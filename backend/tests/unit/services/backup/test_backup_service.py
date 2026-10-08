"""Unit tests for BackupService."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from styrmin_backend.db.models import (
    ApplicationInstance,
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
    AmbiguousIdentifierError,
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
    instances: list[ApplicationInstance] | None = None,
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
    @pytest.mark.anyio
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

    @pytest.mark.anyio
    async def test_create_backup_generates_name(self) -> None:
        instance_id = uuid4()
        uow = make_uow()

        backup = await create_backup(
            instance_id=instance_id,
            uow=uow,
        )

        assert backup.name == f"styrmin-{backup.id}"
        assert backup.status == BackupStatus.PENDING

    @pytest.mark.anyio
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

    @pytest.mark.anyio
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

    @pytest.mark.anyio
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
    @pytest.mark.anyio
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

    @pytest.mark.anyio
    async def test_get_backup_not_found(self) -> None:
        uow = make_uow()

        with pytest.raises(BackupNotFoundError):
            await get_backup(backup_id=uuid4(), uow=uow)


class TestGetBackups:
    @pytest.mark.anyio
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

        results = await get_backups(uow, instance_id=instance_id)
        assert len(results) == 2

    @pytest.mark.anyio
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
            uow, instance_id=instance_id, status=BackupStatus.COMPLETED
        )
        assert len(results) == 1
        assert results[0].name == "b1"

    @staticmethod
    def _deployment_history() -> tuple[FakeUnitOfWork, ApplicationInstance]:
        """One deployment with an old and a new instance, plus another deployment."""
        deployment_id = uuid4()
        old = ApplicationInstance(
            application_version="1.0.0", deployment_id=deployment_id
        )
        new = ApplicationInstance(
            application_version="2.0.0", deployment_id=deployment_id
        )
        other = ApplicationInstance(application_version="1.0.0", deployment_id=uuid4())
        base = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
        backups = [
            Backup(
                name="before-upgrade",
                status=BackupStatus.COMPLETED,
                instance_id=old.id,
                created_on=base,
            ),
            Backup(
                name="after-upgrade",
                status=BackupStatus.FAILED,
                instance_id=new.id,
                created_on=base + timedelta(minutes=2),
            ),
            Backup(
                name="other-deployment",
                status=BackupStatus.COMPLETED,
                instance_id=other.id,
                created_on=base + timedelta(minutes=1),
            ),
        ]
        uow = make_uow(backups=backups, instances=[old, new, other])
        return uow, old

    @pytest.mark.anyio
    async def test_get_backups_by_deployment_returns_every_instance(self) -> None:
        uow, old = self._deployment_history()

        results = await get_backups(uow, deployment_id=old.deployment_id)

        assert [b.name for b in results] == ["after-upgrade", "before-upgrade"]

    @pytest.mark.anyio
    async def test_get_backups_by_deployment_with_status_filter(self) -> None:
        uow, old = self._deployment_history()

        results = await get_backups(
            uow, deployment_id=old.deployment_id, status=BackupStatus.COMPLETED
        )

        assert [b.name for b in results] == ["before-upgrade"]

    @pytest.mark.anyio
    async def test_get_backups_by_instance_returns_only_that_instance(self) -> None:
        uow, old = self._deployment_history()

        results = await get_backups(uow, instance_id=old.id)

        assert [b.name for b in results] == ["before-upgrade"]

    @pytest.mark.anyio
    async def test_get_backups_with_both_identifiers_raises(self) -> None:
        uow, old = self._deployment_history()

        with pytest.raises(AmbiguousIdentifierError, match="not both") as exc_info:
            await get_backups(uow, deployment_id=old.deployment_id, instance_id=old.id)

        assert exc_info.value.error_code == "VALIDATION_ERROR"

    @pytest.mark.anyio
    async def test_get_backups_with_no_identifier_raises(self) -> None:
        uow, _ = self._deployment_history()

        with pytest.raises(AmbiguousIdentifierError, match="is required") as exc_info:
            await get_backups(uow)

        assert exc_info.value.error_code == "VALIDATION_ERROR"


class TestDeleteBackup:
    @pytest.mark.anyio
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

    @pytest.mark.anyio
    async def test_delete_backup_not_found(self) -> None:
        uow = make_uow()

        with pytest.raises(BackupNotFoundError):
            await delete_backup(backup_id=uuid4(), uow=uow)

    @pytest.mark.anyio
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
    @pytest.mark.anyio
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

    @pytest.mark.anyio
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

    @pytest.mark.anyio
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

    @pytest.mark.anyio
    async def test_update_not_found(self) -> None:
        uow = make_uow()

        with pytest.raises(BackupNotFoundError):
            await update_backup_status(
                backup_id=uuid4(),
                status=BackupStatus.COMPLETED,
                uow=uow,
            )

    @pytest.mark.anyio
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

    @pytest.mark.anyio
    async def test_metadata_updates_merge_and_preserve_existing_keys(self) -> None:
        """``metadata_updates`` merges — it must not overwrite the whole dict.

        ``create_backup`` stores the Velero poll ``timeout`` in ``metadata_``,
        and the backup workflow later writes the resolved retention through
        this parameter. A bare assignment (``backup.metadata_ =
        metadata_updates``) would drop ``timeout``, so the workflow's own
        ``metadata_.get("timeout", 3600)`` read would silently fall back to the
        default for every custom-timeout backup (016 / FR-006).
        """
        backup = Backup(
            name="test-backup",
            status=BackupStatus.PENDING,
            instance_id=uuid4(),
            metadata_={"timeout": 1800},
        )
        uow = make_uow(backups=[backup])

        result = await update_backup_status(
            backup_id=backup.id,
            status=BackupStatus.IN_PROGRESS,
            uow=uow,
            metadata_updates={"ttl": "2160h", "ttl_source": "environment"},
        )

        assert result.metadata_ == {
            "timeout": 1800,
            "ttl": "2160h",
            "ttl_source": "environment",
        }

    @pytest.mark.anyio
    async def test_metadata_updates_reassign_the_attribute_not_mutate_it(
        self,
    ) -> None:
        """The merge must produce a NEW dict, not mutate the stored one.

        ``metadata`` is a plain JSON column with no ``MutableDict`` wrapper, so
        SQLAlchemy only marks it dirty on attribute *assignment*. An in-place
        ``backup.metadata_.update(...)`` would pass an equality assertion while
        never reaching the database — this asserts the object identity changed
        so that failure mode cannot hide (016 critique E4 / M2).
        """
        original: dict = {"timeout": 1800}
        backup = Backup(
            name="test-backup",
            status=BackupStatus.IN_PROGRESS,
            instance_id=uuid4(),
            metadata_=original,
        )
        uow = make_uow(backups=[backup])

        result = await update_backup_status(
            backup_id=backup.id,
            status=BackupStatus.COMPLETED,
            uow=uow,
            metadata_updates={"expires_at": "2026-08-03T00:00:00+00:00"},
        )

        assert result.metadata_ is not original
        assert original == {"timeout": 1800}, (
            "the pre-existing metadata dict must not be mutated in place"
        )
        assert result.metadata_["expires_at"] == "2026-08-03T00:00:00+00:00"
        assert result.metadata_["timeout"] == 1800

    @pytest.mark.anyio
    async def test_metadata_updates_on_a_row_with_no_metadata(self) -> None:
        """``metadata_`` is None on pre-existing rows; the merge must cope."""
        backup = Backup(
            name="test-backup",
            status=BackupStatus.IN_PROGRESS,
            instance_id=uuid4(),
        )
        uow = make_uow(backups=[backup])

        result = await update_backup_status(
            backup_id=backup.id,
            status=BackupStatus.COMPLETED,
            uow=uow,
            metadata_updates={"ttl": "720h", "ttl_source": "default"},
        )

        assert result.metadata_ == {"ttl": "720h", "ttl_source": "default"}


class TestCreateBackupTimeout:
    @pytest.mark.anyio
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

    @pytest.mark.anyio
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
    @pytest.mark.anyio
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

    @pytest.mark.anyio
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

    @pytest.mark.anyio
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

    @pytest.mark.anyio
    async def test_component_status_not_found(self) -> None:
        uow = make_uow()

        with pytest.raises(BackupNotFoundError):
            await update_backup_component_status(
                backup_id=uuid4(),
                component_name="web",
                component_status="completed",
                uow=uow,
            )
