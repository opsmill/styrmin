from uuid import uuid4

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    ApplicationInstance,
    Backup,
    BackupStatus,
    Deployment,
    DeploymentState,
    Environment,
    Cluster,
    InstanceStatus,
    Role,
    User,
)
from styrmin_backend.repository.backup import SQLModelBackupRepository


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
async def creator(session: AsyncSession) -> User:
    user = User(
        username="repo-test-creator",
        password_hash="x",
        display_name="repo-test-creator",
        role=Role.ADMIN,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.fixture
async def deployment(
    session: AsyncSession, environment: Environment, creator: User
) -> Deployment:
    dep = Deployment(
        name="test-deployment",
        application_version="1.0.0",
        status=DeploymentState.RUNNING,
        application_driver_version_id=uuid4(),
        environment_id=environment.id,
        created_by_user_id=creator.id,
    )
    session.add(dep)
    await session.flush()
    return dep


@pytest.fixture
async def instance(
    session: AsyncSession, deployment: Deployment
) -> ApplicationInstance:
    inst = ApplicationInstance(
        name="test-instance",
        application_version="1.0.0",
        status=InstanceStatus.RUNNING,
        deployment_id=deployment.id,
        application_driver_version_id=uuid4(),
    )
    session.add(inst)
    await session.flush()
    return inst


@pytest.fixture
def repository(session: AsyncSession) -> SQLModelBackupRepository:
    return SQLModelBackupRepository(session)


@pytest.mark.asyncio
async def test_create_backup(
    repository: SQLModelBackupRepository,
    instance: ApplicationInstance,
):
    backup = Backup(
        name="test-backup-001",
        status=BackupStatus.PENDING,
        instance_id=instance.id,
    )
    created = await repository.create(backup)
    assert created.id is not None
    assert created.name == "test-backup-001"
    assert created.status == BackupStatus.PENDING


@pytest.mark.asyncio
async def test_get_backup(
    repository: SQLModelBackupRepository,
    instance: ApplicationInstance,
):
    backup = Backup(
        name="test-backup-002",
        status=BackupStatus.COMPLETED,
        instance_id=instance.id,
    )
    created = await repository.create(backup)
    result = await repository.get(created.id)
    assert result is not None
    assert result.id == created.id
    assert result.name == "test-backup-002"


@pytest.mark.asyncio
async def test_get_by_instance_id(
    repository: SQLModelBackupRepository,
    instance: ApplicationInstance,
):
    for i in range(3):
        await repository.create(
            Backup(
                name=f"test-backup-{i}",
                status=BackupStatus.COMPLETED,
                instance_id=instance.id,
            )
        )
    results = await repository.get_by_instance_id(instance.id)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_get_by_instance_id_with_status_filter(
    repository: SQLModelBackupRepository,
    instance: ApplicationInstance,
):
    await repository.create(
        Backup(
            name="test-backup-completed",
            status=BackupStatus.COMPLETED,
            instance_id=instance.id,
        )
    )
    await repository.create(
        Backup(
            name="test-backup-failed",
            status=BackupStatus.FAILED,
            instance_id=instance.id,
        )
    )
    results = await repository.get_by_instance_id(
        instance.id, status=BackupStatus.COMPLETED
    )
    assert len(results) == 1
    assert results[0].status == BackupStatus.COMPLETED


@pytest.mark.asyncio
async def test_has_in_progress_backup(
    repository: SQLModelBackupRepository,
    instance: ApplicationInstance,
):
    await repository.create(
        Backup(
            name="test-backup-in-progress",
            status=BackupStatus.IN_PROGRESS,
            instance_id=instance.id,
        )
    )
    result = await repository.has_in_progress_backup(instance.id)
    assert result is not None
    assert result.status == BackupStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_has_in_progress_backup_returns_none(
    repository: SQLModelBackupRepository,
    instance: ApplicationInstance,
):
    await repository.create(
        Backup(
            name="test-backup-completed",
            status=BackupStatus.COMPLETED,
            instance_id=instance.id,
        )
    )
    result = await repository.has_in_progress_backup(instance.id)
    assert result is None


@pytest.mark.asyncio
async def test_delete_backup(
    repository: SQLModelBackupRepository,
    instance: ApplicationInstance,
):
    backup = await repository.create(
        Backup(
            name="test-backup-delete",
            status=BackupStatus.COMPLETED,
            instance_id=instance.id,
        )
    )
    await repository.delete(backup)
    result = await repository.get(backup.id)
    assert result is None
