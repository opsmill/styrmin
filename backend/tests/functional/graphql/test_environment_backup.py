"""Propagation tests for the environment-backup GraphQL surface.

Constitution §V: every new field, argument, and mutation under
``api/schema/`` must be proven to reach the database (writes) and to project
persisted state (reads). Two things make that non-negotiable here:

* ``EnvironmentBackup.status`` has **no column** — it is recomputed on every
  read from the constituent rows. A test that only asserted on the mutation's
  return value would pass even if the derivation never touched the DB.
* the constituent link is a nullable FK on ``Backup``, so a fan-out that
  created backups but forgot to stamp ``environment_backup_id`` would look
  perfectly healthy in the response payload.

Every assertion therefore reads back through a **second session bound to the
same engine** (``fresh_client``), i.e. a unit of work with its own identity
map, so the values must have survived a real round-trip.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    ApplicationDriverVersion,
    ApplicationInstance,
    Backup,
    BackupStatus,
    Deployment,
    Environment,
    EnvironmentBackup,
    EnvironmentRestore,
    InstanceStatus,
    Restore,
    RestoreStatus,
    Role,
)
from styrmin_backend.db.utils import get_session
from styrmin_backend.server.app import app
from styrmin_backend.services.auth.session import create_session

from ._queries import load_query
from .conftest import gql
from .seeds import (
    global_context_dict,
    seed_application_driver_version,
    seed_deployment,
    seed_environment,
    seed_user,
)


@pytest.fixture(name="fresh_client")
async def fresh_client_fixture(session: AsyncSession, admin_token: str):
    """Authenticated ASGI client whose resolvers run in a *fresh* session.

    The seeding session and this client's session are two distinct units of
    work over the same in-memory engine, so anything the client reads had to
    be flushed and committed to the database first.
    """
    bind = session.get_bind()
    engine = bind if isinstance(bind, AsyncEngine) else AsyncEngine(bind)
    assert isinstance(engine.sync_engine, Engine)

    async with AsyncSession(engine, expire_on_commit=False) as fresh_session:

        async def get_session_override():
            yield fresh_session

        app.dependency_overrides[get_session] = get_session_override
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {admin_token}"},
        ) as client:
            yield client
        app.dependency_overrides.clear()


@pytest.fixture(name="read_write_client")
async def read_write_client_fixture(session: AsyncSession):
    """Authenticated ASGI client at ``READ_WRITE`` — one rung below ADMIN.

    ``restoreEnvironmentBackup`` reverts ``Environment.config``, so it is
    gated at ``ADMIN`` for parity with ``updateEnvironment`` (research.md D7).
    Proving the gate needs a client that is authenticated but under-privileged.
    """
    user = await seed_user(session, username="alice-rw", role=Role.READ_WRITE)
    _row, token = await create_session(session, user.id)

    async def get_session_override():
        yield session

    app.dependency_overrides[get_session] = get_session_override
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client
    app.dependency_overrides.clear()


async def seed_running_deployment(
    session: AsyncSession,
    *,
    environment: Environment,
    adv: ApplicationDriverVersion,
    name: str,
    internal: bool = False,
    config: dict | None = None,
    parameters: dict | None = None,
) -> tuple[Deployment, ApplicationInstance]:
    """Seed a deployment wired to an active application instance."""
    deployment = await seed_deployment(
        session, environment=environment, adv=adv, name=name, internal=internal
    )
    instance = ApplicationInstance(
        name=f"instance-{uuid4().hex[:8]}",
        application_version=deployment.application_version,
        status=InstanceStatus.RUNNING,
        deployment_id=deployment.id,
        application_driver_version_id=deployment.application_driver_version_id,
        context=global_context_dict(),
        sequence=1,
    )
    session.add(instance)
    await session.commit()
    deployment.active_application_instance_id = instance.id
    deployment.last_instance_sequence = instance.sequence
    if config is not None:
        deployment.config = config
    if parameters is not None:
        deployment.parameters = parameters
    session.add(deployment)
    await session.commit()
    return deployment, instance


# ---------------------------------------------------------------------------
# createEnvironmentBackup — write propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_environment_backup_persists_parent_snapshots_and_links(
    fresh_client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """The mutation's capture and constituent links must reach the database."""
    environment = await seed_environment(session)
    environment.config = {"fqdn_suffix": "staging.example.com"}
    session.add(environment)
    await session.commit()
    adv = await seed_application_driver_version(
        session, driver_name="infrahub-driver", version="1.2.0", content_hash="f" * 64
    )
    deployment_a, instance_a = await seed_running_deployment(
        session,
        environment=environment,
        adv=adv,
        name="infrahub",
        config={"replicas": 2},
        parameters={"license": "ent"},
    )
    deployment_b, instance_b = await seed_running_deployment(
        session, environment=environment, adv=adv, name="netbox"
    )

    data = await gql(
        fresh_client,
        "create_environment_backup",
        {"environmentId": str(environment.id), "name": "pre-upgrade"},
    )
    payload = data["createEnvironmentBackup"]

    # --- The parent row reached the database ---------------------------
    persisted = await session.get(EnvironmentBackup, UUID(payload["id"]))
    assert persisted is not None
    assert persisted.name == "pre-upgrade"
    assert persisted.environment_id == environment.id
    assert persisted.environment_config == {"fqdn_suffix": "staging.example.com"}
    assert persisted.constituent_errors is None

    # --- The captured declared state reached the database (FR-002/FR-003)
    assert persisted.deployment_snapshots is not None
    snapshots = {raw["deployment_name"]: raw for raw in persisted.deployment_snapshots}
    assert set(snapshots) == {"infrahub", "netbox"}
    assert snapshots["infrahub"]["deployment_id"] == str(deployment_a.id)
    assert snapshots["infrahub"]["instance_id"] == str(instance_a.id)
    assert snapshots["infrahub"]["driver_name"] == "infrahub-driver"
    assert snapshots["infrahub"]["driver_version"] == "1.2.0"
    assert snapshots["infrahub"]["driver_fingerprint"] == "f" * 64
    assert snapshots["infrahub"]["config"] == {"replicas": 2}
    assert snapshots["infrahub"]["parameters"] == {"license": "ent"}
    assert snapshots["netbox"]["deployment_id"] == str(deployment_b.id)

    # --- The constituent FK reached the database (FR-001) --------------
    result = await session.exec(
        select(Backup).where(Backup.environment_backup_id == persisted.id)
    )
    constituents = list(result.all())
    assert {backup.instance_id for backup in constituents} == {
        instance_a.id,
        instance_b.id,
    }
    assert all(backup.status == BackupStatus.PENDING for backup in constituents)

    # --- The response projects the same state --------------------------
    assert payload["status"] == "PENDING"
    assert payload["environment"]["id"] == str(environment.id)
    assert {c["deploymentName"] for c in payload["constituents"]} == {
        "infrahub",
        "netbox",
    }
    assert all(c["error"] is None for c in payload["constituents"])
    assert all(c["backup"] is not None for c in payload["constituents"])


@pytest.mark.asyncio
async def test_create_environment_backup_excludes_internal_and_instanceless(
    fresh_client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """FR-001: only non-internal deployments with an active instance qualify."""
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session)
    await seed_running_deployment(
        session, environment=environment, adv=adv, name="eligible"
    )
    await seed_running_deployment(
        session, environment=environment, adv=adv, name="ingress", internal=True
    )
    # No active instance: seeded but never deployed.
    await seed_deployment(
        session, environment=environment, adv=adv, name="never-deployed"
    )

    data = await gql(
        fresh_client,
        "create_environment_backup",
        {"environmentId": str(environment.id), "name": None},
    )
    payload = data["createEnvironmentBackup"]

    persisted = await session.get(EnvironmentBackup, UUID(payload["id"]))
    assert persisted is not None
    assert persisted.deployment_snapshots is not None
    assert [raw["deployment_name"] for raw in persisted.deployment_snapshots] == [
        "eligible"
    ]
    result = await session.exec(
        select(Backup).where(Backup.environment_backup_id == persisted.id)
    )
    assert len(list(result.all())) == 1
    # The default name is derived from the persisted id.
    assert persisted.name == f"styrmin-envbackup-{persisted.id}"


@pytest.mark.asyncio
async def test_create_environment_backup_records_a_conflicting_constituent(
    fresh_client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """FR-005: a busy instance is an attributable error, and peers proceed."""
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session)
    _busy, busy_instance = await seed_running_deployment(
        session, environment=environment, adv=adv, name="busy-app"
    )
    _healthy, healthy_instance = await seed_running_deployment(
        session, environment=environment, adv=adv, name="healthy-app"
    )
    in_flight = Backup(
        name="pre-existing",
        status=BackupStatus.IN_PROGRESS,
        instance_id=busy_instance.id,
    )
    session.add(in_flight)
    await session.commit()

    data = await gql(
        fresh_client,
        "create_environment_backup",
        {"environmentId": str(environment.id), "name": "with-conflict"},
    )
    payload = data["createEnvironmentBackup"]

    persisted = await session.get(EnvironmentBackup, UUID(payload["id"]))
    assert persisted is not None
    assert persisted.constituent_errors is not None
    assert [raw["deployment_name"] for raw in persisted.constituent_errors] == [
        "busy-app"
    ]
    assert str(in_flight.id) in persisted.constituent_errors[0]["error"]

    result = await session.exec(
        select(Backup).where(Backup.environment_backup_id == persisted.id)
    )
    constituents = list(result.all())
    assert [backup.instance_id for backup in constituents] == [healthy_instance.id]

    by_name = {c["deploymentName"]: c for c in payload["constituents"]}
    assert by_name["busy-app"]["backup"] is None
    assert str(in_flight.id) in by_name["busy-app"]["error"]
    assert by_name["healthy-app"]["backup"] is not None
    assert by_name["healthy-app"]["error"] is None


@pytest.mark.asyncio
async def test_create_environment_backup_on_empty_environment_is_completed(
    fresh_client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """FR-011: a config-only snapshot reports COMPLETED immediately."""
    environment = await seed_environment(session)

    data = await gql(
        fresh_client,
        "create_environment_backup",
        {"environmentId": str(environment.id), "name": "config-only"},
    )
    payload = data["createEnvironmentBackup"]

    assert payload["status"] == "COMPLETED"
    assert payload["deploymentSnapshots"] == []
    assert payload["constituents"] == []

    persisted = await session.get(EnvironmentBackup, UUID(payload["id"]))
    assert persisted is not None
    assert persisted.deployment_snapshots is None


@pytest.mark.asyncio
async def test_create_environment_backup_rejects_a_concurrent_operation(
    fresh_client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """FR-009: the second environment-level operation gets ALREADY_IN_PROGRESS."""
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session)
    _deployment, instance = await seed_running_deployment(
        session, environment=environment, adv=adv, name="infrahub"
    )
    in_flight_parent = EnvironmentBackup(
        name="in-flight", environment_id=environment.id
    )
    session.add(in_flight_parent)
    await session.commit()
    session.add(
        Backup(
            name="in-flight-constituent",
            status=BackupStatus.PENDING,
            instance_id=instance.id,
            environment_backup_id=in_flight_parent.id,
        )
    )
    await session.commit()

    # ``gql`` asserts a clean payload; this path deliberately inspects errors.
    response = await fresh_client.post(
        "/graphql",
        json={
            "query": load_query("create_environment_backup"),
            "variables": {"environmentId": str(environment.id), "name": "second"},
        },
    )

    assert response.status_code == 200
    errors = response.json()["errors"]
    assert errors[0]["extensions"]["code"] == "ALREADY_IN_PROGRESS"
    assert errors[0]["extensions"]["operation_kind"] == "environment_backup"

    # The in-flight operation is untouched — no second parent was written.
    result = await session.exec(
        select(EnvironmentBackup).where(
            EnvironmentBackup.environment_id == environment.id
        )
    )
    assert [parent.id for parent in result.all()] == [in_flight_parent.id]


# ---------------------------------------------------------------------------
# environmentBackup / environmentBackups — read projection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("child_statuses", "error_count", "expected"),
    [
        ([BackupStatus.COMPLETED, BackupStatus.COMPLETED], 0, "COMPLETED"),
        ([BackupStatus.COMPLETED, BackupStatus.FAILED], 0, "PARTIAL"),
        ([BackupStatus.COMPLETED], 1, "PARTIAL"),
        ([BackupStatus.FAILED, BackupStatus.FAILED], 0, "FAILED"),
        ([BackupStatus.PENDING, BackupStatus.PENDING], 0, "PENDING"),
        ([BackupStatus.COMPLETED, BackupStatus.IN_PROGRESS], 0, "IN_PROGRESS"),
    ],
)
async def test_environment_backup_projects_derived_status_from_the_database(
    fresh_client: AsyncClient,
    session: AsyncSession,
    child_statuses: list[BackupStatus],
    error_count: int,
    expected: str,
) -> None:
    """SC-003: the resolver derives the parent status from the persisted rows."""
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session)
    parent = EnvironmentBackup(
        name=f"seeded-{uuid4().hex[:8]}",
        environment_id=environment.id,
        constituent_errors=[
            {
                "deployment_id": str(uuid4()),
                "deployment_name": f"errored-{index}",
                "error": "backup already in progress",
            }
            for index in range(error_count)
        ]
        or None,
    )
    session.add(parent)
    await session.commit()
    for index, status in enumerate(child_statuses):
        _deployment, instance = await seed_running_deployment(
            session, environment=environment, adv=adv, name=f"app-{index}"
        )
        session.add(
            Backup(
                name=f"constituent-{index}-{uuid4().hex[:6]}",
                status=status,
                instance_id=instance.id,
                environment_backup_id=parent.id,
            )
        )
    await session.commit()

    data = await gql(
        fresh_client,
        "get_environment_backup",
        {"environmentBackupId": str(parent.id)},
    )

    assert data["environmentBackup"]["status"] == expected


@pytest.mark.asyncio
async def test_environment_backup_projects_per_constituent_outcomes(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """Each snapshot entry resolves to its backup, its error, or a gap (US3)."""
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session)
    _live, live_instance = await seed_running_deployment(
        session, environment=environment, adv=adv, name="live-app"
    )
    _gap, gap_instance = await seed_running_deployment(
        session, environment=environment, adv=adv, name="deleted-constituent-app"
    )
    errored_deployment_id = uuid4()

    def _snapshot(name: str, deployment_id: UUID, instance_id: UUID) -> dict:
        return {
            "deployment_id": str(deployment_id),
            "deployment_name": name,
            "instance_id": str(instance_id),
            "driver_name": "seed-driver",
            "driver_version": "1.0.0",
            "driver_fingerprint": None,
            "application_version": "1.0.0",
            "config": None,
            "parameters": None,
        }

    parent = EnvironmentBackup(
        name="mixed-outcomes",
        environment_id=environment.id,
        deployment_snapshots=[
            _snapshot("live-app", _live.id, live_instance.id),
            _snapshot("busy-app", errored_deployment_id, uuid4()),
            _snapshot("deleted-constituent-app", _gap.id, gap_instance.id),
        ],
        constituent_errors=[
            {
                "deployment_id": str(errored_deployment_id),
                "deployment_name": "busy-app",
                "error": "Backup already in progress: 1234",
            }
        ],
    )
    session.add(parent)
    await session.commit()
    live_backup = Backup(
        name="live-constituent",
        status=BackupStatus.COMPLETED,
        instance_id=live_instance.id,
        environment_backup_id=parent.id,
    )
    session.add(live_backup)
    await session.commit()

    data = await gql(
        fresh_client,
        "get_environment_backup",
        {"environmentBackupId": str(parent.id)},
    )
    row = data["environmentBackup"]
    by_name = {c["deploymentName"]: c for c in row["constituents"]}

    # One completed constituent + one recorded error -> PARTIAL.
    assert row["status"] == "PARTIAL"
    assert by_name["live-app"]["backup"]["id"] == str(live_backup.id)
    assert by_name["live-app"]["error"] is None
    assert by_name["busy-app"]["backup"] is None
    assert by_name["busy-app"]["error"] == "Backup already in progress: 1234"
    # The individually deleted constituent leaves a visible gap.
    assert by_name["deleted-constituent-app"]["backup"] is None
    assert by_name["deleted-constituent-app"]["error"] is None
    # The captured declared state still projects for the gap entry.
    assert {s["deploymentName"] for s in row["deploymentSnapshots"]} == set(by_name)


@pytest.mark.asyncio
async def test_environment_backups_lists_newest_first_and_scopes_by_environment(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """FR-013: listing is per-environment and ordered newest first."""
    environment = await seed_environment(session, name="target-env")
    other = await seed_environment(session, name="other-env")
    for name in ("oldest", "middle", "newest"):
        session.add(EnvironmentBackup(name=name, environment_id=environment.id))
        await session.commit()
    session.add(EnvironmentBackup(name="elsewhere", environment_id=other.id))
    await session.commit()

    data = await gql(
        fresh_client,
        "list_environment_backups",
        {"environmentId": str(environment.id)},
    )

    names = [row["name"] for row in data["environmentBackups"]]
    assert set(names) == {"oldest", "middle", "newest"}
    assert "elsewhere" not in names
    # Every listed snapshot is config-only, hence COMPLETED (FR-011).
    assert {row["status"] for row in data["environmentBackups"]} == {"COMPLETED"}


# ---------------------------------------------------------------------------
# restoreEnvironmentBackup — write propagation
# ---------------------------------------------------------------------------


def _snapshot_payload(*, deployment: Deployment, instance: ApplicationInstance) -> dict:
    """The JSON snapshot entry the backup fan-out would have captured."""
    return {
        "deployment_id": str(deployment.id),
        "deployment_name": deployment.name,
        "instance_id": str(instance.id),
        "driver_name": "seed-driver",
        "driver_version": "1.0.0",
        "driver_fingerprint": None,
        "application_version": deployment.application_version,
        "config": deployment.config,
        "parameters": deployment.parameters or None,
    }


async def seed_environment_backup(
    session: AsyncSession,
    *,
    environment: Environment,
    entries: list[tuple[Deployment, ApplicationInstance, BackupStatus | None]],
    environment_config: dict | None = None,
    constituent_errors: list[dict] | None = None,
    name: str | None = None,
) -> EnvironmentBackup:
    """Seed a snapshot plus one constituent per entry.

    A ``None`` status means "the constituent row was deleted after the
    backup" — the snapshot entry survives without a linked ``Backup``.
    """
    parent = EnvironmentBackup(
        name=name or f"snapshot-{uuid4().hex[:8]}",
        environment_id=environment.id,
        environment_config=environment_config,
        deployment_snapshots=[
            _snapshot_payload(deployment=deployment, instance=instance)
            for deployment, instance, _ in entries
        ]
        or None,
        constituent_errors=constituent_errors,
    )
    session.add(parent)
    await session.commit()
    for _deployment, instance, status in entries:
        if status is None:
            continue
        session.add(
            Backup(
                name=f"constituent-{uuid4().hex[:8]}",
                status=status,
                instance_id=instance.id,
                environment_backup_id=parent.id,
            )
        )
    await session.commit()
    return parent


@pytest.fixture(name="no_config_fanout")
def no_config_fanout_fixture(mocker):
    """Patch the fan-out's redeploy at its call site.

    The fan-out drives the full reconciliation chain
    (``generate_instance_from_deployment`` + ``apply_state``), which needs a
    renderable driver graph these seeds deliberately do not build. The
    behaviour under test here is what reaches the *database*, not what the
    reconciler does with it — that is covered by the env-config fan-out tests.
    """
    return mocker.patch(
        "styrmin_backend.services.cluster_config_fanout.redeploy_for_environment_update",
        autospec=True,
    )


@pytest.mark.asyncio
async def test_restore_environment_backup_persists_record_links_and_config_revert(
    fresh_client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    no_config_fanout,
) -> None:
    """FR-006/SC-005: the revert and the constituent links must reach the DB."""
    environment = await seed_environment(session)
    environment.config = {"fqdn_suffix": "drifted.example.com"}
    session.add(environment)
    await session.commit()
    adv = await seed_application_driver_version(session)
    deployment_a, instance_a = await seed_running_deployment(
        session, environment=environment, adv=adv, name="infrahub"
    )
    deployment_b, instance_b = await seed_running_deployment(
        session, environment=environment, adv=adv, name="netbox"
    )
    parent = await seed_environment_backup(
        session,
        environment=environment,
        entries=[
            (deployment_a, instance_a, BackupStatus.COMPLETED),
            (deployment_b, instance_b, BackupStatus.COMPLETED),
        ],
        environment_config={"fqdn_suffix": "captured.example.com"},
    )

    data = await gql(
        fresh_client,
        "restore_environment_backup",
        {"environmentBackupId": str(parent.id)},
    )
    payload = data["restoreEnvironmentBackup"]

    # --- The parent restore row reached the database -------------------
    persisted = await session.get(EnvironmentRestore, UUID(payload["id"]))
    assert persisted is not None
    assert persisted.environment_backup_id == parent.id
    assert persisted.skipped_constituents is None

    # --- The config revert reached the database (SC-005) ---------------
    await session.refresh(environment)
    assert environment.config == {"fqdn_suffix": "captured.example.com"}

    # --- The constituent FK reached the database -----------------------
    result = await session.exec(
        select(Restore).where(Restore.environment_restore_id == persisted.id)
    )
    constituents = list(result.all())
    assert {restore.target_namespace for restore in constituents} == {
        f"styrmin-{deployment_a.id}",
        f"styrmin-{deployment_b.id}",
    }
    assert all(restore.status == RestoreStatus.PENDING for restore in constituents)
    # Both deployments are RESTORING when the config fan-out reads them (#467).
    no_config_fanout.assert_not_awaited()

    # --- The response projects the same state --------------------------
    assert payload["status"] == "PENDING"
    assert payload["environmentBackup"]["id"] == str(parent.id)
    assert payload["skippedConstituents"] == []
    assert {restore["id"] for restore in payload["restores"]} == {
        str(restore.id) for restore in constituents
    }


@pytest.mark.asyncio
async def test_restore_environment_backup_persists_every_skip_reason(
    fresh_client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    no_config_fanout,
) -> None:
    """FR-007/SC-004: every non-restored constituent is persisted with a reason."""
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session)
    usable, usable_instance = await seed_running_deployment(
        session, environment=environment, adv=adv, name="usable"
    )
    failed, failed_instance = await seed_running_deployment(
        session, environment=environment, adv=adv, name="failed-backup"
    )
    gap, gap_instance = await seed_running_deployment(
        session, environment=environment, adv=adv, name="deleted-backup"
    )
    errored, errored_instance = await seed_running_deployment(
        session, environment=environment, adv=adv, name="failed-at-creation"
    )
    parent = await seed_environment_backup(
        session,
        environment=environment,
        entries=[
            (usable, usable_instance, BackupStatus.COMPLETED),
            (failed, failed_instance, BackupStatus.FAILED),
            (gap, gap_instance, None),
            (errored, errored_instance, None),
        ],
        constituent_errors=[
            {
                "deployment_id": str(errored.id),
                "deployment_name": "failed-at-creation",
                "error": "backup already in progress",
            }
        ],
    )

    data = await gql(
        fresh_client,
        "restore_environment_backup",
        {"environmentBackupId": str(parent.id)},
    )
    payload = data["restoreEnvironmentBackup"]

    persisted = await session.get(EnvironmentRestore, UUID(payload["id"]))
    assert persisted is not None
    assert persisted.skipped_constituents is not None
    assert {
        raw["deployment_name"]: raw["reason"] for raw in persisted.skipped_constituents
    } == {
        "failed-backup": "backup not completed",
        "deleted-backup": "backup deleted",
        "failed-at-creation": "backup failed at creation",
    }
    # Exactly one constituent restore was created — the usable one.
    result = await session.exec(
        select(Restore).where(Restore.environment_restore_id == persisted.id)
    )
    assert [restore.target_namespace for restore in result.all()] == [
        f"styrmin-{usable.id}"
    ]
    # One PENDING restore alongside three skips derives as IN_PROGRESS.
    assert payload["status"] == "IN_PROGRESS"
    assert {skip["deploymentName"] for skip in payload["skippedConstituents"]} == {
        "failed-backup",
        "deleted-backup",
        "failed-at-creation",
    }


@pytest.mark.asyncio
async def test_restore_environment_backup_does_not_change_the_deployment_count(
    fresh_client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    no_config_fanout,
) -> None:
    """FR-008: restore never creates or deletes a deployment."""
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session)
    survivor, survivor_instance = await seed_running_deployment(
        session, environment=environment, adv=adv, name="survivor"
    )
    departed, departed_instance = await seed_running_deployment(
        session, environment=environment, adv=adv, name="departed"
    )
    parent = await seed_environment_backup(
        session,
        environment=environment,
        entries=[
            (survivor, survivor_instance, BackupStatus.COMPLETED),
            (departed, departed_instance, BackupStatus.COMPLETED),
        ],
    )
    # Tombstone one deployment after the snapshot was taken.
    departed.deleted_at = datetime(2026, 8, 5, tzinfo=timezone.utc)
    session.add(departed)
    await session.commit()
    before = len(
        list(
            (
                await session.exec(
                    select(Deployment).where(
                        Deployment.environment_id == environment.id
                    )
                )
            ).all()
        )
    )

    data = await gql(
        fresh_client,
        "restore_environment_backup",
        {"environmentBackupId": str(parent.id)},
    )
    payload = data["restoreEnvironmentBackup"]

    after = list(
        (
            await session.exec(
                select(Deployment).where(Deployment.environment_id == environment.id)
            )
        ).all()
    )
    assert len(after) == before
    assert [skip["reason"] for skip in payload["skippedConstituents"]] == [
        "deployment no longer exists"
    ]


@pytest.mark.asyncio
async def test_restore_environment_backup_rejects_a_non_restorable_snapshot(
    fresh_client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    no_config_fanout,
) -> None:
    """FR-006: a FAILED snapshot is refused with OPERATION_DENIED."""
    environment = await seed_environment(session)
    environment.config = {"fqdn_suffix": "drifted.example.com"}
    session.add(environment)
    await session.commit()
    adv = await seed_application_driver_version(session)
    deployment, instance = await seed_running_deployment(
        session, environment=environment, adv=adv, name="infrahub"
    )
    parent = await seed_environment_backup(
        session,
        environment=environment,
        entries=[(deployment, instance, BackupStatus.FAILED)],
        environment_config={"fqdn_suffix": "captured.example.com"},
    )

    response = await fresh_client.post(
        "/graphql",
        json={
            "query": load_query("restore_environment_backup"),
            "variables": {"environmentBackupId": str(parent.id)},
        },
    )

    assert response.status_code == 200
    errors = response.json()["errors"]
    assert errors[0]["extensions"]["code"] == "OPERATION_DENIED"
    # Nothing was written and the drifted config stands.
    result = await session.exec(
        select(EnvironmentRestore).where(
            EnvironmentRestore.environment_backup_id == parent.id
        )
    )
    assert list(result.all()) == []
    await session.refresh(environment)
    assert environment.config == {"fqdn_suffix": "drifted.example.com"}


@pytest.mark.asyncio
async def test_restore_environment_backup_rejects_a_concurrent_operation(
    fresh_client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    no_config_fanout,
) -> None:
    """FR-009: the D6 guard reaches the restore entry point."""
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session)
    deployment, instance = await seed_running_deployment(
        session, environment=environment, adv=adv, name="infrahub"
    )
    parent = await seed_environment_backup(
        session,
        environment=environment,
        entries=[(deployment, instance, BackupStatus.COMPLETED)],
    )
    constituent = (
        await session.exec(
            select(Backup).where(Backup.environment_backup_id == parent.id)
        )
    ).first()
    assert constituent is not None
    in_flight = EnvironmentRestore(environment_backup_id=parent.id)
    session.add(in_flight)
    await session.commit()
    session.add(
        Restore(
            name=f"in-flight-{uuid4().hex[:8]}",
            status=RestoreStatus.IN_PROGRESS,
            target_namespace=f"styrmin-{deployment.id}",
            backup_id=constituent.id,
            environment_restore_id=in_flight.id,
        )
    )
    await session.commit()

    response = await fresh_client.post(
        "/graphql",
        json={
            "query": load_query("restore_environment_backup"),
            "variables": {"environmentBackupId": str(parent.id)},
        },
    )

    assert response.status_code == 200
    errors = response.json()["errors"]
    assert errors[0]["extensions"]["code"] == "ALREADY_IN_PROGRESS"
    assert errors[0]["extensions"]["operation_kind"] == "environment_restore"
    result = await session.exec(
        select(EnvironmentRestore).where(
            EnvironmentRestore.environment_backup_id == parent.id
        )
    )
    assert [row.id for row in result.all()] == [in_flight.id]


@pytest.mark.asyncio
async def test_restore_environment_backup_requires_admin(
    session: AsyncSession, read_write_client: AsyncClient
) -> None:
    """research.md D7: reverting env config is an ADMIN-only privilege."""
    environment = await seed_environment(session)
    parent = await seed_environment_backup(session, environment=environment, entries=[])

    response = await read_write_client.post(
        "/graphql",
        json={
            "query": load_query("restore_environment_backup"),
            "variables": {"environmentBackupId": str(parent.id)},
        },
    )

    assert response.status_code == 200
    errors = response.json()["errors"]
    assert errors[0]["extensions"]["code"] == "FORBIDDEN"


# ---------------------------------------------------------------------------
# environmentRestore / environmentRestores — read projection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("child_statuses", "skip_count", "expected"),
    [
        ([RestoreStatus.COMPLETED, RestoreStatus.COMPLETED], 0, "COMPLETED"),
        ([RestoreStatus.COMPLETED], 1, "PARTIAL"),
        ([RestoreStatus.COMPLETED, RestoreStatus.FAILED], 0, "PARTIAL"),
        ([RestoreStatus.FAILED], 0, "FAILED"),
        ([], 2, "FAILED"),
        ([RestoreStatus.PENDING], 0, "PENDING"),
        ([RestoreStatus.COMPLETED, RestoreStatus.IN_PROGRESS], 0, "IN_PROGRESS"),
        ([], 0, "COMPLETED"),
    ],
)
async def test_environment_restore_projects_derived_status_from_the_database(
    fresh_client: AsyncClient,
    session: AsyncSession,
    child_statuses: list[RestoreStatus],
    skip_count: int,
    expected: str,
) -> None:
    """SC-003: the resolver derives the restore status from the persisted rows."""
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session)
    deployment, instance = await seed_running_deployment(
        session, environment=environment, adv=adv, name="infrahub"
    )
    parent = await seed_environment_backup(
        session,
        environment=environment,
        entries=[(deployment, instance, BackupStatus.COMPLETED)],
    )
    constituent = (
        await session.exec(
            select(Backup).where(Backup.environment_backup_id == parent.id)
        )
    ).first()
    assert constituent is not None
    environment_restore = EnvironmentRestore(
        environment_backup_id=parent.id,
        skipped_constituents=[
            {
                "deployment_id": str(uuid4()),
                "deployment_name": f"skipped-{index}",
                "reason": "backup expired",
            }
            for index in range(skip_count)
        ]
        or None,
    )
    session.add(environment_restore)
    await session.commit()
    for index, status in enumerate(child_statuses):
        session.add(
            Restore(
                name=f"restore-{index}-{uuid4().hex[:6]}",
                status=status,
                target_namespace=f"styrmin-{deployment.id}",
                backup_id=constituent.id,
                environment_restore_id=environment_restore.id,
            )
        )
    await session.commit()

    data = await gql(
        fresh_client,
        "get_environment_restore",
        {"environmentRestoreId": str(environment_restore.id)},
    )

    assert data["environmentRestore"]["status"] == expected
    assert len(data["environmentRestore"]["skippedConstituents"]) == skip_count
    assert len(data["environmentRestore"]["restores"]) == len(child_statuses)


@pytest.mark.asyncio
async def test_environment_restores_lists_newest_first_and_scopes_by_snapshot(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """FR-013: listing is per-snapshot and ordered newest first."""
    environment = await seed_environment(session)
    target = await seed_environment_backup(
        session, environment=environment, entries=[], name="target"
    )
    other = await seed_environment_backup(
        session, environment=environment, entries=[], name="other"
    )
    mine = []
    # ``created_on`` is set explicitly: the server default has second-level
    # resolution here, so two rows written back to back would tie and the
    # newest-first assertion below would be vacuous.
    for offset, reason in enumerate(("backup expired", "backup deleted")):
        environment_restore = EnvironmentRestore(
            environment_backup_id=target.id,
            created_on=datetime(2026, 8, 1, tzinfo=timezone.utc)
            + timedelta(hours=offset),
            skipped_constituents=[
                {
                    "deployment_id": str(uuid4()),
                    "deployment_name": "gone-app",
                    "reason": reason,
                }
            ],
        )
        session.add(environment_restore)
        await session.commit()
        mine.append(environment_restore)
    session.add(EnvironmentRestore(environment_backup_id=other.id))
    await session.commit()

    data = await gql(
        fresh_client,
        "list_environment_restores",
        {"environmentBackupId": str(target.id)},
    )

    rows = data["environmentRestores"]
    assert {row["id"] for row in rows} == {str(row.id) for row in mine}
    # Every listed restore skipped everything and restored nothing -> FAILED.
    assert {row["status"] for row in rows} == {"FAILED"}
    assert rows[0]["skippedConstituents"][0]["reason"] == "backup deleted"


# ---------------------------------------------------------------------------
# deleteEnvironmentBackup — cascade propagation (US3 / FR-010, FR-015)
# ---------------------------------------------------------------------------


async def _ids(session: AsyncSession, statement) -> set[UUID]:
    """Read primary keys through the *seeding* session, after ``expire_all()``.

    The mutation ran in a different session, so this one still holds the
    pre-delete objects in its identity map. Expiring first forces a real SELECT
    and makes "the row is gone" mean gone from the database rather than gone
    from the response payload.

    Only ids come back on purpose: an ORM instance handed to a caller *after*
    ``expire_all()`` would re-query the row on first attribute access and raise
    ``ObjectDeletedError`` for exactly the rows these tests expect to be gone.
    Callers therefore capture the ids they care about *before* the mutation and
    compare id sets afterwards.
    """
    session.expire_all()
    return {row.id for row in (await session.exec(statement)).all()}


@pytest.mark.asyncio
async def test_delete_environment_backup_cascades_to_constituents_and_restores(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """FR-010: the parent, its constituents, and their restores all leave the DB."""
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session)
    deployment_a, instance_a = await seed_running_deployment(
        session, environment=environment, adv=adv, name="infrahub"
    )
    deployment_b, instance_b = await seed_running_deployment(
        session, environment=environment, adv=adv, name="netbox"
    )
    parent = await seed_environment_backup(
        session,
        environment=environment,
        entries=[
            (deployment_a, instance_a, BackupStatus.COMPLETED),
            (deployment_b, instance_b, BackupStatus.COMPLETED),
        ],
    )
    parent_id = parent.id
    environment_id = environment.id
    deployment_a_id = deployment_a.id
    deployment_ids = {deployment_a.id, deployment_b.id}
    constituent_ids = await _ids(
        session, select(Backup).where(Backup.environment_backup_id == parent_id)
    )
    assert len(constituent_ids) == 2
    environment_restore = EnvironmentRestore(environment_backup_id=parent_id)
    session.add(environment_restore)
    await session.commit()
    environment_restore_id = environment_restore.id
    for constituent_id in constituent_ids:
        session.add(
            Restore(
                name=f"restore-{uuid4().hex[:8]}",
                status=RestoreStatus.COMPLETED,
                target_namespace=f"styrmin-{deployment_a_id}",
                backup_id=constituent_id,
                environment_restore_id=environment_restore_id,
            )
        )
    await session.commit()

    data = await gql(
        fresh_client,
        "delete_environment_backup",
        {"environmentBackupId": str(parent_id)},
    )

    assert data["deleteEnvironmentBackup"] is True
    # --- Everything the snapshot owned left the database ---------------
    assert (
        await _ids(
            session, select(EnvironmentBackup).where(EnvironmentBackup.id == parent_id)
        )
        == set()
    )
    assert (
        await _ids(
            session,
            select(EnvironmentRestore).where(
                EnvironmentRestore.environment_backup_id == parent_id
            ),
        )
        == set()
    )
    assert (
        await _ids(
            session,
            select(Backup).where(Backup.id.in_(constituent_ids)),  # type: ignore[attr-defined]
        )
        == set()
    )
    assert (
        await _ids(
            session,
            select(Restore).where(
                Restore.environment_restore_id == environment_restore_id
            ),
        )
        == set()
    )
    # --- The deployments themselves are untouched ----------------------
    assert (
        await _ids(
            session,
            select(Deployment).where(Deployment.environment_id == environment_id),
        )
        == deployment_ids
    )


@pytest.mark.asyncio
async def test_delete_environment_backup_spares_sibling_snapshots(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """The cascade is scoped to one snapshot, not to the environment."""
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session)
    deployment, instance = await seed_running_deployment(
        session, environment=environment, adv=adv, name="infrahub"
    )
    doomed = await seed_environment_backup(
        session,
        environment=environment,
        entries=[(deployment, instance, BackupStatus.COMPLETED)],
        name="doomed",
    )
    keeper = await seed_environment_backup(
        session,
        environment=environment,
        entries=[(deployment, instance, BackupStatus.COMPLETED)],
        name="keeper",
    )
    environment_id = environment.id
    doomed_id = doomed.id
    keeper_id = keeper.id
    keeper_constituent_ids = await _ids(
        session, select(Backup).where(Backup.environment_backup_id == keeper_id)
    )

    await gql(
        fresh_client,
        "delete_environment_backup",
        {"environmentBackupId": str(doomed_id)},
    )

    assert await _ids(
        session,
        select(EnvironmentBackup).where(
            EnvironmentBackup.environment_id == environment_id
        ),
    ) == {keeper_id}
    assert (
        await _ids(
            session, select(Backup).where(Backup.environment_backup_id == keeper_id)
        )
        == keeper_constituent_ids
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [BackupStatus.PENDING, BackupStatus.IN_PROGRESS])
async def test_delete_environment_backup_works_while_in_progress(
    fresh_client: AsyncClient, session: AsyncSession, status: BackupStatus
) -> None:
    """FR-010 escape hatch: no status guard, at the API boundary too.

    Read the derived status back through GraphQL first, so the test proves the
    snapshot really was non-terminal at the moment it was deleted rather than
    assuming the seed produced one.
    """
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session)
    deployment, instance = await seed_running_deployment(
        session, environment=environment, adv=adv, name="infrahub"
    )
    parent = await seed_environment_backup(
        session,
        environment=environment,
        entries=[(deployment, instance, status)],
    )
    parent_id = parent.id
    before = await gql(
        fresh_client, "get_environment_backup", {"environmentBackupId": str(parent_id)}
    )
    assert before["environmentBackup"]["status"] in ("PENDING", "IN_PROGRESS")

    data = await gql(
        fresh_client,
        "delete_environment_backup",
        {"environmentBackupId": str(parent_id)},
    )

    assert data["deleteEnvironmentBackup"] is True
    assert (
        await _ids(
            session, select(EnvironmentBackup).where(EnvironmentBackup.id == parent_id)
        )
        == set()
    )
    assert (
        await _ids(
            session, select(Backup).where(Backup.environment_backup_id == parent_id)
        )
        == set()
    )


@pytest.mark.asyncio
async def test_delete_environment_backup_rejects_an_unknown_snapshot(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """A missing snapshot is ``NOT_FOUND``, not a silent success."""
    response = await fresh_client.post(
        "/graphql",
        json={
            "query": load_query("delete_environment_backup"),
            "variables": {"environmentBackupId": str(uuid4())},
        },
    )

    assert response.status_code == 200
    errors = response.json()["errors"]
    assert errors[0]["extensions"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_delete_environment_backup_is_allowed_at_read_write(
    session: AsyncSession, read_write_client: AsyncClient
) -> None:
    """Deleting a snapshot is READ_WRITE — parity with ``deleteBackup``.

    The sibling ``restoreEnvironmentBackup`` is ADMIN because it reverts the
    environment's config; deletion does not, so it must not inherit that gate.
    """
    environment = await seed_environment(session)
    parent = await seed_environment_backup(session, environment=environment, entries=[])
    parent_id = parent.id

    response = await read_write_client.post(
        "/graphql",
        json={
            "query": load_query("delete_environment_backup"),
            "variables": {"environmentBackupId": str(parent_id)},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    assert payload["data"]["deleteEnvironmentBackup"] is True
    assert (
        await _ids(
            session, select(EnvironmentBackup).where(EnvironmentBackup.id == parent_id)
        )
        == set()
    )


@pytest.mark.asyncio
async def test_individually_deleting_a_constituent_leaves_a_visible_gap(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """US3: the parent survives, and the missing child shows as a gap.

    Deleting a constituent through the ordinary per-instance ``deleteBackup``
    must not take the snapshot with it — the entry stays in
    ``deploymentSnapshots`` and resolves to a constituent with neither a
    ``backup`` nor an ``error``.
    """
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session)
    survivor, survivor_instance = await seed_running_deployment(
        session, environment=environment, adv=adv, name="survivor"
    )
    doomed, doomed_instance = await seed_running_deployment(
        session, environment=environment, adv=adv, name="doomed-constituent"
    )
    parent = await seed_environment_backup(
        session,
        environment=environment,
        entries=[
            (survivor, survivor_instance, BackupStatus.COMPLETED),
            (doomed, doomed_instance, BackupStatus.COMPLETED),
        ],
    )
    parent_id = parent.id
    doomed_backup_id = (
        await session.exec(
            select(Backup.id).where(Backup.instance_id == doomed_instance.id)
        )
    ).first()
    assert doomed_backup_id is not None

    await gql(fresh_client, "delete_backup", {"backupId": str(doomed_backup_id)})

    # --- The parent survived the child's deletion ----------------------
    assert await _ids(
        session, select(EnvironmentBackup).where(EnvironmentBackup.id == parent_id)
    ) == {parent_id}
    data = await gql(
        fresh_client, "get_environment_backup", {"environmentBackupId": str(parent_id)}
    )
    row = data["environmentBackup"]
    by_name = {c["deploymentName"]: c for c in row["constituents"]}
    assert set(by_name) == {"survivor", "doomed-constituent"}
    # The gap: captured in the snapshot, but no backup and no error.
    assert by_name["doomed-constituent"]["backup"] is None
    assert by_name["doomed-constituent"]["error"] is None
    assert by_name["survivor"]["backup"] is not None
    # One surviving completed child, no recorded errors -> still COMPLETED.
    assert row["status"] == "COMPLETED"
    assert {s["deploymentName"] for s in row["deploymentSnapshots"]} == set(by_name)


@pytest.mark.asyncio
async def test_delete_environment_cascades_its_environment_backups(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """FR-015: snapshots do not outlive their environment.

    ``environmentbackup.environment_id`` is a non-nullable FK and
    ``Environment.environment_backups`` is an ordinary relationship, so without
    the cascade ``session.delete(environment)`` tries to null the FK out and
    the mutation fails with ``INTERNAL_ERROR`` instead of deleting anything.

    The snapshots here are config-only by necessity, not by preference: a
    constituent backup needs an application instance, which needs a deployment,
    and ``deleteEnvironment`` already refuses an environment that still has
    deployment rows (the same nullify-a-NOT-NULL-FK failure, predating this
    feature). The constituent leg of the cascade is proven at DB level by
    ``test_delete_environment_backup_cascades_to_constituents_and_restores``
    above — ``delete_environment`` reaches it through the very same
    ``delete_environment_backup`` call.
    """
    environment = await seed_environment(session)
    environment_id = environment.id
    parents = [
        await seed_environment_backup(
            session, environment=environment, entries=[], name=f"snapshot-{index}"
        )
        for index in range(2)
    ]
    parent_ids = {parent.id for parent in parents}
    environment_restore = EnvironmentRestore(
        environment_backup_id=parents[0].id,
        skipped_constituents=[
            {
                "deployment_id": str(uuid4()),
                "deployment_name": "gone-app",
                "reason": "deployment no longer exists",
            }
        ],
    )
    session.add(environment_restore)
    await session.commit()
    environment_restore_id = environment_restore.id

    data = await gql(
        fresh_client, "delete_environment", {"environmentId": str(environment_id)}
    )

    assert data["deleteEnvironment"] is not None
    assert (
        await _ids(session, select(Environment).where(Environment.id == environment_id))
        == set()
    )
    assert (
        await _ids(
            session,
            select(EnvironmentBackup).where(EnvironmentBackup.id.in_(parent_ids)),  # type: ignore[attr-defined]
        )
        == set()
    )
    assert (
        await _ids(
            session,
            select(EnvironmentRestore).where(
                EnvironmentRestore.id == environment_restore_id
            ),
        )
        == set()
    )


@pytest.mark.asyncio
async def test_environment_backup_projects_its_restores(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """The snapshot exposes the coordinated restores performed from it."""
    environment = await seed_environment(session)
    parent = await seed_environment_backup(session, environment=environment, entries=[])
    environment_restore = EnvironmentRestore(
        environment_backup_id=parent.id,
        skipped_constituents=[
            {
                "deployment_id": str(uuid4()),
                "deployment_name": "gone-app",
                "reason": "deployment no longer exists",
            }
        ],
    )
    session.add(environment_restore)
    await session.commit()

    data = await gql(
        fresh_client,
        "get_environment_backup",
        {"environmentBackupId": str(parent.id)},
    )

    restores = data["environmentBackup"]["restores"]
    assert [row["id"] for row in restores] == [str(environment_restore.id)]
    assert restores[0]["skippedConstituents"] == [
        {"deploymentName": "gone-app", "reason": "deployment no longer exists"}
    ]
