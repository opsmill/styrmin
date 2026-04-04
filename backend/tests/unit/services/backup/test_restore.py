"""Unit tests for restore operations in BackupService."""

from __future__ import annotations

from uuid import uuid4

import pytest

from styrmin_backend.db.models import (
    Backup,
    BackupStatus,
    Restore,
    RestoreStatus,
)
from styrmin_backend.services.backup.service import (
    create_restore,
    get_restore,
    get_restores,
    update_restore_status,
)
from styrmin_backend.services.exceptions import (
    BackupNotFoundError,
    RestoreAlreadyInProgressError,
    RestoreNotFoundError,
)
from tests.unit.services.fakes import (
    FakeActionRepository,
    FakeApplicationInstanceRepository,
    FakeApplicationRepository,
    FakeBackupRepository,
    FakeClusterRepository,
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
) -> FakeUnitOfWork:
    return FakeUnitOfWork(
        clusters=FakeClusterRepository(),
        environments=FakeEnvironmentRepository(),
        helm_repositories=FakeHelmRepositoryRepository(),
        helm_charts=FakeHelmChartRepository(),
        application_driver_versions=FakeApplicationRepository(),
        instances=FakeApplicationInstanceRepository(),
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        backups=FakeBackupRepository(backups or []),
        restores=FakeRestoreRepository(restores or []),
    )


class TestCreateRestore:
    async def test_create_restore_success(self) -> None:
        instance_id = uuid4()
        backup = Backup(
            name="test-backup",
            status=BackupStatus.COMPLETED,
            instance_id=instance_id,
        )
        uow = make_uow(backups=[backup])

        restore = await create_restore(
            backup_id=backup.id,
            target_namespace="test-ns",
            uow=uow,
        )

        assert restore.status == RestoreStatus.PENDING
        assert restore.target_namespace == "test-ns"
        assert restore.backup_id == backup.id
        assert restore.name == f"styrmin-{restore.id}"
        assert uow.committed is True

    async def test_create_restore_custom_name(self) -> None:
        instance_id = uuid4()
        backup = Backup(
            name="test-backup",
            status=BackupStatus.COMPLETED,
            instance_id=instance_id,
        )
        uow = make_uow(backups=[backup])

        restore = await create_restore(
            backup_id=backup.id,
            target_namespace="test-ns",
            name="my-custom-restore",
            uow=uow,
        )

        assert restore.name == "my-custom-restore"

    async def test_create_restore_with_target_instance(self) -> None:
        instance_id = uuid4()
        target_instance_id = uuid4()
        backup = Backup(
            name="test-backup",
            status=BackupStatus.COMPLETED,
            instance_id=instance_id,
        )
        uow = make_uow(backups=[backup])

        restore = await create_restore(
            backup_id=backup.id,
            target_namespace="other-ns",
            target_instance_id=target_instance_id,
            uow=uow,
        )

        assert restore.target_instance_id == target_instance_id

    async def test_create_restore_backup_not_found(self) -> None:
        uow = make_uow()

        with pytest.raises(BackupNotFoundError):
            await create_restore(
                backup_id=uuid4(),
                target_namespace="test-ns",
                uow=uow,
            )

    async def test_create_restore_already_in_progress(self) -> None:
        instance_id = uuid4()
        backup = Backup(
            name="test-backup",
            status=BackupStatus.COMPLETED,
            instance_id=instance_id,
        )
        existing_restore = Restore(
            name="existing-restore",
            status=RestoreStatus.IN_PROGRESS,
            target_namespace="test-ns",
            backup_id=backup.id,
        )
        uow = make_uow(backups=[backup], restores=[existing_restore])

        with pytest.raises(RestoreAlreadyInProgressError):
            await create_restore(
                backup_id=backup.id,
                target_namespace="other-ns",
                uow=uow,
            )

    async def test_create_restore_completed_does_not_block(self) -> None:
        """A completed restore should not block creation of a new one."""
        instance_id = uuid4()
        backup = Backup(
            name="test-backup",
            status=BackupStatus.COMPLETED,
            instance_id=instance_id,
        )
        completed_restore = Restore(
            name="completed-restore",
            status=RestoreStatus.COMPLETED,
            target_namespace="test-ns",
            backup_id=backup.id,
        )
        uow = make_uow(backups=[backup], restores=[completed_restore])

        restore = await create_restore(
            backup_id=backup.id,
            target_namespace="other-ns",
            uow=uow,
        )

        assert restore.status == RestoreStatus.PENDING


class TestGetRestore:
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

    async def test_get_restore_not_found(self) -> None:
        uow = make_uow()

        with pytest.raises(RestoreNotFoundError):
            await get_restore(restore_id=uuid4(), uow=uow)


class TestGetRestores:
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

    async def test_update_not_found(self) -> None:
        uow = make_uow()

        with pytest.raises(RestoreNotFoundError):
            await update_restore_status(
                restore_id=uuid4(),
                status=RestoreStatus.COMPLETED,
                uow=uow,
            )

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
