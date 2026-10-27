"""The operator phase history: turns each status report into step changes (spec 019, research D6).

A report finds its task by the instance the operator acted on, or, in the
``Deleting`` and ``Deleted`` phases, as the newest delete task of the deployment
(contracts/operator-status.md "Finding the task"). A rollout report changes
nothing once a newer task of the deployment wrote the CR or requested the
deletion: the operator no longer works on that instance. Each reported phase moves
the task's operator-phase steps forward; a later phase succeeds every earlier
step. Only operator-phase steps change; other steps only give start times.

A ``Failed`` phase or an ``Error`` display state fails the first unfinished
step with the CR message, and a retry of the operator adds an attempt. FluxCD's
state of the HelmRelease gives the HelmRelease step its reason, its failed
attempts and its rollbacks (contracts/operator-status.md "HelmRelease details").
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from styrmin_backend.agent.status.models import INIT_CONTAINER_KIND, POD_KIND
from styrmin_backend.db.models import PodPhase
from styrmin_backend.domain import steps
from styrmin_backend.domain.models import Step, StepKind, StepStatus, Task, TaskType
from styrmin_backend.services.steps.recorder import (
    add_attempt_error,
    fail_step,
    record_detail,
    record_rollback,
    start_step,
    succeed_step,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from styrmin_backend.domain.steps import StepDefinition
    from styrmin_backend.services.unit_of_work import UnitOfWork

_DELETE_PHASES = frozenset({"Deleting", "Deleted"})
_FINAL_STATUSES = frozenset({StepStatus.SUCCEEDED, StepStatus.SUPERSEDED})
_IN_PROGRESS = frozenset({StepStatus.RUNNING, StepStatus.FAILED})

_DELETE_STEPS = (steps.DELETE_REQUEST, steps.OPERATOR_TEARDOWN)

#: How far each phase has come: the steps before the index succeed, the step at it runs.
_ROLLOUT_PROGRESS = {
    "CreatingPrerequisites": 0,
    "CreatingHelmRelease": 1,
    "CreatingServices": 2,
    "Ready": len(steps.ROLLOUT_OPERATOR_STEPS),
}
_DELETE_PROGRESS = {"Deleting": 1, "Deleted": len(_DELETE_STEPS)}

#: The CR conditions whose transition to True ends each step (the latest one counts).
_END_CONDITIONS: dict[str, tuple[str, ...]] = {
    steps.OPERATOR_PREREQUISITES.key: ("NetworkPoliciesReady", "SecretsReady"),
    steps.OPERATOR_HELMRELEASE.key: ("HelmReleaseReady",),
    steps.OPERATOR_SERVICES.key: ("ServicesReady",),
    steps.OPERATOR_READY.key: ("Ready",),
    steps.OPERATOR_TEARDOWN.key: ("Deleted",),
}

_HELMRELEASE_READY = "HelmReleaseReady"
_HELMRELEASE_REMEDIATED = "HelmReleaseRemediated"
_DEFAULT_FAILURE = "The operator reported a failure"

#: Container reasons of a container that starts or has done its work: they explain nothing.
_STARTING_REASONS = frozenset({"ContainerCreating", "PodInitializing", "Completed"})
#: Reasons whose kubelet message only gives the back-off delay.
_REASONS_WITHOUT_MESSAGE = frozenset({"CrashLoopBackOff"})
_MAX_MESSAGE = 300
_MAX_PODS = 5
#: Finished pods, such as those of a failed Job, are not part of the rollout.
_FINISHED_POD_PHASES = frozenset({PodPhase.SUCCEEDED, PodPhase.FAILED})
_POD_REASON_STEPS = frozenset(
    {steps.OPERATOR_HELMRELEASE.key, steps.OPERATOR_READY.key}
)


async def apply_operator_report(
    report: Mapping[str, Any], now: datetime, uow: UnitOfWork
) -> None:
    """Move the operator-phase steps of the report's task to the reported phase.

    ``report`` is one ``reportDeploymentStatuses`` entry as the service receives
    it; ``now`` is the time of the report. Runs in the caller's transaction and
    does not commit. A report that names no task with open operator-phase steps,
    or a rollout report for a task that a newer task replaced, returns before it
    locks any row.
    """
    phase = report.get("phase")
    task = await _find_task(report, uow)
    if task is None:
        return
    task_steps = await uow.steps.list_by_task_ids([task.id])
    if all(
        step.status in _FINAL_STATUSES
        for step in task_steps
        if step.kind is StepKind.OPERATOR_PHASE
    ):
        return  # Also a task without operator-phase steps.
    if phase not in _DELETE_PHASES and await _replaced(task, uow):
        return
    by_key = {step.key: step for step in task_steps}

    if phase in _DELETE_PHASES:
        await _move_forward(
            _DELETE_STEPS, _DELETE_PROGRESS[phase], by_key, report, now, uow
        )
        return
    failing = _reports_failure(report)
    # Before the step can succeed, so a rollback reported with the ready release is kept.
    detailed = await _detail_helmrelease(report, by_key, now, uow, failing=failing)
    if failing:
        await _apply_failure(report, by_key, now, uow)
        return
    progress = _ROLLOUT_PROGRESS.get(phase or "")
    if progress is None:
        return
    await _move_forward(
        steps.ROLLOUT_OPERATOR_STEPS, progress, by_key, report, now, uow
    )
    if not detailed:
        await _detail_helmrelease(report, by_key, now, uow, failing=False)


async def _find_task(report: Mapping[str, Any], uow: UnitOfWork) -> Task | None:
    deployment_id = report["deployment_id"]
    if report.get("phase") in _DELETE_PHASES:
        return await uow.tasks.find_latest_by_type(
            deployment_id, TaskType.DELETE_DEPLOYMENT
        )
    instance_id = report.get("instance_id")
    if instance_id is None:
        return None  # A CR from before ``instanceId`` existed.
    task = await uow.tasks.find_by_instance(instance_id)
    # The report must come from the task's own deployment.
    if task is None or task.deployment_id != deployment_id:
        return None
    return task


async def _replaced(task: Task, uow: UnitOfWork) -> bool:
    """Whether a newer task of the deployment wrote the CR or requested the deletion."""
    newer = await uow.steps.find_first_newer_task_with_succeeded_step(
        task.id, steps.CR_WRITE_KEYS
    )
    return newer is not None


def _reports_failure(report: Mapping[str, Any]) -> bool:
    return report.get("phase") == "Failed" or report.get("display_state") == "Error"


async def _move_forward(
    sequence: Sequence[StepDefinition],
    progress: int,
    by_key: dict[str, Step],
    report: Mapping[str, Any],
    now: datetime,
    uow: UnitOfWork,
    *,
    start_current: bool = True,
) -> None:
    """Succeed the steps of ``sequence`` before ``progress`` and run the step at it.

    A step starts when the step before it ended, or at the report time.
    ``by_key`` receives the changed steps.
    """
    previous_end: datetime | None = None
    for index, definition in enumerate(sequence[: progress + 1]):
        step = by_key.get(definition.key)
        if step is None:
            continue
        if step.kind is StepKind.OPERATOR_PHASE:
            start = previous_end or now
            if index < progress:
                step = await _finish(
                    step, start, _end_time(step, start, report, now), uow
                )
            elif start_current:
                step = await _begin(step, start, uow)
            by_key[definition.key] = step
        previous_end = step.ended_at


async def _begin(step: Step, start: datetime, uow: UnitOfWork) -> Step:
    """Run a pending step, or a failed one as a new attempt."""
    if step.status in (StepStatus.PENDING, StepStatus.FAILED):
        return await start_step(step, start, uow=uow)
    return step


async def _finish(step: Step, start: datetime, end: datetime, uow: UnitOfWork) -> Step:
    """Succeed a step the operator has moved past; a skipped step starts first."""
    if step.status in _FINAL_STATUSES:
        return step
    if step.status is StepStatus.PENDING:
        step = await start_step(step, start, uow=uow)
    return await succeed_step(step, end, uow=uow)


def _end_time(
    step: Step, start: datetime, report: Mapping[str, Any], now: datetime
) -> datetime:
    """The latest transition to True of the step's end conditions, else the report time.

    A transition before the step started belongs to an earlier rollout and is ignored.
    """
    started_at = step.started_at or start
    times = [
        time
        for time in (
            _true_since(report, condition_type)
            for condition_type in _END_CONDITIONS.get(step.key, ())
        )
        if time is not None
    ]
    if not times:
        return now
    latest = max(times)
    return latest if latest >= started_at else now


# --- Failures and attempts -------------------------------------------------------


async def _apply_failure(
    report: Mapping[str, Any],
    by_key: dict[str, Step],
    now: datetime,
    uow: UnitOfWork,
) -> None:
    """Fail the first unfinished rollout step with the CR message.

    The steps the operator finished first succeed. A step that already failed
    gets a new attempt when the operator restarted the rollout since its newest
    error, and otherwise only a CR message it does not have yet.
    """
    sequence = steps.ROLLOUT_OPERATOR_STEPS
    progress = max(_phase_progress(report), _finished_by_conditions(report, by_key))
    await _move_forward(
        sequence, progress, by_key, report, now, uow, start_current=False
    )
    target, start = _first_unfinished(by_key, now)
    if target is None:
        return
    if target.status is StepStatus.PENDING:
        by_key[target.key] = await start_step(target, start, uow=uow)
        if target.key == steps.OPERATOR_HELMRELEASE.key:
            await _detail_helmrelease(report, by_key, now, uow, failing=True)
        target = by_key[target.key]

    message = report.get("message") or _DEFAULT_FAILURE
    at = _failure_time(report, now)
    if target.status is StepStatus.RUNNING:
        error = await _with_pod_reasons(message, target, report, uow)
        await fail_step(target, error, at, uow=uow)
        return
    if target.status is not StepStatus.FAILED:
        return
    restarted = _restarted_at(report)
    newest = _newest_error_time(target)
    if restarted is not None and (newest is None or restarted > newest):
        target = await start_step(target, restarted, uow=uow)
        error = await _with_pod_reasons(message, target, report, uow)
        await fail_step(target, error, at, uow=uow)
    elif not _has_message(target, message):
        error = await _with_pod_reasons(message, target, report, uow)
        await add_attempt_error(target, error, at, uow=uow)


def _phase_progress(report: Mapping[str, Any]) -> int:
    """How far the phase of a failure report has come; ``Ready`` with an error says nothing."""
    progress = _ROLLOUT_PROGRESS.get(report.get("phase") or "", 0)
    return progress if progress < len(steps.ROLLOUT_OPERATOR_STEPS) else 0


def _finished_by_conditions(report: Mapping[str, Any], by_key: dict[str, Step]) -> int:
    """How many leading rollout steps have all their end conditions True since they started.

    A handler that fails after the prerequisites reports ``Failed`` without a phase in between.
    """
    bound: datetime | None = None
    for index, definition in enumerate(steps.ROLLOUT_OPERATOR_STEPS):
        step = by_key.get(definition.key)
        if step is None:
            return index
        if step.status in _FINAL_STATUSES:
            bound = step.ended_at or bound
            continue
        times = [
            _true_since(report, condition_type)
            for condition_type in _END_CONDITIONS[definition.key]
        ]
        ended = [time for time in times if time is not None]
        if len(ended) != len(times):
            return index
        start = step.started_at or bound
        if start is not None and max(ended) < start:
            return index
        bound = max(ended)
    return len(steps.ROLLOUT_OPERATOR_STEPS)


def _first_unfinished(
    by_key: dict[str, Step], now: datetime
) -> tuple[Step | None, datetime]:
    """The first rollout step that is not final, and when it starts if it is pending."""
    previous_end: datetime | None = None
    for definition in steps.ROLLOUT_OPERATOR_STEPS:
        step = by_key.get(definition.key)
        if step is None:
            continue
        if step.status not in _FINAL_STATUSES:
            return step, previous_end or now
        previous_end = step.ended_at
    return None, now


def _failure_time(report: Mapping[str, Any], now: datetime) -> datetime:
    """The operator's last condition write for a ``Failed`` phase, else the report time.

    A ``Failed`` phase keeps its conditions until the operator works again, so their
    newest time is when it failed, on the operator's clock.
    """
    if report.get("phase") != "Failed":
        return now
    times = [
        time
        for time in (
            _parse_time(condition.get("lastTransitionTime"))
            for condition in report.get("conditions") or ()
        )
        if time is not None
    ]
    return max(times, default=now)


def _restarted_at(report: Mapping[str, Any]) -> datetime | None:
    """When a ``Failed`` CR's handler last ran: it resets ``HelmReleaseReady`` to Progressing."""
    if report.get("phase") != "Failed":
        return None
    condition = _find_condition(report, _HELMRELEASE_READY)
    if (
        condition is None
        or condition.get("status") != "Unknown"
        or condition.get("reason") != "Progressing"
    ):
        return None
    return _parse_time(condition.get("lastTransitionTime"))


def _newest_error_time(step: Step) -> datetime | None:
    return max((error.occurred_at for error in step.errors), default=None)


def _has_message(step: Step, message: str) -> bool:
    """Whether an error of the step starts with ``message``; pod reasons follow it."""
    return any(
        error.message == message or error.message.startswith(f"{message}\n")
        for error in step.errors
    )


async def _with_pod_reasons(
    message: str, step: Step, report: Mapping[str, Any], uow: UnitOfWork
) -> str:
    """Append the pods that are not ready to a HelmRelease or ready-wait error."""
    if step.key not in _POD_REASON_STEPS:
        return message
    reasons = await _pod_reasons(report["deployment_id"], uow)
    return f"{message}\n{reasons}" if reasons else message


async def _pod_reasons(deployment_id: Any, uow: UnitOfWork) -> str | None:
    """``Pods not ready: <pod> (<cause>; …), …`` from the stored pod statuses."""
    entries: list[str] = []
    pods = await uow.pod_statuses.find_by_deployment(deployment_id)
    for pod in sorted(pods, key=lambda pod: pod.pod_name):
        if pod.phase in _FINISHED_POD_PHASES:
            continue
        causes = [
            cause
            for entry in pod.container_statuses or ()
            if isinstance(entry, dict) and (cause := _entry_cause(entry))
        ]
        if causes:
            entries.append(f"{pod.pod_name} ({'; '.join(causes)})")
        if len(entries) == _MAX_PODS:
            break
    return f"Pods not ready: {', '.join(entries)}" if entries else None


def _entry_cause(entry: Mapping[str, Any]) -> str | None:
    """Why one ``containerStatuses`` entry keeps its pod from being ready, or None.

    - The ``pod`` entry of a pod that is not scheduled: ``<reason>: <message>``.
    - A container or init container that waits or ended with a reason other than
      a starting one: ``<name>: <reason>: <message>``.
    - A container or init container that runs again after restarts and is not
      ready: ``<name>: running after <n> restarts``.
    - An init container that runs, is not ready and has not restarted, such as one
      that waits for a service: ``init container <name>: still running``. The pod
      cannot start its containers until it ends.
    """
    kind = entry.get("kind")
    state = entry.get("state")
    reason = _container_reason(state)
    if kind == POD_KIND:
        return _with_message(reason, entry) if reason else None
    name = entry.get("name")
    is_init = kind == INIT_CONTAINER_KIND
    label = f"init container {name}" if is_init else str(name)
    if reason is not None and reason not in _STARTING_REASONS:
        if reason in _REASONS_WITHOUT_MESSAGE:
            return f"{label}: {reason}"
        return f"{label}: {_with_message(reason, entry)}"
    if state != "running" or entry.get("ready"):
        return None
    restarts = entry.get("restart_count")
    if isinstance(restarts, int) and restarts > 0:
        return f"{label}: running after {restarts} restart{'s' if restarts > 1 else ''}"
    return f"{label}: still running" if is_init else None


def _with_message(reason: str, entry: Mapping[str, Any]) -> str:
    """``<reason>: <message>``, the message on one line and cut to ``_MAX_MESSAGE`` characters."""
    message = entry.get("message")
    if not isinstance(message, str) or not message.strip():
        return reason
    text = " ".join(message.split())
    if len(text) > _MAX_MESSAGE:
        text = f"{text[: _MAX_MESSAGE - 1]}…"
    return f"{reason}: {text}"


def _container_reason(state: object) -> str | None:
    """The reason of a stored ``waiting:<reason>`` or ``terminated:<reason>`` state."""
    if not isinstance(state, str):
        return None
    kind, _, reason = state.partition(":")
    return reason if kind in ("waiting", "terminated") and reason else None


# --- HelmRelease details -----------------------------------------------------------


async def _detail_helmrelease(
    report: Mapping[str, Any],
    by_key: dict[str, Step],
    now: datetime,
    uow: UnitOfWork,
    *,
    failing: bool,
) -> bool:
    """Apply FluxCD's state to a running or failed HelmRelease step; False when there is none."""
    step = by_key.get(steps.OPERATOR_HELMRELEASE.key)
    if step is None or step.status not in _IN_PROGRESS:
        return False
    ready = _find_condition(report, _HELMRELEASE_READY)
    if ready is not None and ready.get("status") != "True":
        detail = _reason_and_message(ready)
        if detail and detail != step.detail:
            step = await record_detail(step, detail, uow=uow)
        step = await _record_fluxcd_failure(ready, step, now, uow, failing=failing)
    remediated = _find_condition(report, _HELMRELEASE_REMEDIATED)
    if remediated is not None:
        step = await _record_remediation(remediated, step, uow, failing=failing)
    by_key[step.key] = step
    return True


async def _record_fluxcd_failure(
    ready: Mapping[str, Any],
    step: Step,
    now: datetime,
    uow: UnitOfWork,
    *,
    failing: bool,
) -> Step:
    """Record a ``*Failed`` reason the step does not have yet as a failed attempt.

    On a running step the error joins the current attempt and, unless the operator
    reports a failure, FluxCD's retry starts the next one. On a failed step it joins
    the failed attempt, unless FluxCD rolled that attempt back: then it is a later one.
    """
    if not str(ready.get("reason") or "").endswith("Failed"):
        return step
    at = _parse_time(ready.get("lastTransitionTime"))
    if at is not None and step.started_at is not None and at < step.started_at:
        return step  # An earlier rollout.
    error = _reason_and_message(ready) or ""
    if any(
        recorded.message == error and (at is None or recorded.occurred_at == at)
        for recorded in step.errors
    ):
        return step
    at = at or now
    if step.status is StepStatus.RUNNING:
        return await add_attempt_error(
            step, error, at, uow=uow, next_attempt=not failing
        )
    newest = _newest_error_time(step)
    rolled_back_at = step.rolled_back_at
    if (
        rolled_back_at is not None
        and (newest is None or rolled_back_at > newest)
        and at > rolled_back_at
    ):
        step = await start_step(step, at, uow=uow)
        return await fail_step(step, error, at, uow=uow)
    return await add_attempt_error(step, error, at, uow=uow)


async def _record_remediation(
    remediated: Mapping[str, Any],
    step: Step,
    uow: UnitOfWork,
    *,
    failing: bool,
) -> Step:
    """Record a rollback newer than the step's; it ends an attempt no error ended yet."""
    if remediated.get("status") != "True":
        return step
    at = _parse_time(remediated.get("lastTransitionTime"))
    if at is None or (step.started_at is not None and at < step.started_at):
        return step  # Remediated before this rollout started.
    previous = step.rolled_back_at
    if previous is not None and at <= previous:
        return step
    ended = any(
        (previous is None or error.occurred_at > previous) and error.occurred_at <= at
        for error in step.errors
    )
    return await record_rollback(
        step,
        at,
        remediated.get("message") or None,
        uow=uow,
        next_attempt=not ended and not failing,
    )


# --- Conditions ----------------------------------------------------------------------


def _find_condition(
    report: Mapping[str, Any], condition_type: str
) -> Mapping[str, Any] | None:
    for condition in report.get("conditions") or ():
        if condition.get("type") == condition_type:
            return condition
    return None


def _reason_and_message(condition: Mapping[str, Any]) -> str | None:
    parts = [
        str(part)
        for part in (condition.get("reason"), condition.get("message"))
        if part
    ]
    return ": ".join(parts) or None


def _true_since(report: Mapping[str, Any], condition_type: str) -> datetime | None:
    condition = _find_condition(report, condition_type)
    if condition is None or condition.get("status") != "True":
        return None
    return _parse_time(condition.get("lastTransitionTime"))


def _parse_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
