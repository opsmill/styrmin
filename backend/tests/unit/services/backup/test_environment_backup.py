"""Unit tests for environment backup service functions.

Note: Tests that require uow.session.exec() (e.g., status aggregation, delete
with in-progress checks) are covered by integration tests since the FakeSession
does not support SQLModel select() queries.
"""

from __future__ import annotations

from enum import Enum
from uuid import uuid4

import pytest

from styrmin_backend.db.models import (
    ApplicationInstance,
    BackupStatus,
    Environment,
    EnvironmentBackup,
    EnvironmentBackupStatus,
)
from styrmin_backend.services.backup.environment import (
    _aggregate_parent_status,
    create_environment_backup,
    get_environment_backup,
    get_environment_backups,
)
from styrmin_backend.services.exceptions import (
    EnvironmentBackupNotFoundError,
    EnvironmentBackupOperationInProgressError,
    EnvironmentBackupValidationError,
    EnvironmentNotFoundError,
)
from tests.unit.services.fakes import (
    FakeActionRepository,
    FakeApplicationInstanceRepository,
    FakeApplicationRepository,
    FakeBackupRepository,
    FakeClusterRepository,
    FakeEnvironmentBackupRepository,
    FakeEnvironmentRepository,
    FakeEnvironmentRestoreRepository,
    FakeHelmChartRepository,
    FakeHelmRepositoryRepository,
    FakeRestoreRepository,
    FakeTaskRepository,
    FakeUnitOfWork,
)


def make_uow(
    environments: list[Environment] | None = None,
    instances: list[ApplicationInstance] | None = None,
    environment_backups: list[EnvironmentBackup] | None = None,
) -> FakeUnitOfWork:
    return FakeUnitOfWork(
        clusters=FakeClusterRepository(),
        environments=FakeEnvironmentRepository(environments or []),
        helm_repositories=FakeHelmRepositoryRepository(),
        helm_charts=FakeHelmChartRepository(),
        application_driver_versions=FakeApplicationRepository(),
        instances=FakeApplicationInstanceRepository(instances or []),
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        backups=FakeBackupRepository(),
        restores=FakeRestoreRepository(),
        environment_backups=FakeEnvironmentBackupRepository(environment_backups or []),
        environment_restores=FakeEnvironmentRestoreRepository(),
    )


class TestCreateEnvironmentBackup:
    async def test_environment_not_found_raises(self) -> None:
        uow = make_uow()
        with pytest.raises(EnvironmentNotFoundError):
            await create_environment_backup(uuid4(), uow)

    async def test_no_bsl_raises_validation_error(self) -> None:
        env_id = uuid4()
        env = Environment(
            id=env_id,
            name="test-env",
            cluster_id=uuid4(),
            backup_storage_location_id=None,
        )
        uow = make_uow(environments=[env])
        with pytest.raises(
            EnvironmentBackupValidationError, match="backup storage location"
        ):
            await create_environment_backup(env_id, uow)

    async def test_rejects_when_env_backup_already_in_progress(self) -> None:
        env_id = uuid4()
        env = Environment(
            id=env_id,
            name="test-env",
            cluster_id=uuid4(),
            backup_storage_location_id=uuid4(),
        )
        existing_backup = EnvironmentBackup(
            id=uuid4(),
            name="existing",
            status=EnvironmentBackupStatus.IN_PROGRESS,
            environment_id=env_id,
        )
        uow = make_uow(environments=[env], environment_backups=[existing_backup])
        with pytest.raises(
            EnvironmentBackupOperationInProgressError,
            match="already in progress",
        ):
            await create_environment_backup(env_id, uow)

    async def test_rejects_when_env_backup_pending(self) -> None:
        env_id = uuid4()
        env = Environment(
            id=env_id,
            name="test-env",
            cluster_id=uuid4(),
            backup_storage_location_id=uuid4(),
        )
        existing_backup = EnvironmentBackup(
            id=uuid4(),
            name="existing",
            status=EnvironmentBackupStatus.PENDING,
            environment_id=env_id,
        )
        uow = make_uow(environments=[env], environment_backups=[existing_backup])
        with pytest.raises(EnvironmentBackupOperationInProgressError):
            await create_environment_backup(env_id, uow)


class TestGetEnvironmentBackup:
    async def test_not_found_raises(self) -> None:
        uow = make_uow()
        with pytest.raises(EnvironmentBackupNotFoundError):
            await get_environment_backup(uuid4(), uow)

    async def test_returns_existing(self) -> None:
        eb_id = uuid4()
        eb = EnvironmentBackup(
            id=eb_id,
            name="test-backup",
            status=EnvironmentBackupStatus.COMPLETED,
            environment_id=uuid4(),
        )
        uow = make_uow(environment_backups=[eb])
        result = await get_environment_backup(eb_id, uow)
        assert result.id == eb_id
        assert result.name == "test-backup"


class TestGetEnvironmentBackups:
    async def test_returns_backups_for_environment(self) -> None:
        env_id = uuid4()
        eb1 = EnvironmentBackup(
            id=uuid4(),
            name="backup-1",
            status=EnvironmentBackupStatus.COMPLETED,
            environment_id=env_id,
        )
        eb2 = EnvironmentBackup(
            id=uuid4(),
            name="backup-2",
            status=EnvironmentBackupStatus.FAILED,
            environment_id=env_id,
        )
        other_env = EnvironmentBackup(
            id=uuid4(),
            name="other",
            status=EnvironmentBackupStatus.COMPLETED,
            environment_id=uuid4(),
        )
        uow = make_uow(environment_backups=[eb1, eb2, other_env])
        result = await get_environment_backups(env_id, uow)
        assert len(result) == 2

    async def test_filters_by_status(self) -> None:
        env_id = uuid4()
        eb1 = EnvironmentBackup(
            id=uuid4(),
            name="backup-1",
            status=EnvironmentBackupStatus.COMPLETED,
            environment_id=env_id,
        )
        eb2 = EnvironmentBackup(
            id=uuid4(),
            name="backup-2",
            status=EnvironmentBackupStatus.FAILED,
            environment_id=env_id,
        )
        uow = make_uow(environment_backups=[eb1, eb2])
        result = await get_environment_backups(
            env_id, uow, status=EnvironmentBackupStatus.COMPLETED
        )
        assert len(result) == 1
        assert result[0].status == EnvironmentBackupStatus.COMPLETED


class TestAggregateParentStatus:
    """Test the shared status aggregation helper."""

    def _aggregate(self, statuses: list) -> Enum:
        return _aggregate_parent_status(
            constituent_statuses=statuses,
            completed_value=BackupStatus.COMPLETED,
            failed_value=BackupStatus.FAILED,
            pending_value=BackupStatus.PENDING,
            in_progress_value=BackupStatus.IN_PROGRESS,
            parent_completed=EnvironmentBackupStatus.COMPLETED,
            parent_failed=EnvironmentBackupStatus.FAILED,
            parent_pending=EnvironmentBackupStatus.PENDING,
            parent_in_progress=EnvironmentBackupStatus.IN_PROGRESS,
            parent_partially_failed=EnvironmentBackupStatus.PARTIALLY_FAILED,
        )

    def test_empty_statuses_returns_failed(self) -> None:
        assert self._aggregate([]) == EnvironmentBackupStatus.FAILED

    def test_all_completed(self) -> None:
        assert (
            self._aggregate([BackupStatus.COMPLETED, BackupStatus.COMPLETED])
            == EnvironmentBackupStatus.COMPLETED
        )

    def test_all_failed(self) -> None:
        assert (
            self._aggregate([BackupStatus.FAILED, BackupStatus.FAILED])
            == EnvironmentBackupStatus.FAILED
        )

    def test_all_pending(self) -> None:
        assert (
            self._aggregate([BackupStatus.PENDING, BackupStatus.PENDING])
            == EnvironmentBackupStatus.PENDING
        )

    def test_mixed_in_progress(self) -> None:
        assert (
            self._aggregate([BackupStatus.COMPLETED, BackupStatus.IN_PROGRESS])
            == EnvironmentBackupStatus.IN_PROGRESS
        )

    def test_mixed_pending_and_completed(self) -> None:
        assert (
            self._aggregate([BackupStatus.COMPLETED, BackupStatus.PENDING])
            == EnvironmentBackupStatus.IN_PROGRESS
        )

    def test_mixed_completed_and_failed(self) -> None:
        assert (
            self._aggregate([BackupStatus.COMPLETED, BackupStatus.FAILED])
            == EnvironmentBackupStatus.PARTIALLY_FAILED
        )
