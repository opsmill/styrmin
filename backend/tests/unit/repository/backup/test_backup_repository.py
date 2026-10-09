from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    ApplicationInstance,
    Backup,
    BackupStatus,
    Deployment,
    DeploymentState,
    Environment,
    EnvironmentBackup,
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


async def _create_deployment_with_instance(
    session: AsyncSession, environment: Environment, creator: User, name: str
) -> ApplicationInstance:
    dep = Deployment(
        name=name,
        application_version="1.0.0",
        status=DeploymentState.RUNNING,
        application_driver_version_id=uuid4(),
        environment_id=environment.id,
        created_by_user_id=creator.id,
    )
    session.add(dep)
    await session.flush()
    inst = ApplicationInstance(
        name=f"{name}-instance",
        application_version="1.0.0",
        status=InstanceStatus.RUNNING,
        deployment_id=dep.id,
        application_driver_version_id=uuid4(),
    )
    session.add(inst)
    await session.flush()
    return inst


@pytest.fixture
async def second_instance(
    session: AsyncSession, deployment: Deployment
) -> ApplicationInstance:
    """A later instance of the same deployment, as an upgrade would create."""
    inst = ApplicationInstance(
        name="test-instance-upgraded",
        application_version="2.0.0",
        status=InstanceStatus.RUNNING,
        deployment_id=deployment.id,
        application_driver_version_id=uuid4(),
    )
    session.add(inst)
    await session.flush()
    return inst


_BASE_TIME = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def _history_backup(
    name: str,
    instance_id: UUID,
    minutes: int,
    status: BackupStatus = BackupStatus.COMPLETED,
    environment_backup_id: UUID | None = None,
) -> Backup:
    return Backup(
        name=name,
        status=status,
        instance_id=instance_id,
        environment_backup_id=environment_backup_id,
        created_on=_BASE_TIME + timedelta(minutes=minutes),
    )


@pytest.mark.asyncio
async def test_get_by_deployment_id_returns_every_instance_newest_first(
    repository: SQLModelBackupRepository,
    deployment: Deployment,
    instance: ApplicationInstance,
    second_instance: ApplicationInstance,
):
    await repository.create(_history_backup("before-upgrade", instance.id, 0))
    await repository.create(_history_backup("after-upgrade", second_instance.id, 2))
    await repository.create(_history_backup("old-instance-late", instance.id, 1))

    results = await repository.get_by_deployment_id(deployment.id)

    assert [b.name for b in results] == [
        "after-upgrade",
        "old-instance-late",
        "before-upgrade",
    ]


@pytest.mark.asyncio
async def test_get_by_deployment_id_excludes_other_deployment(
    session: AsyncSession,
    repository: SQLModelBackupRepository,
    environment: Environment,
    creator: User,
    deployment: Deployment,
    instance: ApplicationInstance,
):
    other_instance = await _create_deployment_with_instance(
        session, environment, creator, "other-deployment"
    )
    await repository.create(_history_backup("own", instance.id, 0))
    await repository.create(_history_backup("other", other_instance.id, 1))

    results = await repository.get_by_deployment_id(deployment.id)

    assert [b.name for b in results] == ["own"]


@pytest.mark.asyncio
async def test_get_by_deployment_id_with_status_filter(
    repository: SQLModelBackupRepository,
    deployment: Deployment,
    instance: ApplicationInstance,
    second_instance: ApplicationInstance,
):
    await repository.create(_history_backup("completed-old", instance.id, 0))
    await repository.create(
        _history_backup("failed", second_instance.id, 1, status=BackupStatus.FAILED)
    )
    await repository.create(_history_backup("completed-new", second_instance.id, 2))

    results = await repository.get_by_deployment_id(
        deployment.id, status=BackupStatus.COMPLETED
    )

    assert [b.name for b in results] == ["completed-new", "completed-old"]


@pytest.mark.asyncio
async def test_get_by_deployment_id_unknown_deployment_returns_empty(
    repository: SQLModelBackupRepository,
    instance: ApplicationInstance,
):
    await repository.create(_history_backup("unrelated", instance.id, 0))

    assert list(await repository.get_by_deployment_id(uuid4())) == []


@pytest.mark.asyncio
async def test_get_by_deployment_id_includes_constituent_backup(
    session: AsyncSession,
    repository: SQLModelBackupRepository,
    environment: Environment,
    deployment: Deployment,
    instance: ApplicationInstance,
):
    parent = EnvironmentBackup(name="env-backup", environment_id=environment.id)
    session.add(parent)
    await session.flush()
    await repository.create(
        _history_backup("constituent", instance.id, 0, environment_backup_id=parent.id)
    )

    results = await repository.get_by_deployment_id(deployment.id)

    assert [b.name for b in results] == ["constituent"]
    assert results[0].environment_backup_id == parent.id


@pytest.mark.asyncio
async def test_get_by_deployment_id_lists_nothing_for_an_internal_deployment(
    session: AsyncSession,
    repository: SQLModelBackupRepository,
    deployment: Deployment,
    instance: ApplicationInstance,
):
    deployment.internal = True
    session.add(deployment)
    await session.flush()
    await repository.create(_history_backup("internal", instance.id, 0))

    assert await repository.get_by_deployment_id(deployment.id) == []
    assert [b.name for b in await repository.get_by_instance_id(instance.id)] == [
        "internal"
    ]


@pytest.mark.asyncio
async def test_get_by_deployment_id_breaks_a_created_on_tie_by_id(
    repository: SQLModelBackupRepository,
    deployment: Deployment,
    instance: ApplicationInstance,
    second_instance: ApplicationInstance,
):
    first = await repository.create(_history_backup("first", instance.id, 0))
    second = await repository.create(_history_backup("second", second_instance.id, 0))

    results = await repository.get_by_deployment_id(deployment.id)

    assert [b.id for b in results] == sorted([first.id, second.id], reverse=True)
