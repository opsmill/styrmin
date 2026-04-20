from uuid import uuid4

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    BackupSchedule,
    Cluster,
    Deployment,
    DeploymentState,
    Environment,
)
from styrmin_backend.repository.backup_schedule import SQLModelBackupScheduleRepository


@pytest.fixture
async def cluster(session: AsyncSession) -> Cluster:
    cluster = Cluster(name="test-cluster")
    session.add(cluster)
    await session.flush()
    return cluster


@pytest.fixture
async def environment(session: AsyncSession, cluster: Cluster) -> Environment:
    env = Environment(name="test-env", cluster_id=cluster.id)
    session.add(env)
    await session.flush()
    return env


@pytest.fixture
async def deployment(session: AsyncSession, environment: Environment) -> Deployment:
    dep = Deployment(
        name="test-deployment",
        application_version="1.0.0",
        status=DeploymentState.RUNNING,
        application_driver_version_id=uuid4(),
        environment_id=environment.id,
    )
    session.add(dep)
    await session.flush()
    return dep


@pytest.fixture
def repository(session: AsyncSession) -> SQLModelBackupScheduleRepository:
    return SQLModelBackupScheduleRepository(session)


@pytest.mark.asyncio
async def test_create_schedule(
    repository: SQLModelBackupScheduleRepository,
    deployment: Deployment,
):
    schedule = BackupSchedule(
        name="daily-backup",
        cron_expression="0 2 * * *",
        deployment_id=deployment.id,
    )
    created = await repository.create(schedule)
    assert created.id is not None
    assert created.name == "daily-backup"
    assert created.enabled is True
    assert created.retention_count == 10


@pytest.mark.asyncio
async def test_get_schedule(
    repository: SQLModelBackupScheduleRepository,
    deployment: Deployment,
):
    schedule = BackupSchedule(
        name="weekly-backup",
        cron_expression="0 0 * * 0",
        deployment_id=deployment.id,
    )
    created = await repository.create(schedule)
    result = await repository.get(created.id)
    assert result is not None
    assert result.id == created.id
    assert result.cron_expression == "0 0 * * 0"


@pytest.mark.asyncio
async def test_get_by_deployment_id(
    repository: SQLModelBackupScheduleRepository,
    deployment: Deployment,
):
    await repository.create(
        BackupSchedule(
            name="schedule-1",
            cron_expression="0 2 * * *",
            deployment_id=deployment.id,
        )
    )
    await repository.create(
        BackupSchedule(
            name="schedule-2",
            cron_expression="0 0 * * 0",
            deployment_id=deployment.id,
        )
    )
    results = await repository.get_by_deployment_id(deployment.id)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_get_by_deployment_id_empty(
    repository: SQLModelBackupScheduleRepository,
):
    results = await repository.get_by_deployment_id(uuid4())
    assert len(results) == 0


@pytest.mark.asyncio
async def test_delete_schedule(
    repository: SQLModelBackupScheduleRepository,
    deployment: Deployment,
):
    schedule = await repository.create(
        BackupSchedule(
            name="delete-me",
            cron_expression="0 2 * * *",
            deployment_id=deployment.id,
        )
    )
    await repository.delete(schedule)
    result = await repository.get(schedule.id)
    assert result is None
