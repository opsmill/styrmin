"""Unit tests for environment restore service functions.

Note: Full restore creation and status aggregation tests require a real
database session and are covered by integration tests.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from styrmin_backend.db.models import (
    EnvironmentBackup,
    EnvironmentBackupStatus,
    EnvironmentRestore,
    EnvironmentRestoreStatus,
)
from styrmin_backend.services.backup.environment import (
    create_environment_restore,
    get_environment_restore,
    get_environment_restores,
)
from styrmin_backend.services.exceptions import (
    EnvironmentBackupNotFoundError,
    EnvironmentBackupOperationInProgressError,
    EnvironmentBackupValidationError,
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
    environment_backups: list[EnvironmentBackup] | None = None,
    environment_restores: list[EnvironmentRestore] | None = None,
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
        backups=FakeBackupRepository(),
        restores=FakeRestoreRepository(),
        environment_backups=FakeEnvironmentBackupRepository(environment_backups or []),
        environment_restores=FakeEnvironmentRestoreRepository(
            environment_restores or []
        ),
    )


class TestCreateEnvironmentRestore:
    async def test_backup_not_found_raises(self) -> None:
        uow = make_uow()
        with pytest.raises(EnvironmentBackupNotFoundError):
            await create_environment_restore(uuid4(), uow)

    async def test_rejects_pending_backup(self) -> None:
        eb_id = uuid4()
        eb = EnvironmentBackup(
            id=eb_id,
            name="test-backup",
            status=EnvironmentBackupStatus.PENDING,
            environment_id=uuid4(),
        )
        uow = make_uow(environment_backups=[eb])
        with pytest.raises(EnvironmentBackupValidationError, match="Cannot restore"):
            await create_environment_restore(eb_id, uow)

    async def test_rejects_in_progress_backup(self) -> None:
        eb_id = uuid4()
        eb = EnvironmentBackup(
            id=eb_id,
            name="test-backup",
            status=EnvironmentBackupStatus.IN_PROGRESS,
            environment_id=uuid4(),
        )
        uow = make_uow(environment_backups=[eb])
        with pytest.raises(EnvironmentBackupValidationError):
            await create_environment_restore(eb_id, uow)

    async def test_rejects_failed_backup(self) -> None:
        eb_id = uuid4()
        eb = EnvironmentBackup(
            id=eb_id,
            name="test-backup",
            status=EnvironmentBackupStatus.FAILED,
            environment_id=uuid4(),
        )
        uow = make_uow(environment_backups=[eb])
        with pytest.raises(EnvironmentBackupValidationError):
            await create_environment_restore(eb_id, uow)

    async def test_rejects_when_restore_in_progress(self) -> None:
        eb_id = uuid4()
        eb = EnvironmentBackup(
            id=eb_id,
            name="test-backup",
            status=EnvironmentBackupStatus.COMPLETED,
            environment_id=uuid4(),
        )
        existing_restore = EnvironmentRestore(
            id=uuid4(),
            name="existing-restore",
            status=EnvironmentRestoreStatus.IN_PROGRESS,
            environment_backup_id=eb_id,
        )
        uow = make_uow(
            environment_backups=[eb], environment_restores=[existing_restore]
        )
        with pytest.raises(EnvironmentBackupOperationInProgressError):
            await create_environment_restore(eb_id, uow)

    async def test_rejects_when_restore_pending(self) -> None:
        eb_id = uuid4()
        eb = EnvironmentBackup(
            id=eb_id,
            name="test-backup",
            status=EnvironmentBackupStatus.COMPLETED,
            environment_id=uuid4(),
        )
        existing_restore = EnvironmentRestore(
            id=uuid4(),
            name="existing-restore",
            status=EnvironmentRestoreStatus.PENDING,
            environment_backup_id=eb_id,
        )
        uow = make_uow(
            environment_backups=[eb], environment_restores=[existing_restore]
        )
        with pytest.raises(EnvironmentBackupOperationInProgressError):
            await create_environment_restore(eb_id, uow)


class TestGetEnvironmentRestore:
    async def test_not_found_raises(self) -> None:
        from styrmin_backend.services.exceptions import EnvironmentRestoreNotFoundError

        uow = make_uow()
        with pytest.raises(EnvironmentRestoreNotFoundError):
            await get_environment_restore(uuid4(), uow)

    async def test_returns_existing(self) -> None:
        eb_id = uuid4()
        er_id = uuid4()
        er = EnvironmentRestore(
            id=er_id,
            name="test-restore",
            status=EnvironmentRestoreStatus.COMPLETED,
            environment_backup_id=eb_id,
        )
        uow = make_uow(environment_restores=[er])
        result = await get_environment_restore(er_id, uow)
        assert result.id == er_id


class TestGetEnvironmentRestores:
    async def test_returns_restores_for_backup(self) -> None:
        eb_id = uuid4()
        er1 = EnvironmentRestore(
            id=uuid4(),
            name="restore-1",
            status=EnvironmentRestoreStatus.COMPLETED,
            environment_backup_id=eb_id,
        )
        er2 = EnvironmentRestore(
            id=uuid4(),
            name="restore-2",
            status=EnvironmentRestoreStatus.FAILED,
            environment_backup_id=eb_id,
        )
        other = EnvironmentRestore(
            id=uuid4(),
            name="other",
            status=EnvironmentRestoreStatus.COMPLETED,
            environment_backup_id=uuid4(),
        )
        uow = make_uow(environment_restores=[er1, er2, other])
        result = await get_environment_restores(eb_id, uow)
        assert len(result) == 2

    async def test_filters_by_status(self) -> None:
        eb_id = uuid4()
        er1 = EnvironmentRestore(
            id=uuid4(),
            name="restore-1",
            status=EnvironmentRestoreStatus.COMPLETED,
            environment_backup_id=eb_id,
        )
        er2 = EnvironmentRestore(
            id=uuid4(),
            name="restore-2",
            status=EnvironmentRestoreStatus.FAILED,
            environment_backup_id=eb_id,
        )
        uow = make_uow(environment_restores=[er1, er2])
        result = await get_environment_restores(
            eb_id, uow, status=EnvironmentRestoreStatus.COMPLETED
        )
        assert len(result) == 1
