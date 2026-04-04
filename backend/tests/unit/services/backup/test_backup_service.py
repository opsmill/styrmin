"""Unit tests for BackupService."""

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
    DEFAULT_BACKUP_TIMEOUT,
    create_backup,
    delete_backup,
    get_backup,
    get_backups,
    get_strategy,
    update_backup_component_status,
    update_backup_status,
)
from styrmin_backend.services.backup.strategies.action import ActionBackupStrategy
from styrmin_backend.services.backup.strategies.disk import DiskSnapshotStrategy
from styrmin_backend.services.backup.strategies.mariadb import MariadbBackupStrategy
from styrmin_backend.services.backup.strategies.mongodb import MongodbBackupStrategy
from styrmin_backend.services.backup.strategies.neo4j import Neo4jBackupStrategy
from styrmin_backend.services.backup.strategies.postgres import PostgresBackupStrategy
from styrmin_backend.services.exceptions import (
    BackupAlreadyInProgressError,
    BackupNotFoundError,
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


class TestGetStrategy:
    def test_disk_strategy(self) -> None:
        strategy = get_strategy("disk")
        assert isinstance(strategy, DiskSnapshotStrategy)

    def test_postgres_strategy(self) -> None:
        strategy = get_strategy("postgres")
        assert isinstance(strategy, PostgresBackupStrategy)

    def test_neo4j_strategy(self) -> None:
        strategy = get_strategy("neo4j")
        assert isinstance(strategy, Neo4jBackupStrategy)

    def test_mariadb_strategy(self) -> None:
        strategy = get_strategy("mariadb")
        assert isinstance(strategy, MariadbBackupStrategy)

    def test_mongodb_strategy(self) -> None:
        strategy = get_strategy("mongodb")
        assert isinstance(strategy, MongodbBackupStrategy)

    def test_action_strategy(self) -> None:
        strategy = get_strategy("action")
        assert isinstance(strategy, ActionBackupStrategy)

    def test_unknown_strategy_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown backup kind"):
            get_strategy("unknown")


class TestCreateBackup:
    async def test_create_backup_success(self) -> None:
        instance_id = uuid4()
        uow = make_uow()

        backup = await create_backup(
            instance_id=instance_id,
            uow=uow,
            name="test-backup",
        )

        assert backup.name == "test-backup"
        assert backup.status == BackupStatus.PENDING
        assert backup.instance_id == instance_id
        assert uow.committed is True

    async def test_create_backup_generates_name(self) -> None:
        instance_id = uuid4()
        uow = make_uow()

        backup = await create_backup(
            instance_id=instance_id,
            uow=uow,
        )

        assert backup.name == f"styrmin-{backup.id}"
        assert backup.status == BackupStatus.PENDING

    async def test_create_backup_concurrent_prevention(self) -> None:
        instance_id = uuid4()
        existing = Backup(
            name="existing-backup",
            status=BackupStatus.IN_PROGRESS,
            instance_id=instance_id,
        )
        uow = make_uow(backups=[existing])

        with pytest.raises(BackupAlreadyInProgressError):
            await create_backup(
                instance_id=instance_id,
                uow=uow,
                name="new-backup",
            )

    async def test_create_backup_with_component_configs(self) -> None:
        instance_id = uuid4()
        uow = make_uow()

        backup = await create_backup(
            instance_id=instance_id,
            uow=uow,
            name="test-backup",
            target_namespace="test-ns",
            component_configs={
                "web": {"kind": "disk", "volume": "data"},
                "db": {"kind": "postgres"},
            },
        )

        assert backup.component_statuses is not None
        assert "web" in backup.component_statuses
        assert "db" in backup.component_statuses
        assert backup.component_statuses["web"]["status"] == "pending"
        assert backup.component_statuses["db"]["status"] == "pending"
        # Original config fields must be preserved for the workflow layer
        assert backup.component_statuses["web"]["kind"] == "disk"
        assert backup.component_statuses["web"]["volume"] == "data"
        assert backup.component_statuses["db"]["kind"] == "postgres"

    async def test_create_backup_pending_does_not_block(self) -> None:
        """A PENDING backup should not block creation of a new backup."""
        instance_id = uuid4()
        existing = Backup(
            name="pending-backup",
            status=BackupStatus.PENDING,
            instance_id=instance_id,
        )
        uow = make_uow(backups=[existing])

        backup = await create_backup(
            instance_id=instance_id,
            uow=uow,
            name="new-backup",
        )

        assert backup.name == "new-backup"


class TestGetBackup:
    async def test_get_backup_found(self) -> None:
        instance_id = uuid4()
        existing = Backup(
            name="test-backup",
            status=BackupStatus.COMPLETED,
            instance_id=instance_id,
        )
        uow = make_uow(backups=[existing])

        result = await get_backup(backup_id=existing.id, uow=uow)
        assert result.id == existing.id

    async def test_get_backup_not_found(self) -> None:
        uow = make_uow()

        with pytest.raises(BackupNotFoundError):
            await get_backup(backup_id=uuid4(), uow=uow)


class TestGetBackups:
    async def test_get_backups_by_instance(self) -> None:
        instance_id = uuid4()
        other_instance_id = uuid4()
        b1 = Backup(
            name="b1",
            status=BackupStatus.COMPLETED,
            instance_id=instance_id,
        )
        b2 = Backup(
            name="b2",
            status=BackupStatus.PENDING,
            instance_id=instance_id,
        )
        b3 = Backup(
            name="b3",
            status=BackupStatus.COMPLETED,
            instance_id=other_instance_id,
        )
        uow = make_uow(backups=[b1, b2, b3])

        results = await get_backups(instance_id=instance_id, uow=uow)
        assert len(results) == 2

    async def test_get_backups_with_status_filter(self) -> None:
        instance_id = uuid4()
        b1 = Backup(
            name="b1",
            status=BackupStatus.COMPLETED,
            instance_id=instance_id,
        )
        b2 = Backup(
            name="b2",
            status=BackupStatus.PENDING,
            instance_id=instance_id,
        )
        uow = make_uow(backups=[b1, b2])

        results = await get_backups(
            instance_id=instance_id, uow=uow, status=BackupStatus.COMPLETED
        )
        assert len(results) == 1
        assert results[0].name == "b1"


class TestDeleteBackup:
    async def test_delete_backup_success(self) -> None:
        instance_id = uuid4()
        backup = Backup(
            name="to-delete",
            status=BackupStatus.COMPLETED,
            instance_id=instance_id,
        )
        uow = make_uow(backups=[backup])

        await delete_backup(backup_id=backup.id, uow=uow)

        assert uow.committed is True
        assert len(uow.backups.models) == 0

    async def test_delete_backup_not_found(self) -> None:
        uow = make_uow()

        with pytest.raises(BackupNotFoundError):
            await delete_backup(backup_id=uuid4(), uow=uow)

    async def test_delete_backup_cascades_restores(self) -> None:
        instance_id = uuid4()
        backup = Backup(
            name="backup-with-restores",
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


class TestUpdateBackupStatus:
    async def test_update_to_in_progress(self) -> None:
        instance_id = uuid4()
        backup = Backup(
            name="test-backup",
            status=BackupStatus.PENDING,
            instance_id=instance_id,
        )
        uow = make_uow(backups=[backup])

        result = await update_backup_status(
            backup_id=backup.id,
            status=BackupStatus.IN_PROGRESS,
            uow=uow,
        )

        assert result.status == BackupStatus.IN_PROGRESS
        assert result.started_at is not None

    async def test_update_to_completed(self) -> None:
        instance_id = uuid4()
        backup = Backup(
            name="test-backup",
            status=BackupStatus.IN_PROGRESS,
            instance_id=instance_id,
        )
        uow = make_uow(backups=[backup])

        result = await update_backup_status(
            backup_id=backup.id,
            status=BackupStatus.COMPLETED,
            uow=uow,
            size_bytes=1024,
        )

        assert result.status == BackupStatus.COMPLETED
        assert result.completed_at is not None
        assert result.size_bytes == 1024

    async def test_update_to_failed(self) -> None:
        instance_id = uuid4()
        backup = Backup(
            name="test-backup",
            status=BackupStatus.IN_PROGRESS,
            instance_id=instance_id,
        )
        uow = make_uow(backups=[backup])

        result = await update_backup_status(
            backup_id=backup.id,
            status=BackupStatus.FAILED,
            uow=uow,
            error_message="Velero timeout",
        )

        assert result.status == BackupStatus.FAILED
        assert result.completed_at is not None
        assert result.error_message == "Velero timeout"

    async def test_update_not_found(self) -> None:
        uow = make_uow()

        with pytest.raises(BackupNotFoundError):
            await update_backup_status(
                backup_id=uuid4(),
                status=BackupStatus.COMPLETED,
                uow=uow,
            )

    async def test_update_component_statuses(self) -> None:
        instance_id = uuid4()
        backup = Backup(
            name="test-backup",
            status=BackupStatus.IN_PROGRESS,
            instance_id=instance_id,
        )
        uow = make_uow(backups=[backup])

        component_statuses = {
            "web": {"status": "completed"},
            "db": {"status": "completed", "size_bytes": 512},
        }

        result = await update_backup_status(
            backup_id=backup.id,
            status=BackupStatus.COMPLETED,
            uow=uow,
            component_statuses=component_statuses,
        )

        assert result.component_statuses == component_statuses


class TestCreateBackupTimeout:
    async def test_default_timeout_stored_in_metadata(self) -> None:
        instance_id = uuid4()
        uow = make_uow()

        backup = await create_backup(
            instance_id=instance_id,
            uow=uow,
            name="test-backup",
        )

        assert backup.metadata_ is not None
        assert backup.metadata_["timeout"] == DEFAULT_BACKUP_TIMEOUT

    async def test_custom_timeout_stored_in_metadata(self) -> None:
        instance_id = uuid4()
        uow = make_uow()

        backup = await create_backup(
            instance_id=instance_id,
            uow=uow,
            name="test-backup",
            timeout=1800,
        )

        assert backup.metadata_ is not None
        assert backup.metadata_["timeout"] == 1800


class TestUpdateBackupComponentStatus:
    async def test_update_single_component(self) -> None:
        instance_id = uuid4()
        backup = Backup(
            name="test-backup",
            status=BackupStatus.IN_PROGRESS,
            instance_id=instance_id,
            component_statuses={
                "web": {"status": "pending"},
                "db": {"status": "pending"},
            },
        )
        uow = make_uow(backups=[backup])

        result = await update_backup_component_status(
            backup_id=backup.id,
            component_name="web",
            component_status="completed",
            uow=uow,
        )

        assert result.component_statuses["web"]["status"] == "completed"  # type: ignore[index]
        assert result.component_statuses["db"]["status"] == "pending"  # type: ignore[index]
        # Not all completed yet, should still be IN_PROGRESS
        assert result.status == BackupStatus.IN_PROGRESS

    async def test_all_components_completed(self) -> None:
        instance_id = uuid4()
        backup = Backup(
            name="test-backup",
            status=BackupStatus.IN_PROGRESS,
            instance_id=instance_id,
            component_statuses={
                "web": {"status": "completed"},
                "db": {"status": "pending"},
            },
        )
        uow = make_uow(backups=[backup])

        result = await update_backup_component_status(
            backup_id=backup.id,
            component_name="db",
            component_status="completed",
            uow=uow,
        )

        assert result.status == BackupStatus.COMPLETED
        assert result.completed_at is not None

    async def test_component_failure_marks_backup_failed(self) -> None:
        instance_id = uuid4()
        backup = Backup(
            name="test-backup",
            status=BackupStatus.IN_PROGRESS,
            instance_id=instance_id,
            component_statuses={
                "web": {"status": "completed"},
                "db": {"status": "pending"},
            },
        )
        uow = make_uow(backups=[backup])

        result = await update_backup_component_status(
            backup_id=backup.id,
            component_name="db",
            component_status="failed",
            uow=uow,
            error_message="Connection refused",
        )

        assert result.status == BackupStatus.FAILED
        assert result.completed_at is not None
        assert result.component_statuses["db"]["error"] == "Connection refused"  # type: ignore[index]
        assert result.error_message is not None
        assert "db" in result.error_message

    async def test_component_status_not_found(self) -> None:
        uow = make_uow()

        with pytest.raises(BackupNotFoundError):
            await update_backup_component_status(
                backup_id=uuid4(),
                component_name="web",
                component_status="completed",
                uow=uow,
            )
