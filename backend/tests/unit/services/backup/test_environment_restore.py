"""Unit tests for environment restore service functions.

Note: Full restore creation and status aggregation tests require a real
database session and are covered by integration tests.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from styrmin_backend.services.backup.environment import (
    create_environment_restore,
)
from styrmin_backend.services.exceptions import (
    EnvironmentBackupNotFoundError,
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


def make_uow() -> FakeUnitOfWork:
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
    )


class TestCreateEnvironmentRestore:
    @pytest.mark.asyncio
    async def test_backup_not_found_raises(self) -> None:
        uow = make_uow()
        with pytest.raises(EnvironmentBackupNotFoundError):
            await create_environment_restore(uuid4(), uow)
