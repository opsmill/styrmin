"""Unit tests for restore operations in BackupService."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

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
from styrmin_backend.db.models import (
    ApplicationInstance,
    Backup,
    BackupStatus,
    Restore,
    RestoreStatus,
)
from styrmin_backend.domain.models import (
    Deployment,
    DeploymentState,
    Instance,
    InstanceStatus,
)
from styrmin_backend.services.backup.service import (
    create_restore,
    get_restore,
    get_restores,
    resolve_restore_target,
    settle_undispatched_restore,
    update_restore_status,
)
from styrmin_backend.services.deployment_status import report_deployment_statuses
from styrmin_backend.services.exceptions import (
    BackupNotFoundError,
    DeletedDeploymentRestoreError,
    DeploymentNotFoundError,
    InternalDeploymentError,
    RestoreAlreadyInProgressError,
    RestoreNotFoundError,
)
from tests.unit.services.fakes import (
    FakeActionRepository,
    FakeApplicationInstanceRepository,
    FakeApplicationRepository,
    FakeBackupRepository,
    FakeClusterRepository,
    FakeDeploymentRepository,
    FakeEnvironmentRepository,
    FakeHelmChartRepository,
    FakeHelmRepositoryRepository,
    FakeRestoreRepository,
    FakeTaskRepository,
    FakeUnitOfWork,
)


def make_uow(
    backups: list[Backup] | None = None,
    restores: list[Restore] | None = None,
    instances: list[ApplicationInstance] | None = None,
    deployments: list[Deployment] | None = None,
) -> FakeUnitOfWork:
    return FakeUnitOfWork(
        clusters=FakeClusterRepository(),
        environments=FakeEnvironmentRepository(),
        helm_repositories=FakeHelmRepositoryRepository(),
        helm_charts=FakeHelmChartRepository(),
        application_driver_versions=FakeApplicationRepository(),
        instances=FakeApplicationInstanceRepository(instances or []),
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        backups=FakeBackupRepository(backups or []),
        restores=FakeRestoreRepository(restores or []),
        deployments=FakeDeploymentRepository(deployments or []),
    )


def make_instance(
    deployment: Deployment,
    *,
    instance_id: UUID | None = None,
    name: str = "test-instance",
) -> Instance:
    """Build a domain instance of *deployment*, to set as its active instance."""
    return Instance(
        id=instance_id or uuid4(),
        name=name,
        application_version="1.0.0",
        status=InstanceStatus.PENDING,
        deployment_id=deployment.id,
        application_driver_version_id=deployment.application_driver_version_id,
        context=GlobalContext(
            cluster=ClusterContext(config=ClusterConfig()),
            environment=EnvironmentContext(
                name="test-environment", config=EnvironmentConfig()
            ),
            deployment=DeploymentContext(config=DeploymentConfig()),
            instance=InstanceContext(
                config=ResolvedConfig(),
                deployment_id=deployment.id,
                namespace=f"styrmin-{deployment.id}",
                release_reference=f"styrmin-{deployment.id}",
            ),
            app=ApplicationContext(
                name="test-app",
                version="1.0.0",
                helm=HelmInfo(
                    chart=ChartInfo(
                        id=uuid4(),
                        name="test-chart",
                        version="0.1.0",
                        values_template="",
                    ),
                    repository=RepositoryInfo(id=uuid4(), url="https://example.com"),
                ),
            ),
        ),
    )


def make_chain(
    backup_status: BackupStatus = BackupStatus.COMPLETED,
    deployment_status: DeploymentState = DeploymentState.RUNNING,
    deployment_internal: bool = False,
    *,
    with_active_instance: bool = False,
) -> tuple[Deployment, ApplicationInstance, Backup]:
    """Build a deployment + instance + backup linked chain for restore tests.

    With ``with_active_instance``, the backup's instance is also the
    deployment's active instance: the returned instance's id is the id the
    active instance carries.
    """
    deployment = Deployment(
        id=uuid4(),
        name="test-deployment",
        application_version="1.0.0",
        config=None,
        application_driver_version_id=uuid4(),
        environment_id=uuid4(),
        status=deployment_status,
        internal=deployment_internal,
        created_by_user_id=uuid4(),
    )
    instance = ApplicationInstance(
        application_version="1.0.0",
        deployment_id=deployment.id,
    )
    backup = Backup(
        name="test-backup",
        status=backup_status,
        instance_id=instance.id,
    )
    if with_active_instance:
        deployment.set_active_instance(
            instance=make_instance(deployment, instance_id=instance.id)
        )
    return deployment, instance, backup


class TestCreateRestore:
    @pytest.mark.anyio
    async def test_create_restore_success(self) -> None:
        deployment, instance, backup = make_chain(with_active_instance=True)
        uow = make_uow(backups=[backup], instances=[instance], deployments=[deployment])

        restore, deployment_id = await create_restore(
            backup_id=backup.id,
            uow=uow,
        )

        assert restore.status == RestoreStatus.PENDING
        assert restore.target_namespace == f"styrmin-{deployment.id}"
        assert restore.target_instance_id == instance.id
        assert restore.backup_id == backup.id
        assert restore.name == f"styrmin-{restore.id}"
        assert deployment_id == deployment.id
        # The deployment must be flipped to RESTORING in the same transaction.
        stored = await uow.deployments.find(deployment.id)
        assert stored is not None
        assert stored.status == DeploymentState.RESTORING
        assert uow.committed is True

    @pytest.mark.anyio
    async def test_create_restore_custom_name(self) -> None:
        deployment, instance, backup = make_chain()
        uow = make_uow(backups=[backup], instances=[instance], deployments=[deployment])

        restore, _ = await create_restore(
            backup_id=backup.id,
            name="my-custom-restore",
            uow=uow,
        )

        assert restore.name == "my-custom-restore"

    @pytest.mark.anyio
    async def test_create_restore_records_the_active_instance_not_the_backups(
        self,
    ) -> None:
        """#532, ADR-063: a backup of an earlier instance lands in the active one."""
        deployment, earlier_instance, backup = make_chain()
        active_instance = make_instance(deployment)
        deployment.set_active_instance(instance=active_instance)
        uow = make_uow(
            backups=[backup], instances=[earlier_instance], deployments=[deployment]
        )

        restore, deployment_id = await create_restore(
            backup_id=backup.id,
            uow=uow,
        )

        assert deployment_id == deployment.id
        assert restore.target_namespace == f"styrmin-{deployment.id}"
        assert restore.target_instance_id == active_instance.id

    @pytest.mark.anyio
    async def test_create_restore_backup_not_found(self) -> None:
        uow = make_uow()

        with pytest.raises(BackupNotFoundError):
            await create_restore(
                backup_id=uuid4(),
                uow=uow,
            )

    @pytest.mark.anyio
    async def test_create_restore_internal_deployment_rejected(self) -> None:
        deployment, instance, backup = make_chain(deployment_internal=True)
        uow = make_uow(backups=[backup], instances=[instance], deployments=[deployment])

        with pytest.raises(InternalDeploymentError):
            await create_restore(
                backup_id=backup.id,
                uow=uow,
            )

    @pytest.mark.anyio
    async def test_create_restore_deleted_deployment_rejected(self) -> None:
        """A deleted deployment keeps its backups, but a restore into it is refused."""
        deployment, instance, backup = make_chain(
            deployment_status=DeploymentState.DELETED
        )
        deployment.deleted_at = datetime(2026, 10, 8, tzinfo=UTC)
        uow = make_uow(backups=[backup], instances=[instance], deployments=[deployment])

        with pytest.raises(DeletedDeploymentRestoreError, match="was deleted") as exc:
            await create_restore(
                backup_id=backup.id,
                uow=uow,
            )

        assert exc.value.error_code == "OPERATION_DENIED"
        stored = await uow.deployments.find(deployment.id)
        assert stored is not None
        assert stored.status == DeploymentState.DELETED
        assert await uow.restores.get_all() == []

    @pytest.mark.anyio
    async def test_create_restore_blocks_when_already_restoring(self) -> None:
        """Concurrency guard: a restore still in flight for the target wins."""
        deployment, instance, backup = make_chain(
            deployment_status=DeploymentState.RESTORING
        )
        existing_restore = Restore(
            name="existing-restore",
            status=RestoreStatus.IN_PROGRESS,
            target_namespace=f"styrmin-{deployment.id}",
            backup_id=backup.id,
        )
        uow = make_uow(
            backups=[backup],
            restores=[existing_restore],
            instances=[instance],
            deployments=[deployment],
        )

        with pytest.raises(RestoreAlreadyInProgressError) as excinfo:
            await create_restore(
                backup_id=backup.id,
                uow=uow,
            )

        # The refusal names the restore it collided with — never "unknown".
        assert excinfo.value.existing_restore_id == str(existing_restore.id)

    @pytest.mark.anyio
    async def test_create_restore_blocks_while_the_first_is_still_pending(self) -> None:
        """The dispatch window counts: rows are written PENDING, not IN_PROGRESS.

        ``create_restore`` creates the row ``PENDING`` and only
        ``execute_restore_workflow`` promotes it to ``IN_PROGRESS``, so a second
        request landing before the flow starts must still be refused — and must
        name the pending row.
        """
        deployment, instance, backup = make_chain(
            deployment_status=DeploymentState.RESTORING
        )
        pending_restore = Restore(
            name="pending-restore",
            status=RestoreStatus.PENDING,
            target_namespace=f"styrmin-{deployment.id}",
            backup_id=backup.id,
        )
        uow = make_uow(
            backups=[backup],
            restores=[pending_restore],
            instances=[instance],
            deployments=[deployment],
        )

        with pytest.raises(RestoreAlreadyInProgressError) as excinfo:
            await create_restore(
                backup_id=backup.id,
                uow=uow,
            )

        assert excinfo.value.existing_restore_id == str(pending_restore.id)

    @pytest.mark.anyio
    async def test_create_restore_blocks_on_a_restore_into_another_namespace(
        self,
    ) -> None:
        """A restore of this deployment's other backup into another namespace,
        as an earlier release let the client choose, is still in flight for
        this deployment."""
        deployment, instance, backup = make_chain()
        other_backup = Backup(
            name="other-backup",
            status=BackupStatus.COMPLETED,
            instance_id=instance.id,
        )
        in_flight = Restore(
            name="custom-namespace-restore",
            status=RestoreStatus.IN_PROGRESS,
            target_namespace="custom-ns",
            backup_id=other_backup.id,
        )
        uow = make_uow(
            backups=[backup, other_backup],
            restores=[in_flight],
            instances=[instance],
            deployments=[deployment],
        )

        with pytest.raises(RestoreAlreadyInProgressError) as excinfo:
            await create_restore(
                backup_id=backup.id,
                uow=uow,
            )

        assert excinfo.value.existing_restore_id == str(in_flight.id)

    @pytest.mark.anyio
    async def test_clone_restore_of_another_backup_does_not_block(self) -> None:
        """An environment clone restoring this deployment's other backup into
        its counterpart's namespace does not touch this deployment."""
        deployment, instance, backup = make_chain()
        other_backup = Backup(
            name="other-backup",
            status=BackupStatus.COMPLETED,
            instance_id=instance.id,
        )
        clone_restore = Restore(
            name="clone-restore",
            status=RestoreStatus.IN_PROGRESS,
            target_namespace=f"styrmin-{uuid4()}",
            backup_id=other_backup.id,
        )
        uow = make_uow(
            backups=[backup, other_backup],
            restores=[clone_restore],
            instances=[instance],
            deployments=[deployment],
        )

        restore, deployment_id = await create_restore(
            backup_id=backup.id,
            uow=uow,
        )

        assert deployment_id == deployment.id
        assert restore.status == RestoreStatus.PENDING

    @pytest.mark.anyio
    async def test_restoring_state_without_an_in_flight_restore_does_not_block(
        self,
    ) -> None:
        """A deployment left in RESTORING by a dead restore is not a conflict.

        Refusing here could name no restore ("unknown"), which is the tell that
        there is nothing to be concurrent with: the only rows for this
        deployment are terminal, so a fresh restore is exactly the recovery the
        operator wants.
        """
        deployment, instance, backup = make_chain(
            deployment_status=DeploymentState.RESTORING
        )
        dead_restore = Restore(
            name="dead-restore",
            status=RestoreStatus.FAILED,
            target_namespace=f"styrmin-{deployment.id}",
            backup_id=backup.id,
        )
        uow = make_uow(
            backups=[backup],
            restores=[dead_restore],
            instances=[instance],
            deployments=[deployment],
        )

        restore, deployment_id = await create_restore(
            backup_id=backup.id,
            uow=uow,
        )

        assert restore.status == RestoreStatus.PENDING
        assert deployment_id == deployment.id

    @pytest.mark.anyio
    async def test_create_restore_already_in_progress(self) -> None:
        """One backup cannot be replayed twice concurrently, wherever aimed.

        The restore in flight is a row an earlier release created into another
        deployment's namespace, so only the same-backup guard can find it.
        """
        deployment, instance, backup = make_chain()
        existing_restore = Restore(
            name="existing-restore",
            status=RestoreStatus.IN_PROGRESS,
            target_namespace=f"styrmin-{uuid4()}",
            backup_id=backup.id,
        )
        uow = make_uow(
            backups=[backup],
            restores=[existing_restore],
            instances=[instance],
            deployments=[deployment],
        )

        with pytest.raises(RestoreAlreadyInProgressError) as excinfo:
            await create_restore(
                backup_id=backup.id,
                uow=uow,
            )

        assert excinfo.value.existing_restore_id == str(existing_restore.id)

    @pytest.mark.anyio
    async def test_create_restore_completed_does_not_block(self) -> None:
        """A completed restore should not block creation of a new one."""
        deployment, instance, backup = make_chain()
        completed_restore = Restore(
            name="completed-restore",
            status=RestoreStatus.COMPLETED,
            target_namespace=f"styrmin-{deployment.id}",
            backup_id=backup.id,
        )
        uow = make_uow(
            backups=[backup],
            restores=[completed_restore],
            instances=[instance],
            deployments=[deployment],
        )

        restore, _ = await create_restore(
            backup_id=backup.id,
            uow=uow,
        )

        assert restore.status == RestoreStatus.PENDING


class TestGetRestore:
    @pytest.mark.anyio
    async def test_get_restore_found(self) -> None:
        backup_id = uuid4()
        existing = Restore(
            name="test-restore",
            status=RestoreStatus.COMPLETED,
            target_namespace="test-ns",
            backup_id=backup_id,
        )
        uow = make_uow(restores=[existing])

        result = await get_restore(restore_id=existing.id, uow=uow)
        assert result.id == existing.id

    @pytest.mark.anyio
    async def test_get_restore_not_found(self) -> None:
        uow = make_uow()

        with pytest.raises(RestoreNotFoundError):
            await get_restore(restore_id=uuid4(), uow=uow)


class TestGetRestores:
    @pytest.mark.anyio
    async def test_get_restores_by_backup(self) -> None:
        backup_id = uuid4()
        other_backup_id = uuid4()
        r1 = Restore(
            name="r1",
            status=RestoreStatus.COMPLETED,
            target_namespace="ns-1",
            backup_id=backup_id,
        )
        r2 = Restore(
            name="r2",
            status=RestoreStatus.PENDING,
            target_namespace="ns-2",
            backup_id=backup_id,
        )
        r3 = Restore(
            name="r3",
            status=RestoreStatus.COMPLETED,
            target_namespace="ns-3",
            backup_id=other_backup_id,
        )
        uow = make_uow(restores=[r1, r2, r3])

        results = await get_restores(backup_id=backup_id, uow=uow)
        assert len(results) == 2

    @pytest.mark.anyio
    async def test_get_restores_with_status_filter(self) -> None:
        backup_id = uuid4()
        r1 = Restore(
            name="r1",
            status=RestoreStatus.COMPLETED,
            target_namespace="ns-1",
            backup_id=backup_id,
        )
        r2 = Restore(
            name="r2",
            status=RestoreStatus.PENDING,
            target_namespace="ns-2",
            backup_id=backup_id,
        )
        uow = make_uow(restores=[r1, r2])

        results = await get_restores(
            backup_id=backup_id, uow=uow, status=RestoreStatus.COMPLETED
        )
        assert len(results) == 1
        assert results[0].name == "r1"


class TestUpdateRestoreStatus:
    @pytest.mark.anyio
    async def test_update_to_in_progress(self) -> None:
        backup_id = uuid4()
        restore = Restore(
            name="test-restore",
            status=RestoreStatus.PENDING,
            target_namespace="test-ns",
            backup_id=backup_id,
        )
        uow = make_uow(restores=[restore])

        result = await update_restore_status(
            restore_id=restore.id,
            status=RestoreStatus.IN_PROGRESS,
            uow=uow,
        )

        assert result.status == RestoreStatus.IN_PROGRESS
        assert result.started_at is not None

    @pytest.mark.anyio
    async def test_update_to_completed(self) -> None:
        backup_id = uuid4()
        restore = Restore(
            name="test-restore",
            status=RestoreStatus.IN_PROGRESS,
            target_namespace="test-ns",
            backup_id=backup_id,
        )
        uow = make_uow(restores=[restore])

        result = await update_restore_status(
            restore_id=restore.id,
            status=RestoreStatus.COMPLETED,
            uow=uow,
        )

        assert result.status == RestoreStatus.COMPLETED
        assert result.completed_at is not None

    @pytest.mark.anyio
    async def test_update_to_failed_with_error(self) -> None:
        backup_id = uuid4()
        restore = Restore(
            name="test-restore",
            status=RestoreStatus.IN_PROGRESS,
            target_namespace="test-ns",
            backup_id=backup_id,
        )
        uow = make_uow(restores=[restore])

        result = await update_restore_status(
            restore_id=restore.id,
            status=RestoreStatus.FAILED,
            uow=uow,
            error_message="Namespace conflict",
        )

        assert result.status == RestoreStatus.FAILED
        assert result.error_message == "Namespace conflict"
        assert result.completed_at is not None

    @pytest.mark.anyio
    async def test_update_not_found(self) -> None:
        uow = make_uow()

        with pytest.raises(RestoreNotFoundError):
            await update_restore_status(
                restore_id=uuid4(),
                status=RestoreStatus.COMPLETED,
                uow=uow,
            )

    @pytest.mark.anyio
    async def test_update_component_statuses(self) -> None:
        backup_id = uuid4()
        restore = Restore(
            name="test-restore",
            status=RestoreStatus.IN_PROGRESS,
            target_namespace="test-ns",
            backup_id=backup_id,
        )
        uow = make_uow(restores=[restore])

        component_statuses = {
            "web": {"status": "completed"},
            "db": {"status": "failed", "error_message": "DB restore failed"},
        }

        result = await update_restore_status(
            restore_id=restore.id,
            status=RestoreStatus.FAILED,
            uow=uow,
            component_statuses=component_statuses,
        )

        assert result.component_statuses == component_statuses


DISPATCH_ERROR = "the restore was created but its workflow was never dispatched: boom"


async def create_undispatched_restore(
    deployment_status: DeploymentState = DeploymentState.RUNNING,
) -> tuple[FakeUnitOfWork, Restore, Deployment]:
    """A restore ``create_restore`` committed, whose dispatch then failed."""
    deployment, instance, backup = make_chain(deployment_status=deployment_status)
    uow = make_uow(backups=[backup], instances=[instance], deployments=[deployment])
    restore, _ = await create_restore(
        backup_id=backup.id,
        uow=uow,
    )
    return uow, restore, deployment


class TestSettleUndispatchedRestore:
    @pytest.mark.anyio
    async def test_fails_the_restore_and_the_restoring_deployment(self) -> None:
        uow, restore, deployment = await create_undispatched_restore()
        commits_before = uow.commit_count

        result = await settle_undispatched_restore(
            restore_id=restore.id,
            deployment_id=deployment.id,
            uow=uow,
            error=DISPATCH_ERROR,
        )

        assert result is restore
        assert restore.status == RestoreStatus.FAILED
        assert restore.error_message == DISPATCH_ERROR
        assert restore.completed_at is not None
        stored = await uow.deployments.find(deployment.id)
        assert stored is not None
        assert stored.status == DeploymentState.FAILED
        # One transaction for both rows.
        assert uow.commit_count == commits_before + 1

    @pytest.mark.anyio
    async def test_status_reports_apply_again_after_settling(self) -> None:
        """#395 review: a PENDING row left by a failed dispatch made every
        status report skip the deployment, holding it in RESTORING."""
        uow, restore, deployment = await create_undispatched_restore()

        await settle_undispatched_restore(
            restore_id=restore.id,
            deployment_id=deployment.id,
            uow=uow,
            error=DISPATCH_ERROR,
        )
        await report_deployment_statuses(
            [
                {
                    "deployment_id": deployment.id,
                    "phase": "Ready",
                    "display_state": "Running",
                }
            ],
            uow,
        )

        stored = await uow.deployments.find(deployment.id)
        assert stored is not None
        assert stored.status == DeploymentState.RUNNING

    @pytest.mark.anyio
    async def test_leaves_a_deployment_that_is_no_longer_restoring(self) -> None:
        uow, restore, deployment = await create_undispatched_restore()
        stored = await uow.deployments.find(deployment.id)
        assert stored is not None
        stored.status = DeploymentState.DELETING

        await settle_undispatched_restore(
            restore_id=restore.id,
            deployment_id=deployment.id,
            uow=uow,
            error=DISPATCH_ERROR,
        )

        assert restore.status == RestoreStatus.FAILED
        assert stored.status == DeploymentState.DELETING

    @pytest.mark.anyio
    async def test_leaves_a_restore_the_workflow_already_picked_up(self) -> None:
        uow, restore, deployment = await create_undispatched_restore()
        restore.status = RestoreStatus.IN_PROGRESS

        result = await settle_undispatched_restore(
            restore_id=restore.id,
            deployment_id=deployment.id,
            uow=uow,
            error=DISPATCH_ERROR,
        )

        assert result is restore
        assert restore.status == RestoreStatus.IN_PROGRESS
        assert restore.error_message is None
        stored = await uow.deployments.find(deployment.id)
        assert stored is not None
        assert stored.status == DeploymentState.RESTORING

    @pytest.mark.anyio
    async def test_missing_restore_row_still_fails_the_deployment(self) -> None:
        deployment, _, _ = make_chain(deployment_status=DeploymentState.RESTORING)
        uow = make_uow(deployments=[deployment])

        result = await settle_undispatched_restore(
            restore_id=uuid4(),
            deployment_id=deployment.id,
            uow=uow,
            error=DISPATCH_ERROR,
        )

        assert result is None
        stored = await uow.deployments.find(deployment.id)
        assert stored is not None
        assert stored.status == DeploymentState.FAILED

    @pytest.mark.anyio
    async def test_missing_deployment_row_still_fails_the_restore(self) -> None:
        restore = Restore(
            name="test-restore",
            status=RestoreStatus.PENDING,
            target_namespace="test-ns",
            backup_id=uuid4(),
        )
        uow = make_uow(restores=[restore])

        result = await settle_undispatched_restore(
            restore_id=restore.id,
            deployment_id=uuid4(),
            uow=uow,
            error=DISPATCH_ERROR,
        )

        assert result is restore
        assert restore.status == RestoreStatus.FAILED
        assert restore.error_message == DISPATCH_ERROR

    @pytest.mark.anyio
    async def test_a_failed_write_does_not_raise(self) -> None:
        uow, restore, deployment = await create_undispatched_restore()

        async def failing_commit() -> None:
            raise RuntimeError("database is down")

        uow.commit = failing_commit  # type: ignore[method-assign]

        result = await settle_undispatched_restore(
            restore_id=restore.id,
            deployment_id=deployment.id,
            uow=uow,
            error=DISPATCH_ERROR,
        )

        assert result is None


def make_counterpart(
    *,
    status: DeploymentState = DeploymentState.RESTORING,
    internal: bool = False,
    with_active_instance: bool = True,
) -> tuple[Deployment, Instance | None]:
    """Build a clone counterpart deployment, optionally with an active instance."""
    deployment = Deployment(
        id=uuid4(),
        name="counterpart-deployment",
        application_version="1.0.0",
        config=None,
        application_driver_version_id=uuid4(),
        environment_id=uuid4(),
        status=status,
        internal=internal,
        created_by_user_id=uuid4(),
    )
    if not with_active_instance:
        return deployment, None
    instance = make_instance(deployment, name="counterpart-instance")
    deployment.set_active_instance(instance=instance)
    return deployment, instance


class TestResolveRestoreTarget:
    """#532 — Styrmin, not the caller, decides where a restore lands."""

    @pytest.mark.anyio
    async def test_in_place_backup_of_the_active_instance(self) -> None:
        deployment, instance, backup = make_chain(with_active_instance=True)
        uow = make_uow(backups=[backup], instances=[instance], deployments=[deployment])

        async with uow:
            target = await resolve_restore_target(backup, uow)

        assert target.deployment.id == deployment.id
        assert target.namespace == f"styrmin-{deployment.id}"
        assert target.instance_id == instance.id

    @pytest.mark.anyio
    async def test_in_place_backup_of_an_earlier_instance_records_the_active_instance(
        self,
    ) -> None:
        """ADR-063: the data lands in the active instance, not the backup's."""
        deployment, earlier_instance, backup = make_chain()
        active_instance = make_instance(deployment)
        deployment.set_active_instance(instance=active_instance)
        uow = make_uow(
            backups=[backup], instances=[earlier_instance], deployments=[deployment]
        )

        async with uow:
            target = await resolve_restore_target(backup, uow)

        assert target.deployment.id == deployment.id
        assert target.namespace == f"styrmin-{deployment.id}"
        assert target.instance_id == active_instance.id
        assert target.instance_id != earlier_instance.id

    @pytest.mark.anyio
    async def test_in_place_deployment_without_an_active_instance(self) -> None:
        deployment, instance, backup = make_chain()
        uow = make_uow(backups=[backup], instances=[instance], deployments=[deployment])

        async with uow:
            target = await resolve_restore_target(backup, uow)

        assert target.deployment.id == deployment.id
        assert target.namespace == f"styrmin-{deployment.id}"
        assert target.instance_id is None

    @pytest.mark.anyio
    async def test_cross_target_resolves_the_counterpart(self) -> None:
        source, instance, backup = make_chain(with_active_instance=True)
        counterpart, counterpart_instance = make_counterpart()
        assert counterpart_instance is not None
        uow = make_uow(
            backups=[backup],
            instances=[instance],
            deployments=[source, counterpart],
        )

        async with uow:
            target = await resolve_restore_target(
                backup, uow, target_deployment_id=counterpart.id
            )

        assert target.deployment.id == counterpart.id
        assert target.namespace == f"styrmin-{counterpart.id}"
        assert target.instance_id == counterpart_instance.id

    @pytest.mark.anyio
    async def test_in_place_backup_instance_missing_raises_backup_not_found(
        self,
    ) -> None:
        deployment, _, backup = make_chain(with_active_instance=True)
        uow = make_uow(backups=[backup], deployments=[deployment])

        with pytest.raises(BackupNotFoundError):
            async with uow:
                await resolve_restore_target(backup, uow)

    @pytest.mark.anyio
    async def test_in_place_instance_without_a_deployment_raises_backup_not_found(
        self,
    ) -> None:
        deployment, instance, backup = make_chain(with_active_instance=True)
        instance.deployment_id = None  # type: ignore[assignment]
        uow = make_uow(backups=[backup], instances=[instance], deployments=[deployment])

        with pytest.raises(BackupNotFoundError):
            async with uow:
                await resolve_restore_target(backup, uow)

    @pytest.mark.anyio
    async def test_in_place_deployment_missing_raises_backup_not_found(self) -> None:
        _, instance, backup = make_chain(with_active_instance=True)
        uow = make_uow(backups=[backup], instances=[instance])

        with pytest.raises(BackupNotFoundError):
            async with uow:
                await resolve_restore_target(backup, uow)

    @pytest.mark.anyio
    async def test_cross_target_counterpart_missing_raises_deployment_not_found(
        self,
    ) -> None:
        source, instance, backup = make_chain(with_active_instance=True)
        uow = make_uow(backups=[backup], instances=[instance], deployments=[source])

        with pytest.raises(DeploymentNotFoundError):
            async with uow:
                await resolve_restore_target(backup, uow, target_deployment_id=uuid4())


class TestCreateRestoreCrossTarget:
    """research D2.1 — ``target_deployment_id`` moves every guard to the target."""

    @pytest.mark.anyio
    async def test_flips_the_target_and_leaves_the_source_untouched(self) -> None:
        source, instance, backup = make_chain()
        counterpart, counterpart_instance = make_counterpart(
            status=DeploymentState.PENDING
        )
        assert counterpart_instance is not None
        uow = make_uow(
            backups=[backup],
            instances=[instance],
            deployments=[source, counterpart],
        )

        restore, deployment_id = await create_restore(
            backup_id=backup.id,
            uow=uow,
            target_deployment_id=counterpart.id,
        )

        # The returned id is the status-write target, i.e. the counterpart.
        assert deployment_id == counterpart.id
        assert restore.target_namespace == f"styrmin-{counterpart.id}"
        # The counterpart is the one flipped to RESTORING ...
        stored_counterpart = await uow.deployments.find(counterpart.id)
        assert stored_counterpart is not None
        assert stored_counterpart.status == DeploymentState.RESTORING
        # ... and the source is never mutated (SC-002).
        stored_source = await uow.deployments.find(source.id)
        assert stored_source is not None
        assert stored_source.status == DeploymentState.RUNNING
        # The counterpart's active instance is recorded for attribution.
        assert restore.target_instance_id == counterpart_instance.id
        assert uow.committed is True

    @pytest.mark.anyio
    async def test_records_the_counterparts_active_instance_not_the_sources(
        self,
    ) -> None:
        """#532: the row records the instance the data lands in, whose id the
        caller can no longer pass."""
        source, instance, backup = make_chain(with_active_instance=True)
        counterpart, counterpart_instance = make_counterpart(
            status=DeploymentState.PENDING
        )
        assert counterpart_instance is not None
        uow = make_uow(
            backups=[backup],
            instances=[instance],
            deployments=[source, counterpart],
        )

        restore, _ = await create_restore(
            backup_id=backup.id,
            uow=uow,
            target_deployment_id=counterpart.id,
        )

        assert restore.target_namespace == f"styrmin-{counterpart.id}"
        assert restore.target_instance_id == counterpart_instance.id
        assert restore.target_instance_id != instance.id

    @pytest.mark.anyio
    async def test_target_without_active_instance_records_none(self) -> None:
        source, instance, backup = make_chain()
        counterpart, _ = make_counterpart(
            status=DeploymentState.PENDING, with_active_instance=False
        )
        uow = make_uow(
            backups=[backup],
            instances=[instance],
            deployments=[source, counterpart],
        )

        restore, _ = await create_restore(
            backup_id=backup.id,
            uow=uow,
            target_deployment_id=counterpart.id,
        )

        assert restore.target_instance_id is None

    @pytest.mark.anyio
    async def test_missing_target_deployment_raises_deployment_not_found(self) -> None:
        source, instance, backup = make_chain()
        uow = make_uow(backups=[backup], instances=[instance], deployments=[source])

        with pytest.raises(DeploymentNotFoundError):
            await create_restore(
                backup_id=backup.id,
                uow=uow,
                target_deployment_id=uuid4(),
            )

    @pytest.mark.anyio
    async def test_internal_target_is_rejected(self) -> None:
        source, instance, backup = make_chain()
        counterpart, _ = make_counterpart(status=DeploymentState.PENDING, internal=True)
        uow = make_uow(
            backups=[backup],
            instances=[instance],
            deployments=[source, counterpart],
        )

        with pytest.raises(InternalDeploymentError):
            await create_restore(
                backup_id=backup.id,
                uow=uow,
                target_deployment_id=counterpart.id,
            )

    @pytest.mark.anyio
    async def test_internal_source_does_not_block_a_cross_target_restore(self) -> None:
        """The source is never resolved, so its flags cannot veto the clone."""
        source, instance, backup = make_chain(deployment_internal=True)
        counterpart, _ = make_counterpart(status=DeploymentState.PENDING)
        uow = make_uow(
            backups=[backup],
            instances=[instance],
            deployments=[source, counterpart],
        )

        restore, deployment_id = await create_restore(
            backup_id=backup.id,
            uow=uow,
            target_deployment_id=counterpart.id,
        )

        assert deployment_id == counterpart.id
        assert restore.status == RestoreStatus.PENDING

    @pytest.mark.anyio
    async def test_in_flight_restore_on_the_target_blocks_a_second_restore(
        self,
    ) -> None:
        """What blocks is the in-flight ``Restore`` row, not the target's state.

        The counterpart is ``RESTORING`` *and* has a live restore aimed at it;
        the second one is refused and the refusal names the first.
        """
        source, instance, backup = make_chain()
        counterpart, _ = make_counterpart(status=DeploymentState.RESTORING)
        existing_restore = Restore(
            name="existing-restore",
            status=RestoreStatus.IN_PROGRESS,
            target_namespace=f"styrmin-{counterpart.id}",
            backup_id=uuid4(),
        )
        uow = make_uow(
            backups=[backup],
            restores=[existing_restore],
            instances=[instance],
            deployments=[source, counterpart],
        )

        with pytest.raises(RestoreAlreadyInProgressError) as excinfo:
            await create_restore(
                backup_id=backup.id,
                uow=uow,
                target_deployment_id=counterpart.id,
            )

        assert excinfo.value.existing_restore_id == str(existing_restore.id)
        # Nothing was written for the refused request.
        assert [r.id for r in uow.restores.models] == [existing_restore.id]

    @pytest.mark.anyio
    async def test_restoring_counterpart_without_a_restore_row_is_allowed(self) -> None:
        """The clone path: a counterpart parked in RESTORING awaits its data.

        ``deploy_application(skip_initial_reconcile=True)`` creates every
        counterpart in ``RESTORING`` so nothing reconciles it before its data
        arrives (research D5). That state is the *precondition* of the first
        cross-target restore, not a conflict with it — gating on the state
        instead of on a live ``Restore`` row failed every clone.
        """
        source, instance, backup = make_chain()
        counterpart, counterpart_instance = make_counterpart(
            status=DeploymentState.RESTORING
        )
        assert counterpart_instance is not None
        uow = make_uow(
            backups=[backup],
            instances=[instance],
            deployments=[source, counterpart],
        )

        restore, deployment_id = await create_restore(
            backup_id=backup.id,
            uow=uow,
            target_deployment_id=counterpart.id,
        )

        assert deployment_id == counterpart.id
        assert restore.status == RestoreStatus.PENDING
        assert restore.target_instance_id == counterpart_instance.id
        stored_counterpart = await uow.deployments.find(counterpart.id)
        assert stored_counterpart is not None
        assert stored_counterpart.status == DeploymentState.RESTORING

    @pytest.mark.anyio
    async def test_a_third_restore_into_the_same_counterpart_is_refused(self) -> None:
        """The guard still serialises: the row the first call wrote blocks the next.

        Same sequence as a clone, run twice — proof the permissive first call
        does not leave the counterpart unguarded afterwards.
        """
        source, instance, backup = make_chain()
        second_backup = Backup(
            name="second-backup",
            status=BackupStatus.COMPLETED,
            instance_id=instance.id,
        )
        counterpart, _ = make_counterpart(status=DeploymentState.RESTORING)
        uow = make_uow(
            backups=[backup, second_backup],
            instances=[instance],
            deployments=[source, counterpart],
        )

        first, _ = await create_restore(
            backup_id=backup.id,
            uow=uow,
            target_deployment_id=counterpart.id,
        )

        with pytest.raises(RestoreAlreadyInProgressError) as excinfo:
            await create_restore(
                backup_id=second_backup.id,
                uow=uow,
                target_deployment_id=counterpart.id,
            )

        assert excinfo.value.existing_restore_id == str(first.id)

    @pytest.mark.anyio
    async def test_restoring_source_does_not_block_a_cross_target_restore(self) -> None:
        """A source mid-restore of its own is irrelevant to the counterpart."""
        source, instance, backup = make_chain(
            deployment_status=DeploymentState.RESTORING
        )
        counterpart, _ = make_counterpart(status=DeploymentState.PENDING)
        uow = make_uow(
            backups=[backup],
            instances=[instance],
            deployments=[source, counterpart],
        )

        restore, deployment_id = await create_restore(
            backup_id=backup.id,
            uow=uow,
            target_deployment_id=counterpart.id,
        )

        assert deployment_id == counterpart.id
        assert restore.status == RestoreStatus.PENDING

    @pytest.mark.anyio
    async def test_source_deployment_row_may_be_gone(self) -> None:
        """Cross-target never walks backup -> instance -> deployment."""
        _, instance, backup = make_chain()
        counterpart, _ = make_counterpart(status=DeploymentState.PENDING)
        uow = make_uow(
            backups=[backup],
            instances=[instance],
            deployments=[counterpart],
        )

        restore, deployment_id = await create_restore(
            backup_id=backup.id,
            uow=uow,
            target_deployment_id=counterpart.id,
        )

        assert deployment_id == counterpart.id
        assert restore.backup_id == backup.id
