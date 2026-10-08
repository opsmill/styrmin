from uuid import uuid4

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    ApplicationInstance,
    Backup,
    BackupStatus,
    Cluster,
    Deployment,
    DeploymentState,
    Environment,
    InstanceStatus,
    Restore,
    RestoreStatus,
    Role,
    User,
)
from styrmin_backend.repository.restore import SQLModelRestoreRepository


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
        sequence=1,
    )
    session.add(inst)
    await session.flush()
    return inst


@pytest.fixture
async def backup(session: AsyncSession, instance: ApplicationInstance) -> Backup:
    backup = Backup(
        name="test-backup",
        status=BackupStatus.COMPLETED,
        instance_id=instance.id,
    )
    session.add(backup)
    await session.flush()
    return backup


@pytest.fixture
def repository(session: AsyncSession) -> SQLModelRestoreRepository:
    return SQLModelRestoreRepository(session)


@pytest.mark.asyncio
async def test_create_restore(
    repository: SQLModelRestoreRepository,
    backup: Backup,
):
    restore = Restore(
        name="test-restore-001",
        status=RestoreStatus.PENDING,
        target_namespace="test-ns",
        backup_id=backup.id,
    )
    created = await repository.create(restore)
    assert created.id is not None
    assert created.name == "test-restore-001"
    assert created.status == RestoreStatus.PENDING


@pytest.mark.asyncio
async def test_get_restore(
    repository: SQLModelRestoreRepository,
    backup: Backup,
):
    restore = Restore(
        name="test-restore-002",
        status=RestoreStatus.COMPLETED,
        target_namespace="test-ns",
        backup_id=backup.id,
    )
    created = await repository.create(restore)
    result = await repository.get(created.id)
    assert result is not None
    assert result.id == created.id


@pytest.mark.asyncio
async def test_get_by_backup_id(
    repository: SQLModelRestoreRepository,
    backup: Backup,
):
    for i in range(2):
        await repository.create(
            Restore(
                name=f"test-restore-{i}",
                status=RestoreStatus.COMPLETED,
                target_namespace="test-ns",
                backup_id=backup.id,
            )
        )
    results = await repository.get_by_backup_id(backup.id)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_get_by_backup_id_with_status_filter(
    repository: SQLModelRestoreRepository,
    backup: Backup,
):
    await repository.create(
        Restore(
            name="test-restore-completed",
            status=RestoreStatus.COMPLETED,
            target_namespace="test-ns",
            backup_id=backup.id,
        )
    )
    await repository.create(
        Restore(
            name="test-restore-failed",
            status=RestoreStatus.FAILED,
            target_namespace="test-ns",
            backup_id=backup.id,
        )
    )
    results = await repository.get_by_backup_id(
        backup.id, status=RestoreStatus.COMPLETED
    )
    assert len(results) == 1
    assert results[0].status == RestoreStatus.COMPLETED


@pytest.mark.asyncio
async def test_delete_restore(
    repository: SQLModelRestoreRepository,
    backup: Backup,
):
    restore = await repository.create(
        Restore(
            name="test-restore-delete",
            status=RestoreStatus.COMPLETED,
            target_namespace="test-ns",
            backup_id=backup.id,
        )
    )
    await repository.delete(restore)
    result = await repository.get(restore.id)
    assert result is None


@pytest.mark.asyncio
async def test_get_non_terminal_by_source_deployment_id(
    session: AsyncSession,
    repository: SQLModelRestoreRepository,
    deployment: Deployment,
    backup: Backup,
):
    """Matches restores of the deployment's own backups in any namespace,
    skipping terminal ones and restores of another deployment's backups."""
    other_deployment = Deployment(
        name="other-deployment",
        application_version="1.0.0",
        status=DeploymentState.RUNNING,
        application_driver_version_id=uuid4(),
        environment_id=deployment.environment_id,
        created_by_user_id=deployment.created_by_user_id,
    )
    session.add(other_deployment)
    await session.flush()
    other_instance = ApplicationInstance(
        name="other-instance",
        application_version="1.0.0",
        status=InstanceStatus.RUNNING,
        deployment_id=other_deployment.id,
        application_driver_version_id=uuid4(),
        sequence=1,
    )
    session.add(other_instance)
    await session.flush()
    other_backup = Backup(
        name="other-backup",
        status=BackupStatus.COMPLETED,
        instance_id=other_instance.id,
    )
    session.add(other_backup)
    await session.flush()

    pending = await repository.create(
        Restore(
            name="restore-pending",
            status=RestoreStatus.PENDING,
            target_namespace="custom-ns",
            backup_id=backup.id,
        )
    )
    in_progress = await repository.create(
        Restore(
            name="restore-in-progress",
            status=RestoreStatus.IN_PROGRESS,
            target_namespace=f"styrmin-{deployment.id}",
            backup_id=backup.id,
        )
    )
    for name, status, backup_id in [
        ("restore-completed", RestoreStatus.COMPLETED, backup.id),
        ("restore-failed", RestoreStatus.FAILED, backup.id),
        ("restore-other", RestoreStatus.IN_PROGRESS, other_backup.id),
    ]:
        await repository.create(
            Restore(
                name=name,
                status=status,
                target_namespace="custom-ns",
                backup_id=backup_id,
            )
        )

    results = await repository.get_non_terminal_by_source_deployment_id(deployment.id)

    assert {r.id for r in results} == {pending.id, in_progress.id}
    other_results = await repository.get_non_terminal_by_source_deployment_id(
        other_deployment.id
    )
    assert [r.name for r in other_results] == ["restore-other"]
