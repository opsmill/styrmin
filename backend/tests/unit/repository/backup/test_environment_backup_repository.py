"""Repository tests for the environment backup/restore parent records.

The guard queries are the enforcement point for research.md D6 ("one
environment-level operation per environment"), and because neither parent
stores a status they are EXISTS queries over the constituent rows — so the
no-children case and the terminal-children case both have to read as *not* in
progress.
"""

from datetime import datetime, timedelta, timezone
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
    EnvironmentBackup,
    EnvironmentRestore,
    InstanceStatus,
    Restore,
    RestoreStatus,
    Role,
    User,
)
from styrmin_backend.repository.environment_backup import (
    SQLModelEnvironmentBackupRepository,
    SQLModelEnvironmentRestoreRepository,
)


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
async def other_environment(session: AsyncSession, cluster: Cluster) -> Environment:
    env = Environment(name="other-env", cluster_id=cluster.id)
    session.add(env)
    await session.flush()
    return env


@pytest.fixture
async def creator(session: AsyncSession) -> User:
    user = User(
        username="env-backup-repo-creator",
        password_hash="x",
        display_name="env-backup-repo-creator",
        role=Role.ADMIN,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.fixture
async def instance(
    session: AsyncSession, environment: Environment, creator: User
) -> ApplicationInstance:
    deployment = Deployment(
        name="test-deployment",
        application_version="1.0.0",
        status=DeploymentState.RUNNING,
        application_driver_version_id=uuid4(),
        environment_id=environment.id,
        created_by_user_id=creator.id,
    )
    session.add(deployment)
    await session.flush()
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
def repository(session: AsyncSession) -> SQLModelEnvironmentBackupRepository:
    return SQLModelEnvironmentBackupRepository(session)


@pytest.fixture
def restore_repository(session: AsyncSession) -> SQLModelEnvironmentRestoreRepository:
    return SQLModelEnvironmentRestoreRepository(session)


async def _add_constituent_backup(
    session: AsyncSession,
    environment_backup: EnvironmentBackup,
    instance: ApplicationInstance,
    status: BackupStatus,
    name: str,
) -> Backup:
    backup = Backup(
        name=name,
        status=status,
        instance_id=instance.id,
        environment_backup_id=environment_backup.id,
    )
    session.add(backup)
    await session.flush()
    return backup


async def _add_constituent_restore(
    session: AsyncSession,
    environment_restore: EnvironmentRestore,
    backup: Backup,
    status: RestoreStatus,
    name: str,
) -> Restore:
    restore = Restore(
        name=name,
        status=status,
        target_namespace="styrmin-test",
        backup_id=backup.id,
        environment_restore_id=environment_restore.id,
    )
    session.add(restore)
    await session.flush()
    return restore


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_get_environment_backup_round_trips_json_columns(
    repository: SQLModelEnvironmentBackupRepository,
    environment: Environment,
) -> None:
    deployment_id = str(uuid4())
    created = await repository.create(
        EnvironmentBackup(
            name="styrmin-envbackup-001",
            environment_id=environment.id,
            environment_config={"dns_zone": "example.com"},
            deployment_snapshots=[
                {"deployment_id": deployment_id, "deployment_name": "infrahub"}
            ],
            constituent_errors=[
                {"deployment_id": deployment_id, "error": "already in progress"}
            ],
        )
    )

    fetched = await repository.get(created.id)

    assert fetched is not None
    assert fetched.name == "styrmin-envbackup-001"
    assert fetched.environment_id == environment.id
    assert fetched.environment_config == {"dns_zone": "example.com"}
    assert fetched.deployment_snapshots == [
        {"deployment_id": deployment_id, "deployment_name": "infrahub"}
    ]
    assert fetched.constituent_errors == [
        {"deployment_id": deployment_id, "error": "already in progress"}
    ]


@pytest.mark.asyncio
async def test_environment_backup_json_columns_default_to_none(
    repository: SQLModelEnvironmentBackupRepository,
    environment: Environment,
) -> None:
    """A config-only snapshot of an empty environment stores no lists."""
    created = await repository.create(
        EnvironmentBackup(name="styrmin-envbackup-empty", environment_id=environment.id)
    )

    fetched = await repository.get(created.id)

    assert fetched is not None
    assert fetched.environment_config is None
    assert fetched.deployment_snapshots is None
    assert fetched.constituent_errors is None


@pytest.mark.asyncio
async def test_create_and_get_environment_restore_round_trips(
    repository: SQLModelEnvironmentBackupRepository,
    restore_repository: SQLModelEnvironmentRestoreRepository,
    environment: Environment,
) -> None:
    parent = await repository.create(
        EnvironmentBackup(name="styrmin-envbackup-r1", environment_id=environment.id)
    )
    created = await restore_repository.create(
        EnvironmentRestore(
            environment_backup_id=parent.id,
            skipped_constituents=[
                {"deployment_name": "gone", "reason": "deployment no longer exists"}
            ],
        )
    )

    fetched = await restore_repository.get(created.id)

    assert fetched is not None
    assert fetched.environment_backup_id == parent.id
    assert fetched.skipped_constituents == [
        {"deployment_name": "gone", "reason": "deployment no longer exists"}
    ]


@pytest.mark.asyncio
async def test_delete_environment_backup(
    repository: SQLModelEnvironmentBackupRepository,
    environment: Environment,
) -> None:
    created = await repository.create(
        EnvironmentBackup(name="styrmin-envbackup-del", environment_id=environment.id)
    )

    await repository.delete(created)

    assert await repository.get(created.id) is None


# ---------------------------------------------------------------------------
# Listing / ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_by_environment_id_returns_newest_first(
    session: AsyncSession,
    repository: SQLModelEnvironmentBackupRepository,
    environment: Environment,
    other_environment: Environment,
) -> None:
    base = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
    for offset, name in enumerate(["oldest", "middle", "newest"]):
        created = await repository.create(
            EnvironmentBackup(name=name, environment_id=environment.id)
        )
        created.created_on = base + timedelta(minutes=offset)
        session.add(created)
    await repository.create(
        EnvironmentBackup(name="other-env-backup", environment_id=other_environment.id)
    )
    await session.flush()

    results = await repository.get_by_environment_id(environment.id)

    assert [backup.name for backup in results] == ["newest", "middle", "oldest"]


@pytest.mark.asyncio
async def test_get_by_environment_id_is_empty_for_unknown_environment(
    repository: SQLModelEnvironmentBackupRepository,
) -> None:
    assert await repository.get_by_environment_id(uuid4()) == []


@pytest.mark.asyncio
async def test_get_by_environment_backup_id_returns_newest_first(
    session: AsyncSession,
    repository: SQLModelEnvironmentBackupRepository,
    restore_repository: SQLModelEnvironmentRestoreRepository,
    environment: Environment,
) -> None:
    parent = await repository.create(
        EnvironmentBackup(name="styrmin-envbackup-list", environment_id=environment.id)
    )
    unrelated = await repository.create(
        EnvironmentBackup(name="styrmin-envbackup-other", environment_id=environment.id)
    )
    base = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
    ids = []
    for offset in range(3):
        restore = await restore_repository.create(
            EnvironmentRestore(environment_backup_id=parent.id)
        )
        restore.created_on = base + timedelta(minutes=offset)
        session.add(restore)
        ids.append(restore.id)
    await restore_repository.create(
        EnvironmentRestore(environment_backup_id=unrelated.id)
    )
    await session.flush()

    results = await restore_repository.get_by_environment_backup_id(parent.id)

    assert [restore.id for restore in results] == list(reversed(ids))


# ---------------------------------------------------------------------------
# D6 concurrency guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [BackupStatus.PENDING, BackupStatus.IN_PROGRESS])
async def test_has_in_progress_environment_backup_detects_non_terminal_child(
    session: AsyncSession,
    repository: SQLModelEnvironmentBackupRepository,
    environment: Environment,
    instance: ApplicationInstance,
    status: BackupStatus,
) -> None:
    parent = await repository.create(
        EnvironmentBackup(
            name=f"styrmin-envbackup-{status.value}", environment_id=environment.id
        )
    )
    await _add_constituent_backup(
        session, parent, instance, status, f"constituent-{status.value}"
    )

    result = await repository.has_in_progress_environment_backup(environment.id)

    assert result is not None
    assert result.id == parent.id


@pytest.mark.asyncio
async def test_has_in_progress_environment_backup_ignores_terminal_children(
    session: AsyncSession,
    repository: SQLModelEnvironmentBackupRepository,
    environment: Environment,
    instance: ApplicationInstance,
) -> None:
    parent = await repository.create(
        EnvironmentBackup(name="styrmin-envbackup-done", environment_id=environment.id)
    )
    await _add_constituent_backup(
        session, parent, instance, BackupStatus.COMPLETED, "constituent-completed"
    )
    await _add_constituent_backup(
        session, parent, instance, BackupStatus.FAILED, "constituent-failed"
    )

    assert await repository.has_in_progress_environment_backup(environment.id) is None


@pytest.mark.asyncio
async def test_has_in_progress_environment_backup_with_no_children_is_none(
    repository: SQLModelEnvironmentBackupRepository,
    environment: Environment,
) -> None:
    """A config-only snapshot never pins the environment (FR-011)."""
    await repository.create(
        EnvironmentBackup(name="styrmin-envbackup-bare", environment_id=environment.id)
    )

    assert await repository.has_in_progress_environment_backup(environment.id) is None


@pytest.mark.asyncio
async def test_has_in_progress_environment_backup_ignores_standalone_backups(
    session: AsyncSession,
    repository: SQLModelEnvironmentBackupRepository,
    environment: Environment,
    instance: ApplicationInstance,
) -> None:
    """A per-instance backup with a null FK is not a constituent of anything."""
    await repository.create(
        EnvironmentBackup(name="styrmin-envbackup-idle", environment_id=environment.id)
    )
    session.add(
        Backup(
            name="standalone-backup",
            status=BackupStatus.IN_PROGRESS,
            instance_id=instance.id,
        )
    )
    await session.flush()

    assert await repository.has_in_progress_environment_backup(environment.id) is None


@pytest.mark.asyncio
async def test_has_in_progress_environment_backup_is_scoped_to_the_environment(
    session: AsyncSession,
    repository: SQLModelEnvironmentBackupRepository,
    environment: Environment,
    other_environment: Environment,
    instance: ApplicationInstance,
) -> None:
    parent = await repository.create(
        EnvironmentBackup(
            name="styrmin-envbackup-elsewhere", environment_id=other_environment.id
        )
    )
    await _add_constituent_backup(
        session, parent, instance, BackupStatus.IN_PROGRESS, "constituent-elsewhere"
    )

    assert await repository.has_in_progress_environment_backup(environment.id) is None
    assert (
        await repository.has_in_progress_environment_backup(other_environment.id)
    ) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [RestoreStatus.PENDING, RestoreStatus.IN_PROGRESS])
async def test_has_in_progress_environment_restore_detects_non_terminal_child(
    session: AsyncSession,
    repository: SQLModelEnvironmentBackupRepository,
    restore_repository: SQLModelEnvironmentRestoreRepository,
    environment: Environment,
    instance: ApplicationInstance,
    status: RestoreStatus,
) -> None:
    parent = await repository.create(
        EnvironmentBackup(
            name=f"styrmin-envbackup-src-{status.value}", environment_id=environment.id
        )
    )
    backup = await _add_constituent_backup(
        session, parent, instance, BackupStatus.COMPLETED, f"src-{status.value}"
    )
    environment_restore = await restore_repository.create(
        EnvironmentRestore(environment_backup_id=parent.id)
    )
    await _add_constituent_restore(
        session, environment_restore, backup, status, f"restore-{status.value}"
    )

    result = await restore_repository.has_in_progress_environment_restore(
        environment.id
    )

    assert result is not None
    assert result.id == environment_restore.id


@pytest.mark.asyncio
async def test_has_in_progress_environment_restore_ignores_terminal_children(
    session: AsyncSession,
    repository: SQLModelEnvironmentBackupRepository,
    restore_repository: SQLModelEnvironmentRestoreRepository,
    environment: Environment,
    instance: ApplicationInstance,
) -> None:
    parent = await repository.create(
        EnvironmentBackup(
            name="styrmin-envbackup-src-done", environment_id=environment.id
        )
    )
    backup = await _add_constituent_backup(
        session, parent, instance, BackupStatus.COMPLETED, "src-done"
    )
    environment_restore = await restore_repository.create(
        EnvironmentRestore(environment_backup_id=parent.id)
    )
    await _add_constituent_restore(
        session, environment_restore, backup, RestoreStatus.COMPLETED, "restore-done"
    )

    assert (
        await restore_repository.has_in_progress_environment_restore(environment.id)
        is None
    )


@pytest.mark.asyncio
async def test_has_in_progress_environment_restore_with_no_children_is_none(
    repository: SQLModelEnvironmentBackupRepository,
    restore_repository: SQLModelEnvironmentRestoreRepository,
    environment: Environment,
) -> None:
    """An all-skipped restore has zero constituents and must not pin the env."""
    parent = await repository.create(
        EnvironmentBackup(
            name="styrmin-envbackup-src-bare", environment_id=environment.id
        )
    )
    await restore_repository.create(
        EnvironmentRestore(
            environment_backup_id=parent.id,
            skipped_constituents=[
                {"deployment_name": "gone", "reason": "deployment no longer exists"}
            ],
        )
    )

    assert (
        await restore_repository.has_in_progress_environment_restore(environment.id)
        is None
    )


@pytest.mark.asyncio
async def test_has_in_progress_environment_restore_is_scoped_to_the_environment(
    session: AsyncSession,
    repository: SQLModelEnvironmentBackupRepository,
    restore_repository: SQLModelEnvironmentRestoreRepository,
    environment: Environment,
    other_environment: Environment,
    instance: ApplicationInstance,
) -> None:
    parent = await repository.create(
        EnvironmentBackup(
            name="styrmin-envbackup-src-elsewhere",
            environment_id=other_environment.id,
        )
    )
    backup = await _add_constituent_backup(
        session, parent, instance, BackupStatus.COMPLETED, "src-elsewhere"
    )
    environment_restore = await restore_repository.create(
        EnvironmentRestore(environment_backup_id=parent.id)
    )
    await _add_constituent_restore(
        session,
        environment_restore,
        backup,
        RestoreStatus.IN_PROGRESS,
        "restore-elsewhere",
    )

    assert (
        await restore_repository.has_in_progress_environment_restore(environment.id)
        is None
    )
    assert (
        await restore_repository.has_in_progress_environment_restore(
            other_environment.id
        )
        is not None
    )
