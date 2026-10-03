"""GraphQL ↔ DB propagation tests for per-component image overrides (018).

Constitution §V: ``ComponentConfigInput.image`` written through ``updateDeployment`` and
``deploy`` reaches ``Deployment.config["components"][name]["image"]`` through the real service
and repository layers, and ``Deployment.componentImageOverrides`` projects the stored state.
``updateDeploymentVersion`` re-validates stored, applicable overrides at the target version.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
    Component,
    ComponentConfig,
    Deployment,
    Task,
)

from ._queries import load_query
from .conftest import gql
from .seeds import (
    seed_application_driver_version,
    seed_deployment,
    seed_environment,
)

PATCHED = "registry.example/acme/simple-app-patched"


def _arm_prefect(prefect_manager_mock: Any) -> None:
    """Give the Prefect manager concrete return values so a successful reconcile dispatch
    does not leak an ``AsyncMock`` into a DB-bound column."""
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())


def _component_config(name: str, container: str | None) -> dict[str, Any]:
    return {
        "identifier": {"label": {"app.kubernetes.io/name": f"{name}-app"}},
        "container": container,
    }


async def _seed_deployment_with_components(
    session: AsyncSession, containers: dict[str, str | None]
) -> Deployment:
    """Seed a deployment whose driver declares ``containers`` (component → component
    container) and whose Component rows mirror them, as ``deploy`` copies them."""
    adv = await seed_application_driver_version(session)
    for name, container in containers.items():
        session.add(
            ComponentConfig(
                name=name,
                config=_component_config(name, container),
                application_driver_version_id=adv.id,
            )
        )
    await session.commit()
    deployment = await seed_deployment(session, adv=adv)
    for name, container in containers.items():
        session.add(
            Component(
                name=name,
                config=_component_config(name, container),
                enabled=True,
                deployment_id=deployment.id,
            )
        )
    await session.commit()
    return deployment


async def _update(
    client: AsyncClient, deployment_id: UUID, components: list[dict]
) -> None:
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment_config"),
            "variables": {
                "deploymentId": str(deployment_id),
                "input": {"components": components},
            },
        },
    )
    assert response.status_code == 200
    assert "errors" not in response.json(), response.json()


async def _stored_components(session: AsyncSession, deployment_id: UUID) -> dict:
    # Fresh SELECT: ``session.get`` would return the stale identity-map object.
    session.expire_all()
    row = (
        await session.exec(select(Deployment).where(Deployment.id == deployment_id))
    ).one()
    return (row.config or {}).get("components") or {}


async def _read_overrides(
    client: AsyncClient, deployment_id: UUID
) -> list[dict[str, Any]]:
    data = await gql(
        client,
        "get_deployment_component_image_overrides",
        {"deploymentId": str(deployment_id)},
    )
    return data["deployment"]["componentImageOverrides"]


@pytest.mark.asyncio
async def test_update_deployment_image_round_trip(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """``updateDeployment`` stores ``image`` on the component block and
    ``componentImageOverrides`` projects it with the token resolved."""
    _arm_prefect(prefect_manager_mock)
    deployment = await _seed_deployment_with_components(
        session, {"server": "simple-app", "db": "postgres"}
    )
    deployment_id = deployment.id
    reference = f"{PATCHED}:{{{{ app.version }}}}"

    await _update(client, deployment_id, [{"name": "server", "image": reference}])

    stored = await _stored_components(session, deployment_id)
    assert stored == {"server": {"image": reference}}

    assert await _read_overrides(client, deployment_id) == [
        {
            "component": "server",
            "reference": reference,
            "resolvedReference": f"{PATCHED}:1.0.0",
            "isOrphaned": False,
            "isApplicable": True,
        }
    ]


@pytest.mark.asyncio
async def test_update_deployment_omitting_image_clears_it(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """Full replacement: re-submitting the block without ``image`` clears the override and
    keeps the other slots."""
    _arm_prefect(prefect_manager_mock)
    deployment = await _seed_deployment_with_components(
        session, {"server": "simple-app"}
    )
    deployment_id = deployment.id

    await _update(
        client,
        deployment_id,
        [{"name": "server", "image": f"{PATCHED}:0.1.0", "args": ["--debug"]}],
    )
    await _update(client, deployment_id, [{"name": "server", "args": ["--debug"]}])

    stored = await _stored_components(session, deployment_id)
    assert stored == {"server": {"args": ["--debug"]}}
    assert await _read_overrides(client, deployment_id) == []


@pytest.mark.asyncio
async def test_deploy_create_persists_image(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """``deploy(config: {components: [{name, image}]})`` stores the override on the new
    deployment exactly like the update path."""
    _arm_prefect(prefect_manager_mock)
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session, version="1.0.0")
    session.add(
        ComponentConfig(
            name="server",
            config=_component_config("server", "simple-app"),
            application_driver_version_id=adv.id,
        )
    )
    await session.commit()
    driver_row = await session.get(ApplicationDriver, adv.application_driver_id)
    assert driver_row is not None
    name = f"image-create-{uuid4().hex[:8]}"
    reference = f"{PATCHED}:{{{{ app.version }}}}"

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("deploy_with_config"),
            "variables": {
                "driver": driver_row.name,
                "environmentId": str(environment.id),
                "version": "1.0.0",
                "name": name,
                "config": {"components": [{"name": "server", "image": reference}]},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    session.expire_all()
    created = (
        await session.exec(select(Deployment).where(Deployment.name == name))
    ).one()
    assert created.config["components"]["server"]["image"] == reference

    rows = await _read_overrides(client, created.id)
    assert [(r["component"], r["resolvedReference"]) for r in rows] == [
        ("server", f"{PATCHED}:1.0.0")
    ]


@pytest.mark.asyncio
async def test_component_image_overrides_empty_when_unset(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment = await _seed_deployment_with_components(
        session, {"server": "simple-app"}
    )
    assert await _read_overrides(client, deployment.id) == []


@pytest.mark.asyncio
async def test_component_image_overrides_projects_stored_state(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Live entries in driver order, then orphans by name. A literal tag is not substituted;
    a containerless or orphaned component is not applicable; blocks without ``image`` are
    omitted."""
    deployment = await _seed_deployment_with_components(
        session, {"server": "simple-app", "worker": None, "db": "postgres"}
    )
    deployment.config = {
        "components": {
            "zombie": {"image": f"{PATCHED}:{{{{app.version}}}}"},
            "db": {"args": ["--verbose"]},
            "worker": {"image": f"{PATCHED}:{{{{ app.version }}}}-worker"},
            "server": {"image": f"{PATCHED}:0.1.0"},
            "ghost": {"image": "ghost:1"},
        }
    }
    session.add(deployment)
    await session.commit()

    data = await gql(
        client,
        "get_deployment_component_image_overrides",
        {"deploymentId": str(deployment.id)},
    )
    assert data["deployment"]["applicationVersion"] == "1.0.0"
    rows = data["deployment"]["componentImageOverrides"]
    assert rows == [
        {
            "component": "server",
            "reference": f"{PATCHED}:0.1.0",
            "resolvedReference": f"{PATCHED}:0.1.0",
            "isOrphaned": False,
            "isApplicable": True,
        },
        {
            "component": "worker",
            "reference": f"{PATCHED}:{{{{ app.version }}}}-worker",
            "resolvedReference": f"{PATCHED}:1.0.0-worker",
            "isOrphaned": False,
            "isApplicable": False,
        },
        {
            "component": "ghost",
            "reference": "ghost:1",
            "resolvedReference": "ghost:1",
            "isOrphaned": True,
            "isApplicable": False,
        },
        {
            "component": "zombie",
            "reference": f"{PATCHED}:{{{{app.version}}}}",
            "resolvedReference": f"{PATCHED}:1.0.0",
            "isOrphaned": True,
            "isApplicable": False,
        },
    ]


# ---------------------------------------------------------------------------
# US2 — updateDeploymentVersion re-validates stored, applicable overrides (T037)
# ---------------------------------------------------------------------------

# Tags disallow "+", so the token breaks only after substituting this version.
BROKEN_TARGET = "1.1.0+build"
TOKEN_REFERENCE = f"{PATCHED}:{{{{ app.version }}}}"


async def _seed_target_driver_version(
    session: AsyncSession, deployment_id: UUID, containers: dict[str, str | None]
) -> UUID:
    """Add a second version of the deployment's driver declaring ``containers``."""
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
    for name, container in containers.items():
        session.add(
            ComponentConfig(
                name=name,
                config=_component_config(name, container),
                application_driver_version_id=target_id,
            )
        )
    await session.commit()
    return target_id


async def _store_config(
    session: AsyncSession, deployment: Deployment, config: dict[str, Any]
) -> None:
    deployment.config = config
    session.add(deployment)
    await session.commit()


async def _update_version(
    client: AsyncClient,
    deployment_id: UUID,
    version: str,
    driver_version_id: UUID | None,
) -> dict[str, Any]:
    variables: dict[str, Any] = {"deploymentId": str(deployment_id), "version": version}
    if driver_version_id is not None:
        variables["driverVersionId"] = str(driver_version_id)
    response = await client.post(
        "/graphql",
        json={"query": load_query("update_deployment_version"), "variables": variables},
    )
    assert response.status_code == 200
    return response.json()


async def _task_count(session: AsyncSession, deployment_id: UUID) -> int:
    rows = await session.exec(select(Task).where(Task.deployment_id == deployment_id))
    return len(rows.all())


async def _stored_row(session: AsyncSession, deployment_id: UUID) -> Deployment:
    session.expire_all()
    return (
        await session.exec(select(Deployment).where(Deployment.id == deployment_id))
    ).one()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current_containers", "target_containers"),
    [
        ({"server": "simple-app"}, None),
        ({"server": None}, {"server": "simple-app"}),
    ],
    ids=["same-driver-version", "target-driver-version-declares-container"],
)
async def test_update_deployment_version_rejects_reference_broken_by_substitution(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    current_containers: dict[str, str | None],
    target_containers: dict[str, str | None] | None,
) -> None:
    """A stored override applicable in the target driver version that resolves to an invalid
    reference at the target application version rejects the upgrade before any task."""
    _arm_prefect(prefect_manager_mock)
    deployment = await _seed_deployment_with_components(session, current_containers)
    deployment_id = deployment.id
    driver_version_before = deployment.application_driver_version_id
    config = {"components": {"server": {"image": TOKEN_REFERENCE}}}
    await _store_config(session, deployment, config)
    target_id = (
        await _seed_target_driver_version(session, deployment_id, target_containers)
        if target_containers is not None
        else None
    )

    payload = await _update_version(client, deployment_id, BROKEN_TARGET, target_id)

    assert "errors" in payload, payload
    error = payload["errors"][0]
    extensions = error.get("extensions") or {}
    assert extensions.get("code") == "INVALID_IMAGE_REFERENCE", extensions
    assert extensions.get("component_name") == "server", extensions
    assert extensions.get("reference") == TOKEN_REFERENCE, extensions
    assert extensions.get("reason") == "after_substitution", extensions
    assert extensions.get("application_version") == BROKEN_TARGET, extensions
    assert "'server'" in error["message"]

    prefect_manager_mock.run_action.assert_not_awaited()
    assert await _task_count(session, deployment_id) == 0
    stored = await _stored_row(session, deployment_id)
    assert stored.application_version == "1.0.0"
    assert stored.application_driver_version_id == driver_version_before
    assert stored.config == config


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current_containers", "config", "target_containers"),
    [
        (
            {"server": "simple-app", "worker": None},
            {
                "components": {
                    "server": {"image": f"{PATCHED}:0.1.0"},
                    "worker": {"image": TOKEN_REFERENCE},
                }
            },
            None,
        ),
        (
            {"server": "simple-app"},
            {"components": {"server": {"image": TOKEN_REFERENCE}}},
            {"server": None},
        ),
        (
            {"server": "simple-app"},
            {"components": {"server": {"image": TOKEN_REFERENCE}}},
            {"api": "api"},
        ),
    ],
    ids=[
        "containerless-component",
        "target-driver-version-drops-container",
        "target-driver-version-drops-component",
    ],
)
async def test_update_deployment_version_ignores_non_applicable_override(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    current_containers: dict[str, str | None],
    config: dict[str, Any],
    target_containers: dict[str, str | None] | None,
) -> None:
    """An override that is not applicable in the target driver version (containerless or
    orphaned component) is never rendered, so it does not block the upgrade."""
    _arm_prefect(prefect_manager_mock)
    deployment = await _seed_deployment_with_components(session, current_containers)
    deployment_id = deployment.id
    await _store_config(session, deployment, config)
    target_id = (
        await _seed_target_driver_version(session, deployment_id, target_containers)
        if target_containers is not None
        else None
    )

    payload = await _update_version(client, deployment_id, BROKEN_TARGET, target_id)

    assert "errors" not in payload, payload
    assert await _task_count(session, deployment_id) == 1
    stored = await _stored_row(session, deployment_id)
    assert stored.application_version == BROKEN_TARGET
    assert stored.config == config
