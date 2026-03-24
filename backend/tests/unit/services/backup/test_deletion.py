"""Unit tests for backup deletion logic."""

from __future__ import annotations

from uuid import uuid4

import pytest

from styrmin_backend.db.models import (
    Backup,
    BackupStatus,
    Restore,
    RestoreStatus,
)
from styrmin_backend.services.backup.service import delete_backup
from styrmin_backend.services.exceptions import BackupNotFoundError
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


class TestDeleteBackup:
    @pytest.mark.anyio
    async def test_delete_removes_backup_record(self) -> None:
        instance_id = uuid4()
        backup = Backup(
            name="to-delete",
            status=BackupStatus.COMPLETED,
            instance_id=instance_id,
        )
        uow = make_uow(backups=[backup])

        await delete_backup(backup_id=backup.id, uow=uow)

        assert len(uow.backups.models) == 0
        assert uow.committed is True

    @pytest.mark.anyio
    async def test_delete_not_found_raises(self) -> None:
        uow = make_uow()

        with pytest.raises(BackupNotFoundError):
            await delete_backup(backup_id=uuid4(), uow=uow)

    @pytest.mark.anyio
    async def test_delete_cascades_single_restore(self) -> None:
        instance_id = uuid4()
        backup = Backup(
            name="backup-with-restore",
            status=BackupStatus.COMPLETED,
            instance_id=instance_id,
        )
        restore = Restore(
            name="restore-1",
            status=RestoreStatus.COMPLETED,
            backup_id=backup.id,
            target_namespace="test-ns",
        )
        uow = make_uow(backups=[backup], restores=[restore])

        await delete_backup(backup_id=backup.id, uow=uow)

        assert len(uow.backups.models) == 0
        assert len(uow.restores.models) == 0

    @pytest.mark.anyio
    async def test_delete_cascades_multiple_restores(self) -> None:
        instance_id = uuid4()
        backup = Backup(
            name="backup-with-restores",
            status=BackupStatus.COMPLETED,
            instance_id=instance_id,
        )
        r1 = Restore(
            name="restore-1",
            status=RestoreStatus.COMPLETED,
            backup_id=backup.id,
            target_namespace="ns-1",
        )
        r2 = Restore(
            name="restore-2",
            status=RestoreStatus.FAILED,
            backup_id=backup.id,
            target_namespace="ns-2",
        )
        uow = make_uow(backups=[backup], restores=[r1, r2])

        await delete_backup(backup_id=backup.id, uow=uow)

        assert len(uow.backups.models) == 0
        assert len(uow.restores.models) == 0

    @pytest.mark.anyio
    async def test_delete_does_not_affect_other_backup_restores(self) -> None:
        """Deleting one backup should not affect restores from other backups."""
        instance_id = uuid4()
        backup_to_delete = Backup(
            name="backup-to-delete",
            status=BackupStatus.COMPLETED,
            instance_id=instance_id,
        )
        other_backup = Backup(
            name="other-backup",
            status=BackupStatus.COMPLETED,
            instance_id=instance_id,
        )
        restore_to_delete = Restore(
            name="restore-to-delete",
            status=RestoreStatus.COMPLETED,
            backup_id=backup_to_delete.id,
            target_namespace="ns-1",
        )
        other_restore = Restore(
            name="other-restore",
            status=RestoreStatus.COMPLETED,
            backup_id=other_backup.id,
            target_namespace="ns-2",
        )
        uow = make_uow(
            backups=[backup_to_delete, other_backup],
            restores=[restore_to_delete, other_restore],
        )

        await delete_backup(backup_id=backup_to_delete.id, uow=uow)

        assert len(uow.backups.models) == 1
        assert uow.backups.models[0].id == other_backup.id
        assert len(uow.restores.models) == 1
        assert uow.restores.models[0].id == other_restore.id

    @pytest.mark.anyio
    async def test_delete_pending_backup(self) -> None:
        """Can delete a backup that's still pending."""
        instance_id = uuid4()
        backup = Backup(
            name="pending-backup",
            status=BackupStatus.PENDING,
            instance_id=instance_id,
        )
        uow = make_uow(backups=[backup])

        await delete_backup(backup_id=backup.id, uow=uow)

        assert len(uow.backups.models) == 0

    @pytest.mark.anyio
    async def test_delete_failed_backup(self) -> None:
        """Can delete a backup that failed."""
        instance_id = uuid4()
        backup = Backup(
            name="failed-backup",
            status=BackupStatus.FAILED,
            instance_id=instance_id,
            error_message="Something went wrong",
        )
        uow = make_uow(backups=[backup])

        await delete_backup(backup_id=backup.id, uow=uow)

        assert len(uow.backups.models) == 0
