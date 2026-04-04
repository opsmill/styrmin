"""Unit tests for environment backup service functions.

Note: Tests that require uow.session.exec() (e.g., status aggregation, delete
with in-progress checks) are covered by integration tests since the FakeSession
does not support SQLModel select() queries.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from styrmin_backend.db.models import (
    ApplicationInstance,
    Environment,
)
from styrmin_backend.services.backup.environment import (
    create_environment_backup,
)
from styrmin_backend.services.exceptions import (
    EnvironmentBackupValidationError,
    EnvironmentNotFoundError,
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
    environments: list[Environment] | None = None,
    instances: list[ApplicationInstance] | None = None,
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
    )


class TestCreateEnvironmentBackup:
    @pytest.mark.asyncio
    async def test_environment_not_found_raises(self) -> None:
        uow = make_uow()
        with pytest.raises(EnvironmentNotFoundError):
            await create_environment_backup(uuid4(), uow)

    @pytest.mark.asyncio
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
