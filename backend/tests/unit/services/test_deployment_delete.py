"""Unit tests for the delete_deployment service (US2 happy path + guards)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from styrmin_backend.domain.models import (
    BackupDisposition,
    Deployment as DeploymentEntity,
    DeploymentState,
    Task as TaskEntity,
    TaskStatus,
    TaskType,
)
from styrmin_backend.services.deployment import delete_deployment
from styrmin_backend.services.exceptions import (
    DeploymentAlreadyDeletedError,
    DeploymentMutationInProgressError,
    DeploymentNotFoundError,
)
from styrmin_backend.workflows.models import PrefectAction, WorkflowInfo


@pytest.fixture
def seeded_deployment(uow) -> DeploymentEntity:
    """Create a RUNNING deployment and persist it through the fake UoW."""
    deployment = DeploymentEntity(
        id=uuid4(),
        name="test-deployment",
        application_version="1.0.0",
        config={},
        parameters={},
        application_driver_version_id=uuid4(),
        environment_id=uuid4(),
        status=DeploymentState.RUNNING,
    )
    # Persist via the fake repo (does not require async context here)
    uow.deployments._deployments.append(deployment)
    return deployment


def _stub_flow(mocker, flow_run_id: UUID | None = None) -> UUID:
    flow_run_id = flow_run_id or uuid4()
    info = mocker.MagicMock(spec=WorkflowInfo)
    info.id = flow_run_id
    return flow_run_id, info


async def test_delete_deployment_happy_path(
    uow, prefect_manager_mock, mocker, seeded_deployment
):
    """A healthy RUNNING deployment transitions to DELETION_REQUESTED and
    creates a DELETE_INSTANCE task with the Prefect flow run id set."""
    flow_run_id, info = _stub_flow(mocker)
    prefect_manager_mock.run_action = mocker.AsyncMock(return_value=info)

    task = await delete_deployment(
        deployment_id=seeded_deployment.id,
        uow=uow,
        backup_disposition=BackupDisposition.RETAIN,
    )

    assert isinstance(task, TaskEntity)
    assert task.type == TaskType.DELETE_INSTANCE
    assert task.status == TaskStatus.PENDING
    assert task.prefect_flow_run_id == flow_run_id
    assert task.deployment_id == seeded_deployment.id

    # Deployment transitioned to DELETION_REQUESTED
    assert uow.deployments._deployments[0].status == DeploymentState.DELETION_REQUESTED

    # Prefect action was dispatched with the expected payload
    prefect_manager_mock.run_action.assert_awaited_once()
    call_kwargs = prefect_manager_mock.run_action.await_args.kwargs
    assert call_kwargs["action"] == PrefectAction.DELETE_INSTANCE
    assert call_kwargs["parameters"]["deployment_id"] == seeded_deployment.id
    assert call_kwargs["parameters"]["backup_disposition"] == "retain"
    # UoW committed
    assert uow.committed is True


async def test_delete_deployment_not_found(uow, prefect_manager_mock):
    with pytest.raises(DeploymentNotFoundError):
        await delete_deployment(
            deployment_id=uuid4(),
            uow=uow,
            backup_disposition=BackupDisposition.RETAIN,
        )


@pytest.mark.parametrize(
    "existing_status",
    [
        DeploymentState.DELETION_REQUESTED,
        DeploymentState.DELETION_IN_PROGRESS,
        DeploymentState.DELETED,
    ],
)
async def test_delete_deployment_idempotent_rejects_repeat(
    uow, prefect_manager_mock, mocker, seeded_deployment, existing_status
):
    """Re-issuing delete against a deployment already in a deletion
    lifecycle state raises DeploymentAlreadyDeletedError and never
    submits a second Prefect flow."""
    seeded_deployment.set_status(existing_status)
    prefect_manager_mock.run_action = mocker.AsyncMock()

    with pytest.raises(DeploymentAlreadyDeletedError):
        await delete_deployment(
            deployment_id=seeded_deployment.id,
            uow=uow,
            backup_disposition=BackupDisposition.RETAIN,
        )

    prefect_manager_mock.run_action.assert_not_called()


async def test_delete_deployment_rejects_when_workflow_in_flight(
    uow, prefect_manager_mock, mocker, seeded_deployment
):
    """If another workflow is running/pending for the deployment, the
    mutation rejects with DeploymentMutationInProgressError and does not
    launch a Prefect flow. The deployment remains in its prior state."""
    active_task = TaskEntity.create(
        type=TaskType.UPDATE_INSTANCE,
        deployment_id=seeded_deployment.id,
    )
    active_task.status = TaskStatus.RUNNING

    mocker.patch.object(
        uow.deployments,
        "list_active_tasks",
        new=mocker.AsyncMock(return_value=[active_task]),
    )
    prefect_manager_mock.run_action = mocker.AsyncMock()

    with pytest.raises(DeploymentMutationInProgressError) as exc:
        await delete_deployment(
            deployment_id=seeded_deployment.id,
            uow=uow,
            backup_disposition=BackupDisposition.RETAIN,
        )

    assert str(active_task.id) in exc.value.active_task_ids
    prefect_manager_mock.run_action.assert_not_called()
    assert uow.deployments._deployments[0].status == DeploymentState.RUNNING


async def test_delete_deployment_propagates_backup_disposition_remove(
    uow, prefect_manager_mock, mocker, seeded_deployment
):
    """REMOVE disposition is passed through to the Prefect flow
    parameters (actual backup teardown is handled by the flow)."""
    _, info = _stub_flow(mocker)
    prefect_manager_mock.run_action = mocker.AsyncMock(return_value=info)

    await delete_deployment(
        deployment_id=seeded_deployment.id,
        uow=uow,
        backup_disposition=BackupDisposition.REMOVE,
    )

    params = prefect_manager_mock.run_action.await_args.kwargs["parameters"]
    assert params["backup_disposition"] == "remove"
