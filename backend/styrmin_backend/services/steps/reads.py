"""Reads of steps for the API (spec 019, research D9 and D14)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from styrmin_backend.domain.models import Step, StepKind, StepParent, StepStatus, Task
from styrmin_backend.services.steps.exceptions import (
    InvalidStartingStepError,
    StepNotFoundError,
)

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


async def list_steps_by_backup(
    backup_ids: Sequence[UUID], uow: UnitOfWork
) -> dict[UUID, list[Step]]:
    """The steps of many backups in one query, keyed by backup, in list order."""
    async with uow:
        steps = await uow.steps.list_by_backup_ids(backup_ids)
    return _group_by(steps, lambda step: step.backup_id)


async def list_steps_by_restore(
    restore_ids: Sequence[UUID], uow: UnitOfWork
) -> dict[UUID, list[Step]]:
    """The steps of many restores in one query, keyed by restore, in list order."""
    async with uow:
        steps = await uow.steps.list_by_restore_ids(restore_ids)
    return _group_by(steps, lambda step: step.restore_id)


def _group_by(
    steps: Iterable[Step], parent_of: Callable[[Step], UUID | None]
) -> dict[UUID, list[Step]]:
    grouped: dict[UUID, list[Step]] = {}
    for step in steps:
        parent_id = parent_of(step)
        if parent_id is not None:
            grouped.setdefault(parent_id, []).append(step)
    return grouped


async def get_started_tasks(step_id: UUID, uow: UnitOfWork) -> list[Task]:
    """List the tasks that a hook step started, oldest first."""
    async with uow:
        return await uow.tasks.find_started_by_steps([step_id])


async def get_tasks_started_by_task(task_id: UUID, uow: UnitOfWork) -> list[Task]:
    """List the tasks that the steps of a task started, oldest first."""
    async with uow:
        steps = await uow.steps.list_by_task_ids([task_id])
        return await uow.tasks.find_started_by_steps([step.id for step in steps])


async def check_starting_step(
    step_id: UUID | None, deployment_id: UUID, uow: UnitOfWork
) -> None:
    """Check that ``step_id`` can start a task of the deployment, inside the caller's transaction.

    Driver actions run in hook steps, and hook steps belong to tasks, so the
    step must be a step of a task of the same deployment. ``None`` passes.

    Raises:
        StepNotFoundError: If ``step_id`` names no step.
        InvalidStartingStepError: If the step is not a step of a task of the deployment.
    """
    if step_id is None:
        return
    step = await uow.steps.get(step_id)
    if step is None:
        raise StepNotFoundError(f"Step with id {step_id} not found.")
    task = await uow.tasks.find(step.task_id) if step.task_id is not None else None
    if task is None or task.deployment_id != deployment_id:
        raise InvalidStartingStepError(
            f"Step {step_id} is not a step of a task of deployment {deployment_id}."
        )


async def get_starting_task(task: Task, uow: UnitOfWork) -> Task | None:
    """The task whose step started ``task``; None when no step started it."""
    if task.started_by_step_id is None:
        return None
    async with uow:
        step = await uow.steps.get(task.started_by_step_id)
        if step is None or step.task_id is None:
            return None
        return await uow.tasks.find(step.task_id)


def waits_for_agent_reports(step: Step) -> bool:
    """Only agent reports move a running operator-phase step forward."""
    return step.kind is StepKind.OPERATOR_PHASE and step.status is StepStatus.RUNNING


def no_report_since(
    step: Step, last_polled_at: datetime | None, now: datetime
) -> datetime | None:
    """The time of the last agent report while it is too old for a running operator step.

    Without a report, the step's start time stands in for it. Returns ``None``
    for every other step and while the report is recent.
    """
    if not waits_for_agent_reports(step):
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
    if not waits_for_agent_reports(step):
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


async def no_report_since_by_step(
    steps: Iterable[Step], tasks: Mapping[UUID, Task], uow: UnitOfWork, now: datetime
) -> dict[UUID, datetime]:
    """``no_report_since`` of many steps, reading the last reports in one query.

    ``tasks`` holds the steps' tasks, which name their deployments. Runs in the
    caller's transaction and queries nothing when no step waits for reports.
    Steps without a notice are left out.
    """
    waiting = [
        (step, _deployment_of(step, tasks))
        for step in steps
        if waits_for_agent_reports(step)
    ]
    statuses = await uow.deployment_statuses.find_by_deployments(
        {deployment_id for _, deployment_id in waiting if deployment_id is not None}
    )
    last_reports = {status.deployment_id: status.last_polled_at for status in statuses}
    notices: dict[UUID, datetime] = {}
    for step, deployment_id in waiting:
        last_report = last_reports.get(deployment_id) if deployment_id else None
        since = no_report_since(step, last_report, now)
        if since is not None:
            notices[step.id] = since
    return notices


def _deployment_of(step: Step, tasks: Mapping[UUID, Task]) -> UUID | None:
    task = tasks.get(step.task_id) if step.task_id is not None else None
    return task.deployment_id if task is not None else None
