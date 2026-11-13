"""``DeploymentResource.scale`` keeps the stored ``services`` block (#598, T030a).

``updateDeployment`` replaces the whole stored config with the fields it receives, and ``scale``
sends the replica count as ``components`` only. These tests run the real SDK against the real
backend through the ASGI client and read the stored config back, so they show what a user of
``styrminctl deployments scale`` gets.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from styrmin_sdk import StyrminClient

from styrmin_backend.db.models import Component, ComponentConfig, Deployment

from .test_service_ingress_propagation import (
    TASK_MANAGER_OVERRIDE_STORED,
    _arm_prefect,
    _seed_deployment,
)

COMPONENT_CONFIG: dict[str, Any] = {
    "identifier": {"label": {"app.kubernetes.io/name": "server-app"}},
    "container": "server",
}


async def _seed_scalable_deployment(
    session: AsyncSession, config: dict[str, Any]
) -> UUID:
    """A deployment with a ``server`` component that the driver version declares."""
    deployment_id = await _seed_deployment(session, config=config)
    deployment = await session.get(Deployment, deployment_id)
    assert deployment is not None
    session.add(
        ComponentConfig(
            name="server",
            config=COMPONENT_CONFIG,
            application_driver_version_id=deployment.application_driver_version_id,
        )
    )
    session.add(
        Component(
            name="server",
            config=COMPONENT_CONFIG,
            enabled=True,
            deployment_id=deployment_id,
        )
    )
    await session.commit()
    return deployment_id


async def _scale(
    client: AsyncClient, deployment_id: UUID, replicas: int | None
) -> None:
    """Run the SDK ``scale`` through the ASGI client of the backend."""
    sdk = StyrminClient(server_address="http://test")
    sdk._transport._client = client  # noqa: SLF001 - the SDK has no hook for another transport
    await sdk.deployments.scale(deployment_id, "server", replicas)


async def _stored_config(session: AsyncSession, deployment_id: UUID) -> dict[str, Any]:
    session.expire_all()
    row = (
        await session.exec(select(Deployment).where(Deployment.id == deployment_id))
    ).one()
    assert row.config is not None
    return row.config


@pytest.mark.asyncio
async def test_scale_keeps_the_stored_service_overrides(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_scalable_deployment(
        session, {"services": {"task-manager": TASK_MANAGER_OVERRIDE_STORED}}
    )

    await _scale(client, deployment_id, 3)

    assert await _stored_config(session, deployment_id) == {
        "components": {"server": {"replicas": 3}},
        "services": {"task-manager": TASK_MANAGER_OVERRIDE_STORED},
    }


@pytest.mark.asyncio
async def test_clearing_the_count_keeps_the_stored_service_overrides(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_scalable_deployment(
        session,
        {
            "components": {"server": {"replicas": 2}},
            "services": {"task-manager": TASK_MANAGER_OVERRIDE_STORED},
        },
    )

    await _scale(client, deployment_id, None)

    assert await _stored_config(session, deployment_id) == {
        "components": {},
        "services": {"task-manager": TASK_MANAGER_OVERRIDE_STORED},
    }


@pytest.mark.asyncio
async def test_scale_without_service_overrides_stores_no_services_key(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_scalable_deployment(session, {})

    await _scale(client, deployment_id, 3)

    assert await _stored_config(session, deployment_id) == {
        "components": {"server": {"replicas": 3}}
    }
