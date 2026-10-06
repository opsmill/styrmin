"""The step recorder: the only code that creates or changes steps (spec 019, research D2).

The primitives (``open_step``, ``start_step``, ``succeed_step``, ``fail_step``,
``record_output``, ``add_pending_steps``, ``ensure_operator_steps``,
``fail_open_flow_steps``, and the operator-phase ``add_attempt_error``,
``record_detail`` and ``record_rollback``) run inside the caller's transaction
and do not commit.
``record_event`` is the ``recordStep`` entry point and commits.

State rules (data-model "State transitions of a step"): ``succeeded`` and
``superseded`` are final; ``failed`` is final except for operator-phase steps,
which can start again or succeed with a new attempt. A forbidden transition is
logged and returns the step unchanged, because a late write is not an error.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from loguru import logger
from pydantic import BaseModel

from styrmin_backend.domain.models import (
    Step,
    StepError,
    StepEvent,
    StepKind,
    StepParent,
    StepStatus,
    Task,
)
from styrmin_backend.domain.steps import (
    ROLLOUT_OPERATOR_STEPS,
    STYRMIN_DEPLOYMENT_WRITE,
    StepDefinition,
    truncate_output,
)
from styrmin_backend.services.exceptions import (
    BackupNotFoundError,
    RestoreNotFoundError,
    TaskNotFoundError,
)
from styrmin_backend.services.steps.exceptions import (
    InvalidStepRecordError,
    StepNotFoundError,
)
from styrmin_backend.services.steps.reads import steps_of_parent

if TYPE_CHECKING:
    from collections.abc import Sequence

    from styrmin_backend.services.unit_of_work import UnitOfWork

_OPEN_STATUSES = frozenset({StepStatus.PENDING, StepStatus.RUNNING})
_IN_PROGRESS = frozenset({StepStatus.RUNNING, StepStatus.FAILED})


class StepRecord(BaseModel):
    """One ``recordStep`` call: an event on a step named by id, or by parent and key."""

    event: StepEvent
    step_id: UUID | None = None
    task_id: UUID | None = None
    backup_id: UUID | None = None
    restore_id: UUID | None = None
    key: str | None = None
    name: str | None = None
    kind: StepKind | None = None
    error: str | None = None
    output: str | None = None
    output_truncated: bool = False
    occurred_at: datetime | None = None


def _utc(at: datetime) -> datetime:
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


def _end_time(step: Step, at: datetime) -> datetime:
    """``at``, but never before the step started."""
    if step.started_at is not None and at < step.started_at:
        return step.started_at
    return at


def _ignore(step: Step, transition: str) -> Step:
    logger.info(
        "Ignored {} of step {} ({}) in status {}",
        transition,
        step.id,
        step.key,
        step.status.value,
    )
    return step


async def _lock(step_id: UUID, uow: UnitOfWork) -> Step:
    step = await uow.steps.get(step_id, for_update=True)
    if step is None:
        raise StepNotFoundError(f"Step with id {step_id} not found.")
    return step


async def _save(step: Step, update: dict[str, Any], uow: UnitOfWork) -> Step:
    changed = step.model_copy(update=update)
    await uow.steps.save(changed)
    return changed


async def _start(step: Step, at: datetime, uow: UnitOfWork) -> Step:
    """Start a locked step that already exists."""
    if step.status is StepStatus.RUNNING:
        return step
    if step.status is StepStatus.PENDING:
        update: dict[str, Any] = {"started_at": at}
    elif step.status is StepStatus.FAILED and step.kind is StepKind.OPERATOR_PHASE:
        update = {"ended_at": None}
    else:
        return _ignore(step, "start")
    update |= {"status": StepStatus.RUNNING, "attempt_count": step.attempt_count + 1}
    return await _save(step, update, uow)


async def open_step(
    parent: StepParent,
    key: str,
    name: str,
    kind: StepKind,
    at: datetime,
    *,
    uow: UnitOfWork,
) -> Step:
    """Create a step as running, or start the one the parent already has under ``key``.

    Opening a running step returns it unchanged, so a retried start is harmless.
    """
    at = _utc(at)
    step = Step.create(parent, key, name, kind, StepStatus.RUNNING, at)
    if await uow.steps.insert_if_absent(step):
        return await _lock(step.id, uow)
    existing = await uow.steps.find_by_key(parent, key, for_update=True)
    if existing is None:
        raise StepNotFoundError(f"Step {key} not found.")
    return await _start(existing, at, uow)


async def start_step(step: Step, at: datetime, *, uow: UnitOfWork) -> Step:
    """Start a pending step; a failed operator-phase step starts a new attempt."""
    return await _start(await _lock(step.id, uow), _utc(at), uow)


async def add_pending_steps(
    parent: StepParent,
    definitions: Sequence[StepDefinition],
    at: datetime,
    *,
    uow: UnitOfWork,
) -> None:
    """Create steps that are expected but not started, keeping any the parent already has.

    Their ``created_on`` follows the order of ``definitions``, which lists them.
    """
    at = _utc(at)
    for index, definition in enumerate(definitions):
        step = Step.create(parent, *definition).model_copy(
            update={"created_on": at + timedelta(microseconds=index)}
        )
        await uow.steps.insert_if_absent(step)


async def ensure_operator_steps(task: Task, at: datetime, *, uow: UnitOfWork) -> None:
    """Create the operator-phase steps of a rollout task once its CR write succeeded.

    The prerequisites step starts at ``at``; the others wait for the operator.
    An internal deployment gets none, because the agent does not report its status.
    """
    deployment = await uow.deployments.find(task.deployment_id)
    if deployment is None or deployment.internal:
        return
    parent = StepParent.of_task(task.id)
    first, *others = ROLLOUT_OPERATOR_STEPS
    started = Step.create(parent, *first, StepStatus.RUNNING, _utc(at))
    await uow.steps.insert_if_absent(started)
    await add_pending_steps(parent, others, at, uow=uow)


async def succeed_step(step: Step, at: datetime, *, uow: UnitOfWork) -> Step:
    """End a running step as succeeded; a failed operator-phase step gets a new attempt.

    A pending step is not succeeded: start it first, so it gets a start time.
    """
    locked = await _lock(step.id, uow)
    retried = (
        locked.status is StepStatus.FAILED and locked.kind is StepKind.OPERATOR_PHASE
    )
    if locked.status is not StepStatus.RUNNING and not retried:
        return _ignore(locked, "success")
    update: dict[str, Any] = {
        "status": StepStatus.SUCCEEDED,
        "ended_at": _end_time(locked, _utc(at)),
        "attempt_count": locked.attempt_count + (1 if retried else 0),
    }
    return await _save(locked, update, uow)


async def fail_step(
    step: Step,
    error: str,
    at: datetime,
    *,
    uow: UnitOfWork,
    output: str | None = None,
    output_truncated: bool = False,
) -> Step:
    """End a pending or running step as failed and append ``error`` to its errors.

    ``output``, when given, replaces the stored output as ``record_output`` does.
    """
    at = _utc(at)
    locked = await _lock(step.id, uow)
    if locked.status is StepStatus.PENDING:
        locked = locked.model_copy(
            update={"started_at": at, "attempt_count": locked.attempt_count + 1}
        )
    elif locked.status is not StepStatus.RUNNING:
        return _ignore(locked, "failure")
    entry = StepError(
        attempt=max(locked.attempt_count, 1), message=error, occurred_at=at
    )
    update: dict[str, Any] = {
        "status": StepStatus.FAILED,
        "ended_at": _end_time(locked, at),
        "errors": [*locked.errors, entry],
    }
    if output is not None:
        kept, cut = truncate_output(output)
        update |= {"output": kept, "output_truncated": output_truncated or cut}
    return await _save(locked, update, uow)


async def record_output(
    step: Step, output: str, truncated: bool, *, uow: UnitOfWork
) -> Step:
    """Store the end of a command's output on a step, whatever its status.

    ``truncated`` says the writer already cut earlier output.
    """
    locked = await _lock(step.id, uow)
    kept, cut = truncate_output(output)
    return await _save(
        locked, {"output": kept, "output_truncated": truncated or cut}, uow
    )


async def _lock_in_progress(
    step: Step, transition: str, uow: UnitOfWork
) -> Step | None:
    """Lock a running or failed operator-phase step; None, logged, for any other step."""
    locked = await _lock(step.id, uow)
    if locked.kind is not StepKind.OPERATOR_PHASE or locked.status not in _IN_PROGRESS:
        _ignore(locked, transition)
        return None
    return locked


async def add_attempt_error(
    step: Step,
    error: str,
    at: datetime,
    *,
    uow: UnitOfWork,
    next_attempt: bool = False,
) -> Step:
    """Append ``error`` to the current attempt of a running or failed operator-phase step.

    The status stays. ``next_attempt`` then starts the next attempt of a running
    step, for FluxCD retrying while the operator waits.
    """
    locked = await _lock_in_progress(step, "error", uow)
    if locked is None:
        return step
    entry = StepError(
        attempt=max(locked.attempt_count, 1), message=error, occurred_at=_utc(at)
    )
    update: dict[str, Any] = {"errors": [*locked.errors, entry]}
    if next_attempt and locked.status is StepStatus.RUNNING:
        update["attempt_count"] = locked.attempt_count + 1
    return await _save(locked, update, uow)


async def record_detail(step: Step, detail: str, *, uow: UnitOfWork) -> Step:
    """Store FluxCD's current reason and message on a running or failed operator-phase step."""
    locked = await _lock_in_progress(step, "detail", uow)
    if locked is None or locked.detail == detail:
        return locked or step
    return await _save(locked, {"detail": detail}, uow)


async def record_rollback(
    step: Step,
    at: datetime,
    message: str | None,
    *,
    uow: UnitOfWork,
    next_attempt: bool = False,
) -> Step:
    """Record that FluxCD rolled back or uninstalled the release; a newer rollback replaces it.

    ``next_attempt`` ends the current attempt of a running step and starts the next one.
    """
    at = _utc(at)
    locked = await _lock_in_progress(step, "rollback", uow)
    if locked is None:
        return step
    if locked.rolled_back_at is not None and at <= locked.rolled_back_at:
        return _ignore(locked, "older rollback")
    update: dict[str, Any] = {"rolled_back_at": at, "rollback_message": message}
    if next_attempt and locked.status is StepStatus.RUNNING:
        update["attempt_count"] = locked.attempt_count + 1
    return await _save(locked, update, uow)


async def fail_open_flow_steps(
    parent: StepParent, message: str, at: datetime, *, uow: UnitOfWork
) -> list[Step]:
    """Fail the pending and running steps of a flow kind, when the flow that owns them died.

    Operator-phase steps are left alone. Returns the steps this call failed.
    """
    failed: list[Step] = []
    for step in await steps_of_parent(parent, uow):
        if step.status not in _OPEN_STATUSES or not step.kind.is_flow_kind:
            continue
        result = await fail_step(step, message, at, uow=uow)
        if result.status is StepStatus.FAILED:
            failed.append(result)
    return failed


def _validate(record: StepRecord) -> None:
    parent_count = sum(
        parent_id is not None
        for parent_id in (record.task_id, record.backup_id, record.restore_id)
    )
    if record.step_id is None and (parent_count != 1 or not record.key):
        raise InvalidStepRecordError(
            "Name a stepId, or exactly one of taskId, backupId and restoreId with a key"
        )
    if record.event is StepEvent.FAILED and not record.error:
        raise InvalidStepRecordError("A FAILED event needs an error")
    if record.event is StepEvent.OUTPUT and record.output is None:
        raise InvalidStepRecordError("An OUTPUT event needs output")


def _check_address(record: StepRecord, step: Step) -> None:
    """A record that names a step by id may also name its parent and key; they must match."""
    for given, stored in (
        (record.task_id, step.task_id),
        (record.backup_id, step.backup_id),
        (record.restore_id, step.restore_id),
        (record.key, step.key),
    ):
        if given is not None and given != stored:
            raise InvalidStepRecordError(
                f"Step {step.id} does not belong to the parent and key in the record"
            )


async def _require_parent(parent: StepParent, uow: UnitOfWork) -> None:
    if parent.task_id is not None and await uow.tasks.find(parent.task_id) is None:
        raise TaskNotFoundError(f"Task with id {parent.task_id} not found.")
    if parent.backup_id is not None and await uow.backups.get(parent.backup_id) is None:
        raise BackupNotFoundError(f"Backup with id {parent.backup_id} not found.")
    if (
        parent.restore_id is not None
        and await uow.restores.get(parent.restore_id) is None
    ):
        raise RestoreNotFoundError(f"Restore with id {parent.restore_id} not found.")


async def _step_by_id(record: StepRecord, step_id: UUID, uow: UnitOfWork) -> Step:
    step = await uow.steps.get(step_id)
    if step is None:
        raise StepNotFoundError(f"Step with id {step_id} not found.")
    _check_address(record, step)
    return step


async def _start_by_key(
    record: StepRecord, parent: StepParent, key: str, at: datetime, uow: UnitOfWork
) -> Step:
    if record.name and record.kind is not None:
        return await open_step(parent, key, record.name, record.kind, at, uow=uow)
    existing = await uow.steps.find_by_key(parent, key, for_update=True)
    if existing is None:
        raise InvalidStepRecordError(
            "A STARTED event needs a name and a kind when the step does not exist yet"
        )
    return await _start(existing, at, uow)


async def _after_success(step: Step, uow: UnitOfWork) -> None:
    """A succeeded CR write hands the task's rollout to the operator."""
    if (
        step.status is not StepStatus.SUCCEEDED
        or step.key != STYRMIN_DEPLOYMENT_WRITE.key
        or step.task_id is None
        or step.ended_at is None
    ):
        return
    task = await uow.tasks.find(step.task_id)
    if task is not None:
        await ensure_operator_steps(task, step.ended_at, uow=uow)


async def _apply(record: StepRecord, at: datetime, uow: UnitOfWork) -> Step:
    if record.step_id is not None:
        step = await _step_by_id(record, record.step_id, uow)
        if record.event is StepEvent.STARTED:
            return await _start(await _lock(step.id, uow), at, uow)
    else:
        parent = StepParent(
            task_id=record.task_id,
            backup_id=record.backup_id,
            restore_id=record.restore_id,
        )
        key = record.key or ""  # _validate requires a key here.
        await _require_parent(parent, uow)
        if record.event is StepEvent.STARTED:
            return await _start_by_key(record, parent, key, at, uow)
        found = await uow.steps.find_by_key(parent, key)
        if found is None:
            raise StepNotFoundError(f"Step {key} not found.")
        step = found
    if record.event is StepEvent.SUCCEEDED:
        succeeded = await succeed_step(step, at, uow=uow)
        await _after_success(succeeded, uow)
        return succeeded
    if record.event is StepEvent.FAILED:
        return await fail_step(
            step,
            record.error or "",
            at,
            uow=uow,
            output=record.output,
            output_truncated=record.output_truncated,
        )
    return await record_output(
        step, record.output or "", record.output_truncated, uow=uow
    )


async def record_event(record: StepRecord, uow: UnitOfWork) -> Step:
    """Apply one ``recordStep`` event and commit.

    Raises ``StepNotFoundError``, ``TaskNotFoundError``, ``BackupNotFoundError``,
    ``RestoreNotFoundError`` or ``InvalidStepRecordError``. The event time is
    ``occurred_at`` or the server's time.
    """
    _validate(record)
    at = _utc(record.occurred_at) if record.occurred_at else datetime.now(UTC)
    async with uow:
        step = await _apply(record, at, uow)
        await uow.commit()
        return step
