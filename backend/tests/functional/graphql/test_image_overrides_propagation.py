"""GraphQL ↔ DB propagation tests for per-component image overrides (018).

Constitution §V: ``ComponentConfigInput.image`` written through ``updateDeployment`` and
``deploy`` reaches ``Deployment.config["components"][name]["image"]`` through the real service
and repository layers, and ``Deployment.componentImageOverrides`` projects the stored state.
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
    Component,
    ComponentConfig,
    Deployment,
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
