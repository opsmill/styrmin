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

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
)
from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterContext,
    DeploymentContext,
    EnvironmentContext,
    GlobalContext,
    InstanceContext,
)
from styrmin_backend.context.models.helm import ChartInfo, HelmInfo, RepositoryInfo
from styrmin_backend.db.models import (
    ApplicationDriverVersion,
    ApplicationInstance,
    Backup,
    BackupStatus,
    Deployment,
    Environment,
    EnvironmentBackup,
    InstanceStatus,
)
from styrmin_backend.db.utils import get_session
from styrmin_backend.server.app import app

from ._queries import load_query
from .conftest import gql
from .seeds import (
    seed_application_driver_version,
    seed_deployment,
    seed_environment,
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


def _global_context_dict() -> dict:
    """A serialised ``GlobalContext`` for the instance's ``context`` column.

    The deployment repository rehydrates every active instance through
    ``GlobalContext.model_validate``, so a seeded instance without a valid
    context is invisible to the fan-out.
    """
    return GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="prop-env", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(),
            deployment_id=uuid4(),
            namespace="prop-ns",
            release_reference="prop-ref",
        ),
        app=ApplicationContext(
            name="prop-app",
            version="1.0.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=uuid4(),
                    name="prop-chart",
                    version="0.1.0",
                    values_template="",
                ),
                repository=RepositoryInfo(id=uuid4(), url="https://example.com"),
            ),
        ),
    ).model_dump(mode="json")


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
        context=_global_context_dict(),
    )
    session.add(instance)
    await session.commit()
    deployment.active_application_instance_id = instance.id
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
    environment.config = {"dns_zone": "staging.example.com"}
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
    assert persisted.environment_config == {"dns_zone": "staging.example.com"}
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
