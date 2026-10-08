"""A ``Running`` report sets ``RUNNING`` only once the rollout's tasks have finished (#405)."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from styrmin_backend.db.models import ApplicationInstance
from styrmin_backend.db.models import Deployment as DeploymentModel
from styrmin_backend.domain.models import (
    DeploymentState,
    StepKind,
    StepParent,
    Task,
    TaskStatus,
    TaskType,
)
from styrmin_backend.services.deployment_status import report_deployment_statuses
from styrmin_backend.services.steps.recorder import open_step
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork
from tests.unit.steps.conftest import Parents


def _running_report(parents: Parents, instance_id: UUID) -> dict[str, Any]:
    return {
        "deployment_id": parents.deployment_id,
        "instance_id": instance_id,
        "phase": "Ready",
        "display_state": "Running",
        "message": None,
        "conditions": None,
        "managed_resource_counts": None,
    }


async def _set_status(uow: SqlModelUnitOfWork, task: Task, status: TaskStatus) -> None:
    task.status = status
    await uow.tasks.save(task)
    await uow.commit()


async def _deployment_status(uow: SqlModelUnitOfWork, parents: Parents) -> str:
    model = await uow.session.get(DeploymentModel, parents.deployment_id)
    assert model is not None
    await uow.session.refresh(model)
    return model.status.value


async def _pending_deployment(uow: SqlModelUnitOfWork, parents: Parents) -> None:
    model = await uow.session.get(DeploymentModel, parents.deployment_id)
    assert model is not None
    model.status = DeploymentState.PENDING
    await uow.commit()


async def _hook_task(uow: SqlModelUnitOfWork, parents: Parents) -> Task:
    """A finished ``stop_components`` task that the upgrade's hook step started."""
    step = await open_step(
        StepParent.of_task(parents.task.id),
        "hook:upgrade",
        "Run the upgrade hook",
        StepKind.HOOK,
        datetime.now(UTC),
        uow=uow,
    )
    source = await uow.session.get(ApplicationInstance, parents.instance_id)
    assert source is not None
    instance = ApplicationInstance(
        name="stopped-instance",
        application_version=source.application_version,
        status=source.status,
        deployment_id=parents.deployment_id,
        application_driver_version_id=source.application_driver_version_id,
    )
    uow.session.add(instance)
    await uow.session.flush()
    task = Task.create(
        type=TaskType.STOP_COMPONENTS,
        deployment_id=parents.deployment_id,
        status=TaskStatus.SUCCESS,
        instance_id=instance.id,
        started_by_step_id=step.id,
    )
    await uow.tasks.save(task)
    await uow.commit()
    return task


async def test_hook_task_rollout_waits_for_the_upgrade(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _set_status(uow, parents.task, TaskStatus.RUNNING)
    hook_task = await _hook_task(uow, parents)
    await _pending_deployment(uow, parents)
    assert hook_task.instance_id is not None
    report = _running_report(parents, hook_task.instance_id)

    _, updated = await report_deployment_statuses([report], uow)
    assert (updated, await _deployment_status(uow, parents)) == (0, "pending")

    await _set_status(uow, parents.task, TaskStatus.SUCCESS)
    _, updated = await report_deployment_statuses([report], uow)
    assert (updated, await _deployment_status(uow, parents)) == (1, "running")


async def test_rollout_waits_for_its_own_task(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _set_status(uow, parents.task, TaskStatus.RUNNING)
    await _pending_deployment(uow, parents)
    report = _running_report(parents, parents.instance_id)

    _, updated = await report_deployment_statuses([report], uow)
    assert (updated, await _deployment_status(uow, parents)) == (0, "pending")

    await _set_status(uow, parents.task, TaskStatus.SUCCESS)
    _, updated = await report_deployment_statuses([report], uow)
    assert (updated, await _deployment_status(uow, parents)) == (1, "running")


async def test_other_states_do_not_wait_for_the_task(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _set_status(uow, parents.task, TaskStatus.RUNNING)
    await _pending_deployment(uow, parents)
    report = _running_report(parents, parents.instance_id) | {
        "phase": "CreatingHelmRelease",
        "display_state": "Deploying",
    }

    _, updated = await report_deployment_statuses([report], uow)
    assert (updated, await _deployment_status(uow, parents)) == (1, "deploying")
