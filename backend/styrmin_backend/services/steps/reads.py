"""Reads of steps for the API (spec 019, research D9 and D14)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from styrmin_backend.domain.models import Step, StepKind, StepParent, StepStatus, Task
from styrmin_backend.services.steps.exceptions import StepNotFoundError

if TYPE_CHECKING:
    from styrmin_backend.services.unit_of_work import UnitOfWork

#: A running operator-phase step shows "no report" after this long without one.
NO_REPORT_AFTER = timedelta(seconds=60)


async def steps_of_parent(parent: StepParent, uow: UnitOfWork) -> list[Step]:
    """The steps of a task, backup or restore, inside the caller's transaction."""
    if parent.task_id is not None:
        return await uow.steps.list_by_task_ids([parent.task_id])
    if parent.backup_id is not None:
        return await uow.steps.list_by_backup(parent.backup_id)
    if parent.restore_id is not None:
        return await uow.steps.list_by_restore(parent.restore_id)
    return []  # StepParent forbids this.


async def get_step(step_id: UUID, uow: UnitOfWork) -> Step:
    """Get a step by its id."""
    async with uow:
        step = await uow.steps.get(step_id)
        if step is None:
            raise StepNotFoundError(f"Step with id {step_id} not found.")
        return step


async def list_steps(parent: StepParent, uow: UnitOfWork) -> list[Step]:
    """List the steps of a task, backup or restore by start time, pending steps last."""
    async with uow:
        return await steps_of_parent(parent, uow)


async def get_started_tasks(step_id: UUID, uow: UnitOfWork) -> list[Task]:
    """List the tasks that a hook step started, oldest first."""
    async with uow:
        return await uow.tasks.find_started_by_steps([step_id])


async def get_tasks_started_by_task(task_id: UUID, uow: UnitOfWork) -> list[Task]:
    """List the tasks that the steps of a task started, oldest first."""
    async with uow:
        steps = await uow.steps.list_by_task_ids([task_id])
        return await uow.tasks.find_started_by_steps([step.id for step in steps])


async def get_starting_task(task: Task, uow: UnitOfWork) -> Task | None:
    """The task whose step started ``task``; None when no step started it."""
    if task.started_by_step_id is None:
        return None
    async with uow:
        step = await uow.steps.get(task.started_by_step_id)
        if step is None or step.task_id is None:
            return None
        return await uow.tasks.find(step.task_id)


def no_report_since(
    step: Step, last_polled_at: datetime | None, now: datetime
) -> datetime | None:
    """The time of the last agent report while it is too old for a running operator step.

    Without a report, the step's start time stands in for it. Returns ``None``
    for every other step and while the report is recent.
    """
    if (
        step.kind is not StepKind.OPERATOR_PHASE
        or step.status is not StepStatus.RUNNING
    ):
        return None
    reference = last_polled_at or step.started_at
    if reference is None:
        return None
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    return reference if now - reference > NO_REPORT_AFTER else None


async def get_no_report_since(
    step: Step, uow: UnitOfWork, now: datetime | None = None
) -> datetime | None:
    """``no_report_since`` for one step, reading its deployment's last report."""
    if (
        step.kind is not StepKind.OPERATOR_PHASE
        or step.status is not StepStatus.RUNNING
    ):
        return None
    last_polled_at = None
    if step.task_id is not None:
        async with uow:
            task = await uow.tasks.find(step.task_id)
            if task is not None and task.deployment_id is not None:
                status = await uow.deployment_statuses.find_by_deployment(
                    task.deployment_id
                )
                last_polled_at = status.last_polled_at if status is not None else None
    return no_report_since(step, last_polled_at, now or datetime.now(UTC))
