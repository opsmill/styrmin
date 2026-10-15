"""GraphQL ↔ DB propagation tests for per-component replica overrides (023).

Constitution §V: ``ComponentConfigInput.replicas`` written through ``updateDeployment``,
``deploy`` and ``updateDeploymentVersion(input:)`` reaches
``Deployment.config["components"][name]["replicas"]`` through the real service and repository
layers, and ``Deployment.componentReplicas`` projects the stored state. Invalid writes are
rejected with typed errors before any task or flow run, and the deployment row is unchanged
(SC-003). A driver version's ``replicas`` and ``singleton`` keys give the count when no override
is stored (US2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import yaml
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import SpecPatch
from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
    Component,
    ComponentConfig,
    Deployment,
    Task,
)
from styrmin_backend.services.context import generate_context_from_deployment_id
from styrmin_backend.services.replicas.patch_builder import (
    REPLICA_PATCH_KINDS,
    build_component_replica_patches,
)
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork

from ._queries import load_query
from .conftest import gql
from .seeds import (
    seed_application_driver_version,
    seed_deployment,
    seed_environment,
)

# ``server`` declares nothing, ``worker`` a driver default, ``database`` is a singleton.
DECLARATIONS: dict[str, dict[str, Any]] = {
    "server": {},
    "worker": {"replicas": 2},
    "database": {"singleton": True},
}


def _arm_prefect(prefect_manager_mock: Any) -> None:
    """Give the Prefect manager concrete return values so a successful reconcile dispatch
    does not leak an ``AsyncMock`` into a DB-bound column."""
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())


def _component_config(name: str, replica_keys: dict[str, Any]) -> dict[str, Any]:
    return {
        "identifier": {"label": {"app.kubernetes.io/name": f"{name}-app"}},
        "container": name,
        **replica_keys,
    }


def _add_component_configs(
    session: AsyncSession, adv_id: UUID, declarations: dict[str, dict[str, Any]]
) -> None:
    for name, replica_keys in declarations.items():
        session.add(
            ComponentConfig(
                name=name,
                config=_component_config(name, replica_keys),
                application_driver_version_id=adv_id,
            )
        )


async def _seed_deployment(
    session: AsyncSession,
    declarations: dict[str, dict[str, Any]] = DECLARATIONS,
    config: dict[str, Any] | None = None,
) -> tuple[UUID, str]:
    """Seed a deployment whose driver version declares ``declarations`` and whose Component
    rows mirror them, as ``deploy`` copies them. Return its id and its driver name."""
    adv = await seed_application_driver_version(session)
    _add_component_configs(session, adv.id, declarations)
    await session.commit()
    deployment = await seed_deployment(session, adv=adv)
    for name, replica_keys in declarations.items():
        session.add(
            Component(
                name=name,
                config=_component_config(name, replica_keys),
                enabled=True,
                deployment_id=deployment.id,
            )
        )
    if config is not None:
        deployment.config = config
        session.add(deployment)
    await session.commit()
    driver = await session.get(ApplicationDriver, adv.application_driver_id)
    assert driver is not None
    return deployment.id, driver.name


async def _seed_target_driver_version(
    session: AsyncSession,
    deployment_id: UUID,
    declarations: dict[str, dict[str, Any]],
) -> UUID:
    """Add version ``2.0.0`` of the deployment's driver declaring ``declarations``."""
    deployment = await session.get(Deployment, deployment_id)
    assert deployment is not None
    current = await session.get(
        ApplicationDriverVersion, deployment.application_driver_version_id
    )
    assert current is not None
    driver = await session.get(ApplicationDriver, current.application_driver_id)
    assert driver is not None
    target = await seed_application_driver_version(
        session, driver=driver, version="2.0.0"
    )
    target_id = target.id
    _add_component_configs(session, target_id, declarations)
    await session.commit()
    return target_id


async def _seed_deploy_driver(
    session: AsyncSession, declarations: dict[str, dict[str, Any]] = DECLARATIONS
) -> tuple[str, UUID]:
    """Seed an environment and a driver version declaring ``declarations``; return the driver
    name and the environment id for a ``deploy`` call."""
    environment = await seed_environment(session)
    environment_id = environment.id
    adv = await seed_application_driver_version(session, version="1.0.0")
    _add_component_configs(session, adv.id, declarations)
    await session.commit()
    driver = await session.get(ApplicationDriver, adv.application_driver_id)
    assert driver is not None
    return driver.name, environment_id


def _checked_against(driver_name: str, driver_version: str = "1.0.0") -> str:
    return f"driver {driver_name} version {driver_version} (application version 1.0.0)"


async def _post(
    client: AsyncClient, operation: str, variables: dict[str, Any]
) -> dict[str, Any]:
    response = await client.post(
        "/graphql", json={"query": load_query(operation), "variables": variables}
    )
    assert response.status_code == 200
    return response.json()


async def _post_update(
    client: AsyncClient, deployment_id: UUID, components: list[dict[str, Any]]
) -> dict[str, Any]:
    return await _post(
        client,
        "update_deployment_config",
        {"deploymentId": str(deployment_id), "input": {"components": components}},
    )


async def _post_deploy(
    client: AsyncClient,
    driver_name: str,
    environment_id: UUID,
    components: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    name = f"replicas-deploy-{uuid4().hex[:8]}"
    payload = await _post(
        client,
        "deploy_with_config",
        {
            "driver": driver_name,
            "environmentId": str(environment_id),
            "version": "1.0.0",
            "name": name,
            "config": {"components": components},
        },
    )
    return name, payload


async def _post_update_version(
    client: AsyncClient,
    deployment_id: UUID,
    driver_version_id: UUID,
    components: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """``updateDeploymentVersion`` at application version ``1.0.0``, with ``input`` when
    ``components`` is given (what ``styrminctl deployments apply`` sends)."""
    variables: dict[str, Any] = {
        "deploymentId": str(deployment_id),
        "version": "1.0.0",
        "driverVersionId": str(driver_version_id),
    }
    if components is None:
        return await _post(client, "update_deployment_version", variables)
    variables["input"] = {"components": components}
    return await _post(client, "update_deployment_version_with_input", variables)


async def _stored_row(session: AsyncSession, deployment_id: UUID) -> Deployment:
    # Fresh SELECT: ``session.get`` would return the stale identity-map object.
    session.expire_all()
    return (
        await session.exec(select(Deployment).where(Deployment.id == deployment_id))
    ).one()


async def _stored_components(
    session: AsyncSession, deployment_id: UUID
) -> dict[str, Any]:
    row = await _stored_row(session, deployment_id)
    return (row.config or {}).get("components") or {}


async def _row_snapshot(session: AsyncSession, deployment_id: UUID) -> tuple[Any, ...]:
    row = await _stored_row(session, deployment_id)
    return (
        row.config,
        row.parameters,
        row.name,
        row.status,
        row.application_version,
        row.application_driver_version_id,
    )


async def _task_count(session: AsyncSession, deployment_id: UUID) -> int:
    rows = await session.exec(select(Task).where(Task.deployment_id == deployment_id))
    return len(rows.all())


async def _read_rows(client: AsyncClient, deployment_id: UUID) -> list[dict[str, Any]]:
    data = await gql(
        client,
        "get_deployment_component_replicas",
        {"deploymentId": str(deployment_id)},
    )
    return data["deployment"]["componentReplicas"]


def _row(
    component: str,
    count: int | None,
    source: str,
    *,
    override: int | None = None,
    singleton: bool = False,
) -> dict[str, Any]:
    return {
        "component": component,
        "count": count,
        "source": source,
        "override": override,
        "singleton": singleton,
        "isOrphaned": False,
        "isApplicable": True,
    }


DATABASE_ROW = _row("database", 1, "DRIVER_DEFAULT", singleton=True)
WORKER_ROW = _row("worker", 2, "DRIVER_DEFAULT")


def _assert_error(payload: dict[str, Any], code: str, **metadata: Any) -> str:
    """Assert the first error carries ``code`` and ``metadata``; return its message."""
    assert "errors" in payload, payload
    error = payload["errors"][0]
    extensions = error.get("extensions") or {}
    assert extensions.get("code") == code, extensions
    for key, value in metadata.items():
        assert extensions.get(key) == value, extensions
    return error["message"]


async def _assert_rejected_without_task(
    session: AsyncSession,
    prefect_manager_mock: Any,
    deployment_id: UUID,
    snapshot_before: tuple[Any, ...],
) -> None:
    prefect_manager_mock.run_action.assert_not_awaited()
    assert await _task_count(session, deployment_id) == 0
    assert await _row_snapshot(session, deployment_id) == snapshot_before


async def _assert_deploy_rejected_without_task(
    session: AsyncSession, prefect_manager_mock: Any, name: str
) -> None:
    prefect_manager_mock.run_action.assert_not_awaited()
    session.expire_all()
    created = await session.exec(select(Deployment).where(Deployment.name == name))
    assert created.all() == []
    assert (await session.exec(select(Task))).all() == []


# ---------------------------------------------------------------------------
# T016 — write paths store the override; componentReplicas projects it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_deployment_replicas_round_trip(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """``updateDeployment`` stores ``replicas`` on the component block, and
    ``componentReplicas`` reports it as the applied override, sorted by component."""
    _arm_prefect(prefect_manager_mock)
    deployment_id, _ = await _seed_deployment(session)

    payload = await _post_update(
        client, deployment_id, [{"name": "server", "replicas": 2}]
    )

    assert "errors" not in payload, payload
    assert await _stored_components(session, deployment_id) == {
        "server": {"replicas": 2}
    }
    assert await _task_count(session, deployment_id) == 1
    assert await _read_rows(client, deployment_id) == [
        DATABASE_ROW,
        _row("server", 2, "OVERRIDE", override=2),
        WORKER_ROW,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cleared_block",
    [{"name": "server"}, {"name": "server", "replicas": None}],
    ids=["replicas-omitted", "replicas-null"],
)
async def test_update_deployment_omitting_replicas_clears_it(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    cleared_block: dict[str, Any],
) -> None:
    """Full replacement: re-submitting the block without ``replicas`` clears the override, and
    the component falls back to the chart's count."""
    _arm_prefect(prefect_manager_mock)
    deployment_id, _ = await _seed_deployment(
        session, config={"components": {"server": {"replicas": 2}}}
    )

    payload = await _post_update(client, deployment_id, [cleared_block])

    assert "errors" not in payload, payload
    assert await _stored_components(session, deployment_id) == {"server": {}}
    assert await _read_rows(client, deployment_id) == [
        DATABASE_ROW,
        _row("server", None, "CHART"),
        WORKER_ROW,
    ]


@pytest.mark.asyncio
async def test_deploy_create_persists_replicas(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """``deploy(config: {components: [{name, replicas}]})`` stores the override on the new
    deployment exactly like the update path."""
    _arm_prefect(prefect_manager_mock)
    driver_name, environment_id = await _seed_deploy_driver(session)

    name, payload = await _post_deploy(
        client, driver_name, environment_id, [{"name": "server", "replicas": 3}]
    )

    assert "errors" not in payload, payload
    session.expire_all()
    created = (
        await session.exec(select(Deployment).where(Deployment.name == name))
    ).one()
    assert created.config["components"] == {"server": {"replicas": 3}}
    assert await _read_rows(client, created.id) == [
        DATABASE_ROW,
        _row("server", 3, "OVERRIDE", override=3),
        WORKER_ROW,
    ]


@pytest.mark.asyncio
async def test_update_deployment_version_input_persists_replicas(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """``updateDeploymentVersion(input:)`` stores the override with the driver version change
    and checks it against the target driver version, which declares ``api``."""
    _arm_prefect(prefect_manager_mock)
    deployment_id, _ = await _seed_deployment(session)
    target_id = await _seed_target_driver_version(
        session, deployment_id, {**DECLARATIONS, "api": {}}
    )

    payload = await _post_update_version(
        client, deployment_id, target_id, [{"name": "api", "replicas": 4}]
    )

    assert "errors" not in payload, payload
    stored = await _stored_row(session, deployment_id)
    assert stored.application_driver_version_id == target_id
    assert stored.config == {"components": {"api": {"replicas": 4}}}
    assert await _task_count(session, deployment_id) == 1
    assert await _read_rows(client, deployment_id) == [
        _row("api", 4, "OVERRIDE", override=4),
        DATABASE_ROW,
        _row("server", None, "CHART"),
        WORKER_ROW,
    ]


# ---------------------------------------------------------------------------
# T017 — rejections: typed error, no task, no flow run, unchanged row (SC-003)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("replicas", [0, -1])
async def test_update_deployment_rejects_count_below_one(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    replicas: int,
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id, _ = await _seed_deployment(
        session, config={"components": {"server": {"replicas": 2}}}
    )
    snapshot = await _row_snapshot(session, deployment_id)

    payload = await _post_update(
        client, deployment_id, [{"name": "server", "replicas": replicas}]
    )

    message = _assert_error(
        payload,
        "INVALID_REPLICA_COUNT",
        component_name="server",
        requested_replicas=replicas,
    )
    assert "'server'" in message
    assert "stop the component" in message
    await _assert_rejected_without_task(
        session, prefect_manager_mock, deployment_id, snapshot
    )


@pytest.mark.asyncio
async def test_update_deployment_rejects_override_on_unknown_component(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id, driver_name = await _seed_deployment(session)
    snapshot = await _row_snapshot(session, deployment_id)

    payload = await _post_update(
        client, deployment_id, [{"name": "ghost", "replicas": 2}]
    )

    message = _assert_error(
        payload,
        "UNKNOWN_COMPONENT_REPLICA_OVERRIDE",
        component_name="ghost",
        known_components=["database", "server", "worker"],
        checked_against=_checked_against(driver_name),
    )
    assert "'ghost'" in message
    await _assert_rejected_without_task(
        session, prefect_manager_mock, deployment_id, snapshot
    )


@pytest.mark.asyncio
async def test_deploy_rejects_override_on_unknown_component(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    _arm_prefect(prefect_manager_mock)
    driver_name, environment_id = await _seed_deploy_driver(session)

    name, payload = await _post_deploy(
        client, driver_name, environment_id, [{"name": "ghost", "replicas": 2}]
    )

    _assert_error(
        payload,
        "UNKNOWN_COMPONENT_REPLICA_OVERRIDE",
        component_name="ghost",
        known_components=["database", "server", "worker"],
        checked_against=_checked_against(driver_name),
    )
    await _assert_deploy_rejected_without_task(session, prefect_manager_mock, name)


@pytest.mark.asyncio
async def test_deploy_rejects_override_above_one_on_singleton(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    _arm_prefect(prefect_manager_mock)
    driver_name, environment_id = await _seed_deploy_driver(session)

    name, payload = await _post_deploy(
        client, driver_name, environment_id, [{"name": "database", "replicas": 2}]
    )

    message = _assert_error(
        payload,
        "SINGLETON_REPLICA_OVERRIDE",
        component_name="database",
        requested_replicas=2,
        checked_against=_checked_against(driver_name),
    )
    assert "'database'" in message
    await _assert_deploy_rejected_without_task(session, prefect_manager_mock, name)


@pytest.mark.asyncio
async def test_update_deployment_rejects_override_above_one_on_singleton(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id, driver_name = await _seed_deployment(session)
    snapshot = await _row_snapshot(session, deployment_id)

    payload = await _post_update(
        client, deployment_id, [{"name": "database", "replicas": 2}]
    )

    _assert_error(
        payload,
        "SINGLETON_REPLICA_OVERRIDE",
        component_name="database",
        requested_replicas=2,
        checked_against=_checked_against(driver_name),
    )
    await _assert_rejected_without_task(
        session, prefect_manager_mock, deployment_id, snapshot
    )


@pytest.mark.asyncio
async def test_update_deployment_version_input_rejects_override_above_one_on_singleton(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """The ``styrminctl deployments apply`` path: ``updateDeploymentVersion(input:)`` on the
    bound driver version."""
    _arm_prefect(prefect_manager_mock)
    deployment_id, driver_name = await _seed_deployment(session)
    stored = await _stored_row(session, deployment_id)
    bound_id = stored.application_driver_version_id
    snapshot = await _row_snapshot(session, deployment_id)

    payload = await _post_update_version(
        client,
        deployment_id,
        bound_id,
        [{"name": "server", "replicas": 2}, {"name": "database", "replicas": 3}],
    )

    _assert_error(
        payload,
        "SINGLETON_REPLICA_OVERRIDE",
        component_name="database",
        requested_replicas=3,
        checked_against=_checked_against(driver_name),
    )
    await _assert_rejected_without_task(
        session, prefect_manager_mock, deployment_id, snapshot
    )


# The current driver version lets ``database`` scale; the target marks it singleton.
UNMARKED_DATABASE = {**DECLARATIONS, "database": {}}


@pytest.mark.asyncio
async def test_version_change_rejects_stored_override_on_new_singleton(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """A stored override of 2 breaks the target driver version's singleton rule, so the
    version change without ``input`` is rejected and the deployment stays bound."""
    _arm_prefect(prefect_manager_mock)
    deployment_id, driver_name = await _seed_deployment(
        session,
        UNMARKED_DATABASE,
        config={"components": {"database": {"replicas": 2}}},
    )
    target_id = await _seed_target_driver_version(session, deployment_id, DECLARATIONS)
    snapshot = await _row_snapshot(session, deployment_id)

    payload = await _post_update_version(client, deployment_id, target_id, None)

    message = _assert_error(
        payload,
        "SINGLETON_REPLICA_OVERRIDE",
        component_name="database",
        requested_replicas=2,
        checked_against=_checked_against(driver_name, "2.0.0"),
    )
    assert "Set the override to 1 or clear it" in message
    await _assert_rejected_without_task(
        session, prefect_manager_mock, deployment_id, snapshot
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("components", "expected_stored", "expected_database"),
    [
        (
            [{"name": "database", "replicas": 1}],
            {"database": {"replicas": 1}},
            _row("database", 1, "OVERRIDE", override=1, singleton=True),
        ),
        ([{"name": "database"}], {"database": {}}, DATABASE_ROW),
    ],
    ids=["lowered-to-one", "cleared"],
)
async def test_version_change_to_new_singleton_succeeds_when_input_fixes_override(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    components: list[dict[str, Any]],
    expected_stored: dict[str, Any],
    expected_database: dict[str, Any],
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id, _ = await _seed_deployment(
        session,
        UNMARKED_DATABASE,
        config={"components": {"database": {"replicas": 2}}},
    )
    target_id = await _seed_target_driver_version(session, deployment_id, DECLARATIONS)

    payload = await _post_update_version(client, deployment_id, target_id, components)

    assert "errors" not in payload, payload
    stored = await _stored_row(session, deployment_id)
    assert stored.application_driver_version_id == target_id
    assert stored.config == {"components": expected_stored}
    assert await _task_count(session, deployment_id) == 1
    rows = await _read_rows(client, deployment_id)
    assert rows[0] == expected_database


# ---------------------------------------------------------------------------
# T033 — driver defaults reach componentReplicas and the replica patch (US2)
# ---------------------------------------------------------------------------


def _write_driver(path: Path, components: dict[str, dict[str, Any]]) -> None:
    """Write a local driver whose components carry the given ``replicas`` / ``singleton`` keys."""
    spec: dict[str, Any] = {
        "apiVersion": "styrmin.io/v1",
        "kind": "ApplicationDriver",
        "metadata": {"name": f"replica-defaults-{uuid4().hex[:8]}"},
        "spec": {
            "version": "0.1.0",
            "supported_versions": ">=1.0,<2.0",
            "info": {"description": "Driver default replicas fixture"},
            "helm": {
                "main": {
                    "location": "oci://registry.example.com/charts/simple-app",
                    "version": "0.1.0",
                }
            },
            "components": {
                name: {
                    "identifier": {"label": {"app.kubernetes.io/name": f"{name}-app"}},
                    "container": name,
                    **keys,
                }
                for name, keys in components.items()
            },
        },
    }
    (path / "driver.styrmin.yml").write_text(yaml.safe_dump(spec))
    (path / "values.j2.yml").write_text("{}\n")


@pytest.mark.asyncio
async def test_driver_defaults_report_without_an_override(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock, tmp_path: Path
) -> None:
    """A deployment created with no override of a loaded driver version that declares
    ``server.replicas: 2`` and ``database.singleton: true`` reports 2 and 1 from the driver
    default, and the chart's count for ``worker``; the replica patches carry the same counts."""
    _arm_prefect(prefect_manager_mock)
    _write_driver(
        tmp_path,
        {"server": {"replicas": 2}, "database": {"singleton": True}, "worker": {}},
    )
    loaded = await gql(
        client, "load_local_driver_component_replicas", {"path": str(tmp_path)}
    )
    version = loaded["loadLocalApplicationDriverVersion"]
    driver = await session.get(ApplicationDriver, UUID(version["applicationDriverId"]))
    assert driver is not None
    environment = await seed_environment(session)
    name = f"replica-defaults-{uuid4().hex[:8]}"

    payload = await _post(
        client,
        "deploy_with_driver_version",
        {
            "driver": driver.name,
            "environmentId": str(environment.id),
            "name": name,
            "version": "1.0.0",
            "driverVersionId": version["id"],
        },
    )

    assert "errors" not in payload, payload
    session.expire_all()
    created = (
        await session.exec(select(Deployment).where(Deployment.name == name))
    ).one()
    assert not (created.config or {}).get("components")
    assert await _read_rows(client, created.id) == [
        _row("database", 1, "DRIVER_DEFAULT", singleton=True),
        _row("server", 2, "DRIVER_DEFAULT"),
        _row("worker", None, "CHART"),
    ]

    context = await generate_context_from_deployment_id(
        created.id, SqlModelUnitOfWork(session=session)
    )
    patches = build_component_replica_patches(context)
    summary = []
    for tp in patches:
        assert isinstance(tp.patch, SpecPatch)
        summary.append(
            (tp.target.kind, tp.target.label_selector, tp.patch.specs["replicas"])
        )
    assert sorted(summary) == sorted(
        (kind, f"app.kubernetes.io/name={component}-app", count)
        for component, count in (("server", 2), ("database", 1))
        for kind in REPLICA_PATCH_KINDS
    )
