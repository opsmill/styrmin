"""Unit tests for the delete_deployment service (US2 happy path + guards)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from styrmin_backend.db.models import (
    ApplicationInstance as ApplicationInstanceDBModel,
    Backup as BackupDBModel,
    BackupStatus,
    InstanceStatus,
    Restore as RestoreDBModel,
    RestoreStatus,
)
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
from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
)
from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterContext,
    DeploymentContext,
    EnvironmentContext,
    GlobalContext,
    InstanceContext,
)
from styrmin_backend.context.models.helm import ChartInfo, HelmInfo, RepositoryInfo
from styrmin_backend.domain.models import Instance as InstanceEntity
from styrmin_backend.domain.models import InstanceStatus as InstanceStatusEntity
from styrmin_backend.workflows.models import PrefectAction, WorkflowInfo


def _make_instance(deployment_id: UUID, namespace: str, release: str) -> InstanceEntity:
    context = GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="env", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(),
            deployment_id=deployment_id,
            namespace=namespace,
            release_reference=release,
        ),
        app=ApplicationContext(
            name="app",
            version="1.0.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=uuid4(),
                    name="chart",
                    version="0.1.0",
                    values_template="",
                ),
                repository=RepositoryInfo(id=uuid4(), url="https://example.com"),
            ),
        ),
    )
    return InstanceEntity(
        id=uuid4(),
        name="inst",
        application_version="1.0.0",
        status=InstanceStatusEntity.RUNNING,
        deployment_id=deployment_id,
        application_driver_version_id=uuid4(),
        context=context,
    )


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


def _stub_flow(mocker, flow_run_id: UUID | None = None) -> tuple[UUID, Any]:
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
    # backup_disposition is persisted on the task so the timeline can
    # surface it even after the callback overwrites task.message.
    assert task.parameters == {"backup_disposition": "retain"}

    # Deployment transitioned to DELETION_REQUESTED
    assert uow.deployments._deployments[0].status == DeploymentState.DELETION_REQUESTED

    # Prefect action was dispatched with the expected payload
    prefect_manager_mock.run_action.assert_awaited_once()
    call_kwargs = prefect_manager_mock.run_action.await_args.kwargs
    assert call_kwargs["action"] == PrefectAction.DELETE_INSTANCE
    params = call_kwargs["parameters"]
    assert params["deployment_id"] == seeded_deployment.id
    assert params["backup_disposition"] == "retain"
    # No active instance on this seeded deployment — no cluster targets
    assert params["release_reference"] is None
    assert params["namespace"] is None
    # UoW committed
    assert uow.committed is True


async def test_delete_deployment_not_found(uow, prefect_manager_mock):
    with pytest.raises(DeploymentNotFoundError):
        await delete_deployment(
            deployment_id=uuid4(),
            uow=uow,
            backup_disposition=BackupDisposition.RETAIN,
        )


async def test_delete_deployment_rejects_when_already_tombstoned(
    uow, prefect_manager_mock, mocker, seeded_deployment
):
    """A tombstoned deployment (``status=DELETED``) is terminal — the
    mutation rejects with the typed error and carries the deployment
    id in metadata so the UI can distinguish this from a
    mid-flight deletion."""
    seeded_deployment.set_status(DeploymentState.DELETED)
    prefect_manager_mock.run_action = mocker.AsyncMock()

    with pytest.raises(DeploymentAlreadyDeletedError) as exc:
        await delete_deployment(
            deployment_id=seeded_deployment.id,
            uow=uow,
            backup_disposition=BackupDisposition.RETAIN,
        )

    assert exc.value.error_metadata == {"deployment_id": str(seeded_deployment.id)}
    prefect_manager_mock.run_action.assert_not_called()


@pytest.mark.parametrize(
    "previous_status",
    [
        DeploymentState.DELETION_REQUESTED,
        DeploymentState.DELETION_IN_PROGRESS,
    ],
)
async def test_delete_deployment_admits_retry_after_failed_attempt(
    uow, prefect_manager_mock, mocker, seeded_deployment, previous_status
):
    """A deployment stuck in DELETION_REQUESTED / DELETION_IN_PROGRESS
    with no active task (i.e. the previous attempt failed terminally)
    must accept a fresh retry. The concurrency guard is the only
    thing that blocks in-flight deletions — terminal-failed state is
    recoverable."""
    seeded_deployment.set_status(previous_status)
    # Seed a FAILED DELETE_INSTANCE task as the "previous attempt".
    previous_task = TaskEntity.create(
        type=TaskType.DELETE_INSTANCE,
        deployment_id=seeded_deployment.id,
    )
    previous_task.status = TaskStatus.FAILED
    previous_task.message = "teardown exhausted retries"
    uow.tasks.models.append(previous_task)

    flow_run_id, info = _stub_flow(mocker)
    prefect_manager_mock.run_action = mocker.AsyncMock(return_value=info)

    task = await delete_deployment(
        deployment_id=seeded_deployment.id,
        uow=uow,
        backup_disposition=BackupDisposition.RETAIN,
    )

    # New task was created and the Prefect flow was dispatched.
    assert task.id != previous_task.id
    assert task.status == TaskStatus.PENDING
    assert task.prefect_flow_run_id == flow_run_id
    prefect_manager_mock.run_action.assert_awaited_once()
    # Deployment transitions back to DELETION_REQUESTED for the new attempt.
    assert uow.deployments._deployments[0].status == DeploymentState.DELETION_REQUESTED


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


async def test_delete_deployment_remove_deletes_backups_and_restores(
    uow, prefect_manager_mock, mocker, seeded_deployment
):
    """REMOVE disposition deletes every Backup (and its Restores)
    attached to any ApplicationInstance of the deployment. The Prefect
    flow receives ``backup_disposition=remove`` as a breadcrumb even
    though the iteration has already happened server-side."""
    _, info = _stub_flow(mocker)
    prefect_manager_mock.run_action = mocker.AsyncMock(return_value=info)

    # Two historical instances, three backups total (2 + 1), one restore
    instance_a = ApplicationInstanceDBModel(
        id=uuid4(),
        name="a",
        application_version="1.0.0",
        status=InstanceStatus.RUNNING,
        deployment_id=seeded_deployment.id,
        application_driver_version_id=uuid4(),
    )
    instance_b = ApplicationInstanceDBModel(
        id=uuid4(),
        name="b",
        application_version="1.1.0",
        status=InstanceStatus.RUNNING,
        deployment_id=seeded_deployment.id,
        application_driver_version_id=uuid4(),
    )
    uow.instances.models.extend([instance_a, instance_b])

    backup_a1 = BackupDBModel(
        id=uuid4(),
        name="b-a-1",
        status=BackupStatus.COMPLETED,
        instance_id=instance_a.id,
    )
    backup_a2 = BackupDBModel(
        id=uuid4(),
        name="b-a-2",
        status=BackupStatus.COMPLETED,
        instance_id=instance_a.id,
    )
    backup_b1 = BackupDBModel(
        id=uuid4(),
        name="b-b-1",
        status=BackupStatus.COMPLETED,
        instance_id=instance_b.id,
    )
    uow.backups.models.extend([backup_a1, backup_a2, backup_b1])

    restore_a1 = RestoreDBModel(
        id=uuid4(),
        name="r-a-1",
        status=RestoreStatus.COMPLETED,
        target_namespace="ns",
        backup_id=backup_a1.id,
    )
    uow.restores.models.append(restore_a1)

    await delete_deployment(
        deployment_id=seeded_deployment.id,
        uow=uow,
        backup_disposition=BackupDisposition.REMOVE,
    )

    # Every backup + restore is gone
    assert uow.backups.models == []
    assert uow.restores.models == []
    # Flow still receives the breadcrumb disposition
    params = prefect_manager_mock.run_action.await_args.kwargs["parameters"]
    assert params["backup_disposition"] == "remove"


async def test_delete_deployment_retain_keeps_backups(
    uow, prefect_manager_mock, mocker, seeded_deployment
):
    """RETAIN disposition must not touch backup rows."""
    _, info = _stub_flow(mocker)
    prefect_manager_mock.run_action = mocker.AsyncMock(return_value=info)

    instance = ApplicationInstanceDBModel(
        id=uuid4(),
        name="i",
        application_version="1.0.0",
        status=InstanceStatus.RUNNING,
        deployment_id=seeded_deployment.id,
        application_driver_version_id=uuid4(),
    )
    uow.instances.models.append(instance)

    backup = BackupDBModel(
        id=uuid4(),
        name="b",
        status=BackupStatus.COMPLETED,
        instance_id=instance.id,
    )
    uow.backups.models.append(backup)

    await delete_deployment(
        deployment_id=seeded_deployment.id,
        uow=uow,
        backup_disposition=BackupDisposition.RETAIN,
    )

    assert uow.backups.models == [backup]


async def test_delete_deployment_passes_cluster_targets_from_active_instance(
    uow, prefect_manager_mock, mocker, seeded_deployment
):
    """When the deployment has an active instance, the flow parameters
    include the release_reference + namespace so the flow can issue
    the CRD delete against the right target."""
    _, info = _stub_flow(mocker)
    prefect_manager_mock.run_action = mocker.AsyncMock(return_value=info)

    seeded_deployment.set_active_instance(
        _make_instance(
            deployment_id=seeded_deployment.id,
            namespace="styrmin-demo",
            release="demo-1",
        )
    )

    await delete_deployment(
        deployment_id=seeded_deployment.id,
        uow=uow,
        backup_disposition=BackupDisposition.RETAIN,
    )

    params = prefect_manager_mock.run_action.await_args.kwargs["parameters"]
    assert params["namespace"] == "styrmin-demo"
    assert params["release_reference"] == "demo-1"


# ---------------------------------------------------------------------------
# update_task_state DELETE_INSTANCE branch — invariant: instance status
# is NOT overwritten by the deletion lifecycle callbacks. The instance
# row is a historical snapshot once the deployment is tombstoned; lying
# about it (e.g., marking RUNNING on a torn-down instance) was the bug
# we fixed in the review.
# ---------------------------------------------------------------------------
from styrmin_backend.services.tasks import update_task_state  # noqa: E402


async def _seed_deletion_in_flight(uow, active_instance: InstanceEntity | None = None):
    """Return (deployment, task) pair — deployment has just transitioned
    to DELETION_REQUESTED and a DELETE_INSTANCE task is PENDING."""
    deployment = DeploymentEntity(
        id=uuid4(),
        name="td",
        application_version="1.0.0",
        config={},
        parameters={},
        application_driver_version_id=uuid4(),
        environment_id=uuid4(),
        status=DeploymentState.DELETION_REQUESTED,
    )
    if active_instance is not None:
        deployment.set_active_instance(active_instance)
    uow.deployments._deployments.append(deployment)

    task = TaskEntity.create(type=TaskType.DELETE_INSTANCE, deployment_id=deployment.id)
    uow.tasks.models.append(task)
    return deployment, task


@pytest.mark.parametrize(
    "callback_state, expected_deployment_state",
    [
        ("RUNNING", DeploymentState.DELETION_IN_PROGRESS),
        ("COMPLETED", DeploymentState.DELETED),
    ],
)
async def test_update_task_state_delete_instance_preserves_instance_status(
    uow, callback_state, expected_deployment_state
):
    """Callbacks for DELETE_INSTANCE must drive the deployment lifecycle
    without lying about the historical instance. Previous code set the
    instance status to RUNNING on COMPLETED, painting a torn-down
    instance as live."""
    live_instance = _make_instance(deployment_id=uuid4(), namespace="ns", release="rel")
    live_instance.status = InstanceStatusEntity.RUNNING
    deployment, task = await _seed_deletion_in_flight(
        uow, active_instance=live_instance
    )

    await update_task_state(
        task_id=task.id,
        state_name=callback_state,
        state_message=None,
        uow=uow,
    )

    assert deployment.status == expected_deployment_state
    # Instance status is unchanged — the historical row is a snapshot.
    assert deployment.active_instance is not None
    assert deployment.active_instance.status == InstanceStatusEntity.RUNNING


async def test_update_task_state_delete_instance_failed_stays_retryable(
    uow,
):
    """On FAILED the deployment stays in DELETION_IN_PROGRESS so the
    service's retry path (no active task) can accept a fresh
    attempt. Instance status is untouched."""
    live_instance = _make_instance(deployment_id=uuid4(), namespace="ns", release="rel")
    live_instance.status = InstanceStatusEntity.RUNNING
    deployment, task = await _seed_deletion_in_flight(
        uow, active_instance=live_instance
    )
    deployment.set_status(DeploymentState.DELETION_IN_PROGRESS)

    await update_task_state(
        task_id=task.id,
        state_name="FAILED",
        state_message="finalizer stuck on pvc",
        uow=uow,
    )

    assert task.status == TaskStatus.FAILED
    # Deployment left in DELETION_IN_PROGRESS so the service can admit
    # a retry now that no active task remains.
    assert deployment.status == DeploymentState.DELETION_IN_PROGRESS
    assert deployment.active_instance is not None
    assert deployment.active_instance.status == InstanceStatusEntity.RUNNING
