"""Provides the task services."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from styrmin_backend.domain.models import (
    DeploymentState,
    InstanceStatus,
    Task,
    TaskStatus,
    TaskType,
)
from styrmin_backend.services.exceptions import (
    DeploymentNotFoundError,
    TaskNotFoundError,
    UnknownTaskStateError,
)
from styrmin_backend.services.unit_of_work import UnitOfWork

if TYPE_CHECKING:
    pass


async def get_task(task_id: UUID, uow: UnitOfWork) -> Task:
    """Get a task by its id."""
    async with uow:
        task = await uow.tasks.find(task_id)
        if task is None:
            raise TaskNotFoundError(f"Task with id {task_id} not found.")

        return task


async def get_tasks(uow: UnitOfWork) -> list[Task]:
    """Get all tasks."""
    async with uow:
        tasks = await uow.tasks.all()
        return list(tasks)


async def get_tasks_by_deployment(deployment_id: UUID, uow: UnitOfWork) -> list[Task]:
    """Get all tasks for a deployment, ordered newest-first."""
    async with uow:
        tasks = await uow.tasks.find_by_deployment(deployment_id)
        return list(tasks)


async def update_task_state(
    task_id: UUID,
    state_name: str,
    state_message: str | None,
    uow: UnitOfWork,
) -> None:
    """Update the state of a task."""
    async with uow:
        task = await uow.tasks.find(task_id)
        if task is None:
            raise TaskNotFoundError(f"Task with id {task_id} not found.")

        deployment = await uow.deployments.find(task.deployment_id)
        if deployment is None:
            raise DeploymentNotFoundError(
                f"Deployment with id {task.deployment_id} not found."
            )

        target_task_state = None
        target_deployment_state = None
        target_instance_state: InstanceStatus | None = None
        is_deletion = task.type == TaskType.DELETE_INSTANCE
        # Map the state name to the task, deployment, and instance states.
        # For DELETE_INSTANCE tasks the historical instance row is
        # cosmetic once the deployment is tombstoned — leave its status
        # unchanged (target_instance_state stays None) rather than
        # lying about an instance that's either gone from the cluster
        # (SUCCESS) or possibly still running but un-torn-down
        # (FAILED, pending retry).
        match state_name.upper():
            case "RUNNING":
                target_task_state = TaskStatus.RUNNING
                target_deployment_state = (
                    DeploymentState.DELETION_IN_PROGRESS
                    if is_deletion
                    else DeploymentState.PENDING
                )
                target_instance_state = None if is_deletion else InstanceStatus.PENDING
            case "COMPLETED":
                target_task_state = TaskStatus.SUCCESS
                if is_deletion:
                    target_deployment_state = DeploymentState.DELETED
                else:
                    # Don't set deployment to RUNNING here — the CRD status
                    # reporter will update it when the CRD reaches Ready.
                    target_deployment_state = None
                    target_instance_state = InstanceStatus.RUNNING
            case "FAILED":
                target_task_state = TaskStatus.FAILED
                if is_deletion:
                    # Keep the deployment in DELETION_IN_PROGRESS so a
                    # retry can advance it; the failed task + message
                    # carries the reason. No active-task blockers left,
                    # so delete_deployment() will admit a fresh retry.
                    target_deployment_state = None
                else:
                    target_deployment_state = DeploymentState.FAILED
                    target_instance_state = InstanceStatus.FAILED
            case _:
                raise UnknownTaskStateError(f"Unknown task state: {state_name}")

        task.status = target_task_state
        if target_deployment_state is not None:
            deployment.status = target_deployment_state
        if (
            is_deletion
            and target_deployment_state == DeploymentState.DELETED
            and deployment.deleted_at is None
        ):
            deployment.deleted_at = datetime.now(tz=timezone.utc)
        if target_instance_state is not None and deployment.active_instance is not None:
            deployment.active_instance.status = target_instance_state
        task.message = state_message

        await uow.tasks.save(task)
        await uow.deployments.save(deployment)
        await uow.commit()
