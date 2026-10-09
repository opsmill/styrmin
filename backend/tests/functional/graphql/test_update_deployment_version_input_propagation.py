"""GraphQL ↔ DB propagation tests for ``updateDeploymentVersion(input:)`` (#388).

The config, name, parameters and service name overrides given with a version
change are validated against the target driver version and written with it,
in one task.
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
    ApplicationInstance,
    ComponentConfig,
    Deployment,
    Task,
)

from ._queries import load_query
from .conftest import gql
from .seeds import seed_application_driver_version, seed_environment


def _arm_prefect(prefect_manager_mock: Any) -> None:
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())


async def _seed_driver(session: AsyncSession) -> tuple[str, UUID, UUID]:
    """Seed ``v1`` (``server`` without a container) and ``v2`` (``server`` and
    ``worker`` with containers) of one driver."""
    v1 = await seed_application_driver_version(session, version="1.0.0")
    driver = await session.get(ApplicationDriver, v1.application_driver_id)
    assert driver is not None
    driver_name = driver.name
    v2 = await seed_application_driver_version(session, driver=driver, version="2.0.0")
    v1_id, v2_id = v1.id, v2.id
    for adv_id, name, container in (
        (v1_id, "server", None),
        (v2_id, "server", "simple-app"),
        (v2_id, "worker", "worker"),
    ):
        session.add(
            ComponentConfig(
                name=name,
                config={
                    "identifier": {"label": {"app.kubernetes.io/name": f"{name}-app"}},
                    "container": container,
                },
                application_driver_version_id=adv_id,
            )
        )
    await session.commit()
    return driver_name, v1_id, v2_id


async def _deploy(
    client: AsyncClient,
    session: AsyncSession,
    *,
    driver_name: str,
    driver_version_id: UUID,
) -> UUID:
    environment = await seed_environment(session)
    name = f"version-input-{uuid4().hex[:8]}"
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("deploy_with_driver_version"),
            "variables": {
                "driver": driver_name,
                "environmentId": str(environment.id),
                "name": name,
                "version": "1.0.0",
                "driverVersionId": str(driver_version_id),
            },
        },
    )
    assert response.status_code == 200
    assert "errors" not in response.json(), response.json()
    session.expire_all()
    return (
        await session.exec(select(Deployment.id).where(Deployment.name == name))
    ).one()


async def _update_version(
    client: AsyncClient,
    deployment_id: UUID,
    driver_version_id: UUID,
    update_input: dict[str, Any],
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    variables: dict[str, Any] = {
        "deploymentId": str(deployment_id),
        "version": "1.0.0",
        "driverVersionId": str(driver_version_id),
        "input": update_input,
    }
    if parameters is not None:
        variables["parameters"] = parameters
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment_version_with_input"),
            "variables": variables,
        },
    )
    assert response.status_code == 200
    return response.json()


def _component_env(name: str, key: str, value: str) -> dict[str, Any]:
    return {"name": name, "envVars": [{"name": key, "value": value}]}


async def _stored(session: AsyncSession, deployment_id: UUID) -> Deployment:
    session.expire_all()
    deployment = await session.get(Deployment, deployment_id)
    assert deployment is not None
    return deployment


@pytest.mark.asyncio
async def test_component_config_is_validated_against_the_target_version(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """Env vars on a component that gains a container, and on a component the
    target version adds, are accepted and written with the version in one task."""
    _arm_prefect(prefect_manager_mock)
    driver_name, v1_id, v2_id = await _seed_driver(session)
    deployment_id = await _deploy(
        client, session, driver_name=driver_name, driver_version_id=v1_id
    )

    payload = await _update_version(
        client,
        deployment_id,
        v2_id,
        {
            "components": [
                _component_env("server", "LOG_LEVEL", "debug"),
                _component_env("worker", "MODE", "fast"),
            ]
        },
    )

    assert "errors" not in payload, payload
    assert payload["data"]["updateDeploymentVersion"]["type"] == "upgrade_instance"
    stored = await _stored(session, deployment_id)
    assert stored.application_driver_version_id == v2_id
    assert stored.config["components"] == {
        "server": {"env_vars": {"LOG_LEVEL": "debug"}},
        "worker": {"env_vars": {"MODE": "fast"}},
    }
    tasks = await session.exec(select(Task).where(Task.deployment_id == deployment_id))
    assert len(tasks.all()) == 2  # the deploy and this update
    data = await gql(
        client,
        "get_deployment_component_env_vars",
        {"deploymentId": str(deployment_id)},
    )
    rows = {row["component"]: row for row in data["deployment"]["componentEnvVars"]}
    assert rows["server"]["isApplicable"] is True
    assert rows["worker"]["isApplicable"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("component", "code"),
    [
        ("server", "COMPONENT_CONTAINER_NOT_DECLARED"),
        ("worker", "UNKNOWN_COMPONENT_ENV_VAR"),
    ],
    ids=["container-dropped", "component-dropped"],
)
async def test_config_the_target_version_cannot_apply_is_rejected(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    component: str,
    code: str,
) -> None:
    """Moving to ``v1``, which declares no ``server`` container and no ``worker``,
    rejects new env vars on them and leaves the deployment unchanged."""
    _arm_prefect(prefect_manager_mock)
    driver_name, v1_id, v2_id = await _seed_driver(session)
    deployment_id = await _deploy(
        client, session, driver_name=driver_name, driver_version_id=v2_id
    )
    config_before = (await _stored(session, deployment_id)).config

    payload = await _update_version(
        client,
        deployment_id,
        v1_id,
        {"components": [_component_env(component, "LOG_LEVEL", "debug")]},
    )

    assert payload["errors"][0]["extensions"]["code"] == code, payload
    stored = await _stored(session, deployment_id)
    assert stored.application_driver_version_id == v2_id
    assert stored.config == config_before


@pytest.mark.asyncio
async def test_name_parameters_and_service_names_are_written_with_the_version(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """``input.parameters`` merge on top of the ``parameters`` argument and are
    validated against the target version; the renamed service reaches the
    upgraded instance's context."""
    _arm_prefect(prefect_manager_mock)
    driver_name, v1_id, v2_id = await _seed_driver(session)
    v2 = await session.get(ApplicationDriverVersion, v2_id)
    assert v2 is not None
    v2.parameters = [
        {"name": "replicas", "label": "Replicas", "kind": "integer", "default": 1},
        {"name": "label", "label": "Label", "kind": "string", "default": ""},
    ]
    v2.services = [
        {
            "name": "simple-app",
            "kind": "http",
            "scope": "internal",
            "port": 8080,
            "component": "server",
        }
    ]
    session.add(v2)
    await session.commit()
    deployment_id = await _deploy(
        client, session, driver_name=driver_name, driver_version_id=v1_id
    )
    new_name = f"renamed-{uuid4().hex[:8]}"

    payload = await _update_version(
        client,
        deployment_id,
        v2_id,
        {
            "name": new_name,
            "parameters": [{"name": "replicas", "value": 5}],
            "serviceNameOverrides": [
                {"driverServiceName": "simple-app", "overrideName": "simple-app-v2"}
            ],
        },
        parameters={"replicas": 2, "label": "baseline"},
    )

    assert "errors" not in payload, payload
    stored = await _stored(session, deployment_id)
    assert stored.name == new_name
    assert stored.parameters == {"replicas": 5, "label": "baseline"}
    instance = await session.get(
        ApplicationInstance, stored.active_application_instance_id
    )
    assert instance is not None
    resolved_names = {
        svc["resolved_name"] for svc in instance.context.get("deployed_services") or []
    }
    assert resolved_names == {"simple-app-v2"}
