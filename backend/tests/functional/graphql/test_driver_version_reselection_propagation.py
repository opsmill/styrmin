"""GraphQL ↔ DB propagation tests for driver-version reselection / pinning.

Per Constitution §V the new optional ``driverVersionId`` argument on
``updateDeploymentVersion`` and ``deploy`` requires propagation coverage
proving the value flows through the real service + repository layers into
``Deployment.application_driver_version_id``. This module also pins the
default latest-wins resolution at the GraphQL boundary: when several driver
versions of the same driver support the requested application version, the
binding moves to the latest one (highest parseable driver ``version``, then
``created_on``), never the DB insertion order.

Successful mutations regenerate the application instance and dispatch a
reconcile through the Prefect manager, so they arm the mock via
:func:`_arm_prefect` (mirrors ``test_container_overrides_propagation.py``).

NOTE: object attribute access after ``session.expire_all()`` would trigger a
sync lazy refresh (MissingGreenlet under asyncio) — every test captures the
ids it needs *before* driving the mutation.
"""

from __future__ import annotations

from datetime import datetime, timezone
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
)

from ._queries import load_query
from .seeds import (
    seed_application_driver_version,
    seed_deployment,
    seed_environment,
)

_T_OLD = datetime(2026, 1, 1, tzinfo=timezone.utc)
_T_NEW = datetime(2026, 2, 1, tzinfo=timezone.utc)


def _arm_prefect(prefect_manager_mock: Any) -> None:
    """Give the Prefect manager concrete (non-AsyncMock) return values so a
    successful reconcile dispatch does not leak an ``AsyncMock`` into a
    DB-bound column.
    """
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())


async def _add_component_config(
    session: AsyncSession, adv_id: UUID, name: str = "server"
) -> None:
    session.add(
        ComponentConfig(
            name=name,
            config={"identifier": {"label": {"app.kubernetes.io/name": f"{name}-app"}}},
            application_driver_version_id=adv_id,
        )
    )
    await session.commit()


async def _seed_overlapping_versions(session: AsyncSession) -> tuple[UUID, UUID, str]:
    """Two versions of the same driver, both supporting ``0.x`` app versions.

    Returns ``(old_id, new_id, driver_name)``. ``old`` is driver version "1"
    (loaded first), ``new`` is driver version "2" (loaded later). Both declare
    a ``server`` component so a rebind recreates a same-named component — the
    regression case for ``Deployment.set_components``.
    """
    old = await seed_application_driver_version(
        session,
        version="1",
        application_supported_versions=">=0.1,<1.0",
        created_on=_T_OLD,
    )
    driver = await session.get(ApplicationDriver, old.application_driver_id)
    assert driver is not None
    new = await seed_application_driver_version(
        session,
        driver=driver,
        version="2",
        application_supported_versions=">=0.1,<1.0",
        created_on=_T_NEW,
    )
    await _add_component_config(session, old.id)
    await _add_component_config(session, new.id)
    return old.id, new.id, driver.name


async def _seed_bound_deployment(session: AsyncSession, adv_id: UUID) -> UUID:
    """A deployment bound to ``adv_id`` with a matching ``server`` component
    row. Returns the deployment id."""
    adv = await session.get(ApplicationDriverVersion, adv_id)
    assert adv is not None
    deployment = await seed_deployment(session, adv=adv)
    session.add(
        Component(
            name="server",
            config={"identifier": {"label": {"app.kubernetes.io/name": "server-app"}}},
            enabled=True,
            deployment_id=deployment.id,
        )
    )
    await session.commit()
    return deployment.id


async def _update_version(
    client: AsyncClient,
    deployment_id: UUID,
    version: str,
    driver_version_id: UUID | None = None,
) -> dict:
    variables: dict[str, Any] = {
        "deploymentId": str(deployment_id),
        "version": version,
    }
    if driver_version_id is not None:
        variables["driverVersionId"] = str(driver_version_id)
    response = await client.post(
        "/graphql",
        json={"query": load_query("update_deployment_version"), "variables": variables},
    )
    assert response.status_code == 200
    return response.json()


async def _get_binding(session: AsyncSession, deployment_id: UUID) -> tuple[UUID, str]:
    """Read back ``(application_driver_version_id, application_version)``."""
    session.expire_all()
    refreshed = await session.get(Deployment, deployment_id)
    assert refreshed is not None
    return refreshed.application_driver_version_id, refreshed.application_version


async def _get_components(
    session: AsyncSession, deployment_id: UUID
) -> list[Component]:
    return list(
        (
            await session.exec(
                select(Component).where(Component.deployment_id == deployment_id)
            )
        ).all()
    )


# ---------------------------------------------------------------------------
# updateDeploymentVersion — latest-wins default resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_version_rebinds_to_latest_overlapping_driver_version(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """Without a pin, an upgrade re-resolves the binding to the latest driver
    version supporting the requested application version — even when the
    currently bound version still supports it (the gate removed by this
    feature) and even at the same application version."""
    _arm_prefect(prefect_manager_mock)
    old_id, new_id, _ = await _seed_overlapping_versions(session)
    deployment_id = await _seed_bound_deployment(session, old_id)

    payload = await _update_version(client, deployment_id, "0.5.0")
    assert "errors" not in payload, payload

    binding, app_version = await _get_binding(session, deployment_id)
    assert binding == new_id
    assert app_version == "0.5.0"

    # The rebind replaced the same-named component instead of raising or
    # duplicating — exactly one ``server`` Component row remains.
    components = await _get_components(session, deployment_id)
    assert [c.name for c in components] == ["server"]


@pytest.mark.asyncio
async def test_update_version_noop_keeps_binding_and_components(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """Already bound to the latest matching driver version → the binding and
    the component rows are untouched (no churn), while the upgrade still
    reconciles the requested application version."""
    _arm_prefect(prefect_manager_mock)
    _old_id, new_id, _ = await _seed_overlapping_versions(session)
    deployment_id = await _seed_bound_deployment(session, new_id)
    component_ids = {c.id for c in await _get_components(session, deployment_id)}

    payload = await _update_version(client, deployment_id, "0.6.0")
    assert "errors" not in payload, payload

    binding, app_version = await _get_binding(session, deployment_id)
    assert binding == new_id
    assert app_version == "0.6.0"
    assert {
        c.id for c in await _get_components(session, deployment_id)
    } == component_ids


# ---------------------------------------------------------------------------
# updateDeploymentVersion — explicit pin
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_version_pin_propagates_to_binding(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """An explicit ``driverVersionId`` overrides latest-wins: pinning the
    older build moves the binding there even though a newer one matches."""
    _arm_prefect(prefect_manager_mock)
    old_id, new_id, _ = await _seed_overlapping_versions(session)
    deployment_id = await _seed_bound_deployment(session, new_id)

    payload = await _update_version(
        client, deployment_id, "0.5.0", driver_version_id=old_id
    )
    assert "errors" not in payload, payload

    binding, app_version = await _get_binding(session, deployment_id)
    assert binding == old_id
    assert app_version == "0.5.0"


@pytest.mark.asyncio
async def test_update_version_pin_unknown_id_raises_not_found(
    client: AsyncClient, session: AsyncSession
) -> None:
    old_id, _new_id, _ = await _seed_overlapping_versions(session)
    deployment_id = await _seed_bound_deployment(session, old_id)

    payload = await _update_version(
        client, deployment_id, "0.5.0", driver_version_id=uuid4()
    )
    assert any(
        err["extensions"].get("code") == "NOT_FOUND" for err in payload["errors"]
    ), payload["errors"]

    binding, _ = await _get_binding(session, deployment_id)
    assert binding == old_id


@pytest.mark.asyncio
async def test_update_version_pin_from_other_driver_raises_validation(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A pin that belongs to a different application driver is rejected —
    cross-driver moves are not supported."""
    old_id, _new_id, _ = await _seed_overlapping_versions(session)
    deployment_id = await _seed_bound_deployment(session, old_id)
    foreign = await seed_application_driver_version(
        session, application_supported_versions=">=0.1,<1.0"
    )
    foreign_id = foreign.id

    payload = await _update_version(
        client, deployment_id, "0.5.0", driver_version_id=foreign_id
    )
    assert any(
        err["extensions"].get("code") == "VALIDATION_ERROR" for err in payload["errors"]
    ), payload["errors"]

    binding, _ = await _get_binding(session, deployment_id)
    assert binding == old_id


@pytest.mark.asyncio
async def test_update_version_pin_unsupported_version_raises_validation(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A pin whose specifier does not cover the requested application version
    is rejected instead of silently deploying an unsupported combination."""
    old_id, _new_id, _ = await _seed_overlapping_versions(session)
    deployment_id = await _seed_bound_deployment(session, old_id)
    old = await session.get(ApplicationDriverVersion, old_id)
    assert old is not None
    driver = await session.get(ApplicationDriver, old.application_driver_id)
    assert driver is not None
    incompatible = await seed_application_driver_version(
        session,
        driver=driver,
        version="3",
        application_supported_versions=">=2.0,<3.0",
    )
    incompatible_id = incompatible.id

    payload = await _update_version(
        client, deployment_id, "0.5.0", driver_version_id=incompatible_id
    )
    assert any(
        err["extensions"].get("code") == "VALIDATION_ERROR" for err in payload["errors"]
    ), payload["errors"]

    binding, _ = await _get_binding(session, deployment_id)
    assert binding == old_id


# ---------------------------------------------------------------------------
# deploy — latest-wins + explicit pin at create time
# ---------------------------------------------------------------------------


async def _deploy(
    client: AsyncClient,
    driver_name: str,
    environment_id: UUID,
    name: str,
    *,
    version: str | None = None,
    driver_version_id: UUID | None = None,
) -> dict:
    variables: dict[str, Any] = {
        "driver": driver_name,
        "environmentId": str(environment_id),
        "name": name,
    }
    if version is not None:
        variables["version"] = version
    if driver_version_id is not None:
        variables["driverVersionId"] = str(driver_version_id)
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("deploy_with_driver_version"),
            "variables": variables,
        },
    )
    assert response.status_code == 200
    return response.json()


async def _get_created(session: AsyncSession, name: str) -> Deployment:
    session.expire_all()
    return (await session.exec(select(Deployment).where(Deployment.name == name))).one()


@pytest.mark.asyncio
async def test_deploy_binds_latest_overlapping_driver_version(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    _arm_prefect(prefect_manager_mock)
    _old_id, new_id, driver_name = await _seed_overlapping_versions(session)
    environment = await seed_environment(session)
    environment_id = environment.id

    payload = await _deploy(
        client, driver_name, environment_id, "latest-wins-deploy", version="0.5.0"
    )
    assert "errors" not in payload, payload

    created = await _get_created(session, "latest-wins-deploy")
    assert created.application_driver_version_id == new_id


@pytest.mark.asyncio
async def test_deploy_pin_propagates_to_binding(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    _arm_prefect(prefect_manager_mock)
    old_id, _new_id, driver_name = await _seed_overlapping_versions(session)
    environment = await seed_environment(session)
    environment_id = environment.id

    payload = await _deploy(
        client,
        driver_name,
        environment_id,
        "pinned-deploy",
        version="0.5.0",
        driver_version_id=old_id,
    )
    assert "errors" not in payload, payload

    created = await _get_created(session, "pinned-deploy")
    assert created.application_driver_version_id == old_id


@pytest.mark.asyncio
async def test_deploy_default_version_comes_from_latest_driver_version(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """With no version given, the default_version declared by the *latest*
    driver version wins — not the first row in insertion order."""
    _arm_prefect(prefect_manager_mock)
    old = await seed_application_driver_version(
        session,
        version="1",
        application_supported_versions=">=0.1,<1.0",
        default_version="0.1.0",
        created_on=_T_OLD,
    )
    driver = await session.get(ApplicationDriver, old.application_driver_id)
    assert driver is not None
    driver_name = driver.name
    new = await seed_application_driver_version(
        session,
        driver=driver,
        version="2",
        application_supported_versions=">=0.1,<1.0",
        default_version="0.2.0",
        created_on=_T_NEW,
    )
    new_id = new.id
    await _add_component_config(session, old.id)
    await _add_component_config(session, new_id)
    environment = await seed_environment(session)
    environment_id = environment.id

    payload = await _deploy(client, driver_name, environment_id, "default-from-latest")
    assert "errors" not in payload, payload

    created = await _get_created(session, "default-from-latest")
    assert created.application_version == "0.2.0"
    assert created.application_driver_version_id == new_id


@pytest.mark.asyncio
async def test_deploy_pin_unknown_id_raises_not_found(
    client: AsyncClient, session: AsyncSession
) -> None:
    _old_id, _new_id, driver_name = await _seed_overlapping_versions(session)
    environment = await seed_environment(session)
    environment_id = environment.id

    payload = await _deploy(
        client,
        driver_name,
        environment_id,
        "pin-unknown",
        version="0.5.0",
        driver_version_id=uuid4(),
    )
    assert any(
        err["extensions"].get("code") == "NOT_FOUND" for err in payload["errors"]
    ), payload["errors"]
    session.expire_all()
    assert (
        await session.exec(select(Deployment).where(Deployment.name == "pin-unknown"))
    ).first() is None
