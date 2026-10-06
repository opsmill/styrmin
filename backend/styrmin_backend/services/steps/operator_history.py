"""The operator phase history: turns each status report into step changes (spec 019, research D6).

A report finds its task by the instance the operator acted on, or, in the
``Deleting`` and ``Deleted`` phases, as the newest delete task of the deployment
(contracts/operator-status.md "Finding the task"). Each reported phase moves
the task's operator-phase steps forward; a later phase succeeds every earlier
step. Only operator-phase steps change; other steps only give start times.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from styrmin_backend.domain import steps
from styrmin_backend.domain.models import Step, StepKind, StepStatus, Task, TaskType
from styrmin_backend.services.steps.recorder import start_step, succeed_step

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from styrmin_backend.domain.steps import StepDefinition
    from styrmin_backend.services.unit_of_work import UnitOfWork

_DELETE_PHASES = frozenset({"Deleting", "Deleted"})
_FINAL_STATUSES = frozenset({StepStatus.SUCCEEDED, StepStatus.SUPERSEDED})

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


async def apply_operator_report(
    report: Mapping[str, Any], now: datetime, uow: UnitOfWork
) -> None:
    """Move the operator-phase steps of the report's task to the reported phase.

    ``report`` is one ``reportDeploymentStatuses`` entry as the service receives
    it; ``now`` is the time of the report. Runs in the caller's transaction and
    does not commit. A report that names no task with open operator-phase steps
    returns before it locks any row.
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
    by_key = {step.key: step for step in task_steps}

    if phase in _DELETE_PHASES:
        await _move_forward(
            _DELETE_STEPS, _DELETE_PROGRESS[phase], by_key, report, now, uow
        )
        return
    if _reports_failure(report):
        return  # Failing a step follows contracts/operator-status.md; not built yet.
    progress = _ROLLOUT_PROGRESS.get(phase or "")
    if progress is not None:
        await _move_forward(
            steps.ROLLOUT_OPERATOR_STEPS, progress, by_key, report, now, uow
        )


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


def _reports_failure(report: Mapping[str, Any]) -> bool:
    return report.get("phase") == "Failed" or report.get("display_state") == "Error"


async def _move_forward(
    sequence: Sequence[StepDefinition],
    progress: int,
    by_key: dict[str, Step],
    report: Mapping[str, Any],
    now: datetime,
    uow: UnitOfWork,
) -> None:
    """Succeed the steps of ``sequence`` before ``progress`` and run the step at it.

    A step starts when the step before it ended, or at the report time.
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
            else:
                step = await _begin(step, start, uow)
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


def _true_since(report: Mapping[str, Any], condition_type: str) -> datetime | None:
    for condition in report.get("conditions") or ():
        if condition.get("type") != condition_type:
            continue
        if condition.get("status") != "True":
            return None
        return _parse_time(condition.get("lastTransitionTime"))
    return None


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
