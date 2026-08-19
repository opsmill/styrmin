"""Repository tests for the environment clone record.

The clone stores no status and its terminality is not EXISTS-able, so the
derivation runs in Python over rows this repository loads. Two properties of
that loading are what these tests pin down:

* the record round-trips every nullable foreign key and JSON column, because
  provenance has to survive the deletion of everything it points at, and
* the constituent restores behind the JSON ``restore_id`` values are fetched
  for a whole batch of clones with **one** query — the derivation reads them
  for every clone of an environment on every read.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

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
    EnvironmentClone,
    InstanceStatus,
    Restore,
    RestoreStatus,
    Role,
    User,
)
from styrmin_backend.repository.environment_clone import (
    SQLModelEnvironmentCloneRepository,
    referenced_restore_ids,
)


@pytest.fixture
async def cluster(session: AsyncSession) -> Cluster:
    cluster = Cluster(name="clone-cluster")
    session.add(cluster)
    await session.flush()
    return cluster


@pytest.fixture
async def source_environment(session: AsyncSession, cluster: Cluster) -> Environment:
    env = Environment(name="source-env", cluster_id=cluster.id)
    session.add(env)
    await session.flush()
    return env


@pytest.fixture
async def created_environment(session: AsyncSession, cluster: Cluster) -> Environment:
    env = Environment(name="created-env", cluster_id=cluster.id)
    session.add(env)
    await session.flush()
    return env


@pytest.fixture
async def creator(session: AsyncSession) -> User:
    user = User(
        username="env-clone-repo-creator",
        password_hash="x",
        display_name="env-clone-repo-creator",
        role=Role.ADMIN,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.fixture
async def instance(
    session: AsyncSession, source_environment: Environment, creator: User
) -> ApplicationInstance:
    deployment = Deployment(
        name="clone-source-deployment",
        application_version="1.0.0",
        status=DeploymentState.RUNNING,
        application_driver_version_id=uuid4(),
        environment_id=source_environment.id,
        created_by_user_id=creator.id,
    )
    session.add(deployment)
    await session.flush()
    inst = ApplicationInstance(
        name="clone-source-instance",
        application_version="1.0.0",
        status=InstanceStatus.RUNNING,
        deployment_id=deployment.id,
        application_driver_version_id=uuid4(),
    )
    session.add(inst)
    await session.flush()
    return inst


@pytest.fixture
async def capture(
    session: AsyncSession, source_environment: Environment
) -> EnvironmentBackup:
    backup = EnvironmentBackup(
        name="styrmin-envbackup-clone-capture",
        environment_id=source_environment.id,
    )
    session.add(backup)
    await session.flush()
    return backup


@pytest.fixture
def repository(session: AsyncSession) -> SQLModelEnvironmentCloneRepository:
    return SQLModelEnvironmentCloneRepository(session)


async def _add_restore(
    session: AsyncSession,
    instance: ApplicationInstance,
    capture: EnvironmentBackup,
    status: RestoreStatus,
    name: str,
) -> Restore:
    backup = Backup(
        name=f"{name}-backup",
        status=BackupStatus.COMPLETED,
        instance_id=instance.id,
        environment_backup_id=capture.id,
    )
    session.add(backup)
    await session.flush()
    restore = Restore(
        name=name,
        status=status,
        target_namespace="styrmin-counterpart",
        backup_id=backup.id,
    )
    session.add(restore)
    await session.flush()
    return restore


def _result(deployment_id: UUID, outcome: str, restore_id: UUID | None) -> dict:
    return {
        "deployment_id": str(deployment_id),
        "deployment_name": "postgres-main",
        "outcome": outcome,
        "reason": None,
        "counterpart_deployment_id": None,
        "restore_id": None if restore_id is None else str(restore_id),
    }


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_get_round_trips_json_columns_and_links(
    repository: SQLModelEnvironmentCloneRepository,
    source_environment: Environment,
    created_environment: Environment,
    capture: EnvironmentBackup,
    creator: User,
) -> None:
    deployment_id = uuid4()
    restore_id = uuid4()
    created = await repository.create(
        EnvironmentClone(
            name="created-env",
            source_environment_id=source_environment.id,
            source_environment_name=source_environment.name,
            environment_backup_id=capture.id,
            created_environment_id=created_environment.id,
            requested_deployment_ids=[str(deployment_id)],
            config_override={"dns_zone": "clone.example.com"},
            cleared_config_fields=["backup_storage_location_id"],
            deployment_results=[_result(deployment_id, "cloned", restore_id)],
            clone_errors=[
                {"step": "capture", "error": "one constituent failed", "fatal": False}
            ],
            created_by_user_id=creator.id,
        )
    )

    fetched = await repository.get(created.id)

    assert fetched is not None
    assert fetched.name == "created-env"
    assert fetched.source_environment_id == source_environment.id
    assert fetched.source_environment_name == "source-env"
    assert fetched.environment_backup_id == capture.id
    assert fetched.created_environment_id == created_environment.id
    assert fetched.requested_deployment_ids == [str(deployment_id)]
    assert fetched.config_override == {"dns_zone": "clone.example.com"}
    assert fetched.cleared_config_fields == ["backup_storage_location_id"]
    assert fetched.deployment_results == [_result(deployment_id, "cloned", restore_id)]
    assert fetched.clone_errors == [
        {"step": "capture", "error": "one constituent failed", "fatal": False}
    ]
    assert fetched.created_by_user_id == creator.id


@pytest.mark.asyncio
async def test_get_eager_loads_provenance_and_capture_constituents(
    session: AsyncSession,
    repository: SQLModelEnvironmentCloneRepository,
    source_environment: Environment,
    created_environment: Environment,
    capture: EnvironmentBackup,
    instance: ApplicationInstance,
) -> None:
    """The derivation reads the capture's constituents, so they load up front."""
    session.add(
        Backup(
            name="clone-capture-constituent",
            status=BackupStatus.COMPLETED,
            instance_id=instance.id,
            environment_backup_id=capture.id,
        )
    )
    created = await repository.create(
        EnvironmentClone(
            name="created-env",
            source_environment_id=source_environment.id,
            source_environment_name=source_environment.name,
            environment_backup_id=capture.id,
            created_environment_id=created_environment.id,
        )
    )
    session.expunge_all()

    fetched = await repository.get(created.id)

    assert fetched is not None
    # Touching these on a freshly loaded row would emit lazy IO (and raise
    # MissingGreenlet in the async resolvers) if they were not eager-loaded.
    assert fetched.source_environment is not None
    assert fetched.source_environment.name == "source-env"
    assert fetched.created_environment is not None
    assert fetched.created_environment.name == "created-env"
    assert fetched.environment_backup is not None
    assert [b.name for b in fetched.environment_backup.backups] == [
        "clone-capture-constituent"
    ]


@pytest.mark.asyncio
async def test_json_columns_and_nullable_links_default_to_none(
    repository: SQLModelEnvironmentCloneRepository,
    source_environment: Environment,
) -> None:
    """A clone registered before its capture exists carries nothing but intent."""
    created = await repository.create(
        EnvironmentClone(
            name="pending-clone",
            source_environment_id=source_environment.id,
            source_environment_name=source_environment.name,
        )
    )

    fetched = await repository.get(created.id)

    assert fetched is not None
    assert fetched.environment_backup_id is None
    assert fetched.created_environment_id is None
    assert fetched.requested_deployment_ids is None
    assert fetched.config_override is None
    assert fetched.cleared_config_fields is None
    assert fetched.deployment_results is None
    assert fetched.clone_errors is None
    assert fetched.created_by_user_id is None


@pytest.mark.asyncio
async def test_name_is_not_unique_so_a_discarded_clone_can_be_retried(
    repository: SQLModelEnvironmentCloneRepository,
    source_environment: Environment,
) -> None:
    """SC-005: a failed clone must not block re-cloning under the same name."""
    for _ in range(2):
        await repository.create(
            EnvironmentClone(
                name="same-target-name",
                source_environment_id=source_environment.id,
                source_environment_name=source_environment.name,
            )
        )

    clones = await repository.get_by_source_environment_id(source_environment.id)

    assert [clone.name for clone in clones] == ["same-target-name"] * 2


@pytest.mark.asyncio
async def test_provenance_survives_a_nulled_source_and_created_environment(
    session: AsyncSession,
    repository: SQLModelEnvironmentCloneRepository,
    source_environment: Environment,
    created_environment: Environment,
) -> None:
    """Both environment links are nullable; the record stays readable."""
    created = await repository.create(
        EnvironmentClone(
            name="created-env",
            source_environment_id=source_environment.id,
            source_environment_name=source_environment.name,
            created_environment_id=created_environment.id,
        )
    )
    created.source_environment_id = None
    created.created_environment_id = None
    await repository.save(created)
    session.expunge_all()

    fetched = await repository.get(created.id)

    assert fetched is not None
    assert fetched.source_environment_id is None
    assert fetched.source_environment is None
    assert fetched.created_environment_id is None
    assert fetched.source_environment_name == "source-env"


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_persists_an_updated_attribution_list(
    session: AsyncSession,
    repository: SQLModelEnvironmentCloneRepository,
    source_environment: Environment,
) -> None:
    deployment_id = uuid4()
    created = await repository.create(
        EnvironmentClone(
            name="created-env",
            source_environment_id=source_environment.id,
            source_environment_name=source_environment.name,
            deployment_results=[_result(deployment_id, "pending", None)],
        )
    )
    restore_id = uuid4()

    created.deployment_results = [_result(deployment_id, "cloned", restore_id)]
    await repository.save(created)
    session.expunge_all()

    fetched = await repository.get(created.id)
    assert fetched is not None
    assert fetched.deployment_results == [_result(deployment_id, "cloned", restore_id)]


@pytest.mark.asyncio
async def test_save_accepts_a_detached_clone(
    session: AsyncSession,
    repository: SQLModelEnvironmentCloneRepository,
    source_environment: Environment,
) -> None:
    """The flow re-reads its row between steps, so ``save`` merges."""
    created = await repository.create(
        EnvironmentClone(
            name="created-env",
            source_environment_id=source_environment.id,
            source_environment_name=source_environment.name,
        )
    )
    session.expunge_all()

    created.clone_errors = [
        {
            "step": "created_environment_deleted",
            "error": "discarded by operator",
            "fatal": True,
        }
    ]
    merged = await repository.save(created)
    session.expunge_all()

    assert merged.clone_errors == created.clone_errors
    fetched = await repository.get(created.id)
    assert fetched is not None
    assert fetched.clone_errors == [
        {
            "step": "created_environment_deleted",
            "error": "discarded by operator",
            "fatal": True,
        }
    ]


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_by_source_environment_id_returns_newest_first(
    session: AsyncSession,
    repository: SQLModelEnvironmentCloneRepository,
    source_environment: Environment,
    created_environment: Environment,
) -> None:
    base = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
    for offset, name in enumerate(["oldest", "middle", "newest"]):
        clone = await repository.create(
            EnvironmentClone(
                name=name,
                source_environment_id=source_environment.id,
                source_environment_name=source_environment.name,
            )
        )
        clone.created_on = base + timedelta(minutes=offset)
        session.add(clone)
    await repository.create(
        EnvironmentClone(
            name="elsewhere",
            source_environment_id=created_environment.id,
            source_environment_name=created_environment.name,
        )
    )
    await session.flush()

    results = await repository.get_by_source_environment_id(source_environment.id)

    assert [clone.name for clone in results] == ["newest", "middle", "oldest"]


@pytest.mark.asyncio
async def test_get_by_source_environment_id_is_empty_for_unknown_environment(
    repository: SQLModelEnvironmentCloneRepository,
) -> None:
    assert await repository.get_by_source_environment_id(uuid4()) == []


@pytest.mark.asyncio
async def test_get_by_created_environment_id_finds_the_clone_that_made_it(
    repository: SQLModelEnvironmentCloneRepository,
    source_environment: Environment,
    created_environment: Environment,
) -> None:
    made_it = await repository.create(
        EnvironmentClone(
            name="created-env",
            source_environment_id=source_environment.id,
            source_environment_name=source_environment.name,
            created_environment_id=created_environment.id,
        )
    )
    await repository.create(
        EnvironmentClone(
            name="never-materialised",
            source_environment_id=source_environment.id,
            source_environment_name=source_environment.name,
        )
    )

    results = await repository.get_by_created_environment_id(created_environment.id)

    assert [clone.id for clone in results] == [made_it.id]


@pytest.mark.asyncio
async def test_get_by_created_environment_id_is_empty_for_unknown_environment(
    repository: SQLModelEnvironmentCloneRepository,
) -> None:
    assert await repository.get_by_created_environment_id(uuid4()) == []


@pytest.mark.asyncio
async def test_get_by_environment_backup_id_finds_the_clones_built_from_a_capture(
    session: AsyncSession,
    repository: SQLModelEnvironmentCloneRepository,
    source_environment: Environment,
    capture: EnvironmentBackup,
    instance: ApplicationInstance,
) -> None:
    """The lookup the FR-008 delete guard and its cascade run on (010 D9).

    Newest-first and eager-loaded like every other read, because the guard
    derives each clone's status — which walks the capture's own constituents —
    before deciding whether the deletion is refused.
    """
    base = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
    session.add(
        Backup(
            name="styrmin-constituent-for-guard",
            status=BackupStatus.IN_PROGRESS,
            instance_id=instance.id,
            environment_backup_id=capture.id,
        )
    )
    for offset, name in enumerate(["older-clone", "newer-clone"]):
        clone = await repository.create(
            EnvironmentClone(
                name=name,
                source_environment_id=source_environment.id,
                source_environment_name=source_environment.name,
                environment_backup_id=capture.id,
            )
        )
        clone.created_on = base + timedelta(minutes=offset)
        session.add(clone)
    await repository.create(
        EnvironmentClone(
            name="not-yet-registered",
            source_environment_id=source_environment.id,
            source_environment_name=source_environment.name,
        )
    )
    await session.flush()

    results = await repository.get_by_environment_backup_id(capture.id)

    assert [clone.name for clone in results] == ["newer-clone", "older-clone"]
    # Eager-loaded two levels deep: the guard reads the capture's constituents
    # off these rows, and a lazy load there raises ``MissingGreenlet``.
    assert [backup.status for backup in results[0].environment_backup.backups] == [
        BackupStatus.IN_PROGRESS
    ]


@pytest.mark.asyncio
async def test_get_by_environment_backup_id_is_empty_for_unknown_capture(
    repository: SQLModelEnvironmentCloneRepository,
) -> None:
    assert await repository.get_by_environment_backup_id(uuid4()) == []


# ---------------------------------------------------------------------------
# Batched restore fetch
# ---------------------------------------------------------------------------


def _count_queries(session: AsyncSession, sink: list[Any]) -> None:
    """Record every statement the session executes into ``sink``."""
    original = session.exec

    async def counting_exec(statement: Any, *args: Any, **kwargs: Any) -> Any:
        sink.append(statement)
        return await original(statement, *args, **kwargs)

    session.exec = counting_exec  # type: ignore[method-assign]


@pytest.mark.asyncio
async def test_get_referenced_restores_uses_one_in_query_for_a_batch(
    session: AsyncSession,
    repository: SQLModelEnvironmentCloneRepository,
    source_environment: Environment,
    capture: EnvironmentBackup,
    instance: ApplicationInstance,
) -> None:
    restores = [
        await _add_restore(
            session, instance, capture, RestoreStatus.COMPLETED, f"restore-{index}"
        )
        for index in range(3)
    ]
    clones = [
        await repository.create(
            EnvironmentClone(
                name=f"clone-{index}",
                source_environment_id=source_environment.id,
                source_environment_name=source_environment.name,
                deployment_results=[
                    _result(uuid4(), "cloned", restore.id),
                    _result(uuid4(), "skipped", None),
                ],
            )
        )
        for index, restore in enumerate(restores)
    ]
    statements: list[Any] = []
    _count_queries(session, statements)

    fetched = await repository.get_referenced_restores(clones)

    assert set(fetched) == {restore.id for restore in restores}
    assert all(isinstance(row, Restore) for row in fetched.values())
    assert len(statements) == 1
    assert " IN " in str(statements[0]).upper()


@pytest.mark.asyncio
async def test_get_referenced_restores_omits_ids_with_no_row(
    repository: SQLModelEnvironmentCloneRepository,
    source_environment: Environment,
) -> None:
    """A restore cascaded away with its backup is simply absent (not an error)."""
    gone = uuid4()
    clone = await repository.create(
        EnvironmentClone(
            name="clone-with-vanished-restore",
            source_environment_id=source_environment.id,
            source_environment_name=source_environment.name,
            deployment_results=[_result(uuid4(), "cloned", gone)],
        )
    )

    assert await repository.get_referenced_restores([clone]) == {}


@pytest.mark.asyncio
async def test_get_referenced_restores_issues_no_query_without_ids(
    session: AsyncSession,
    repository: SQLModelEnvironmentCloneRepository,
    source_environment: Environment,
) -> None:
    clone = await repository.create(
        EnvironmentClone(
            name="all-skipped",
            source_environment_id=source_environment.id,
            source_environment_name=source_environment.name,
            deployment_results=[_result(uuid4(), "skipped", None)],
        )
    )
    statements: list[Any] = []
    _count_queries(session, statements)

    assert await repository.get_referenced_restores([clone]) == {}
    assert await repository.get_referenced_restores([]) == {}
    assert statements == []


def test_referenced_restore_ids_skips_missing_null_and_malformed_entries() -> None:
    good = uuid4()
    clone = EnvironmentClone(
        name="mixed",
        source_environment_name="source-env",
        deployment_results=[
            {
                "deployment_id": str(uuid4()),
                "outcome": "cloned",
                "restore_id": str(good),
            },
            {"deployment_id": str(uuid4()), "outcome": "skipped", "restore_id": None},
            {"deployment_id": str(uuid4()), "outcome": "pending"},
            {"deployment_id": str(uuid4()), "restore_id": "not-a-uuid"},
            "not-a-dict",
        ],
    )

    assert referenced_restore_ids([clone]) == {good}


def test_referenced_restore_ids_is_empty_without_results() -> None:
    clone = EnvironmentClone(name="bare", source_environment_name="source-env")

    assert referenced_restore_ids([clone]) == set()
