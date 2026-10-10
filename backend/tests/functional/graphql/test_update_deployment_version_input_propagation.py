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
    DeployedService,
    Deployment,
    Task,
)

from ._queries import load_query
from .conftest import gql
from .seeds import seed_application_driver_version, seed_environment


_SERVICES = [
    {
        "name": "simple-app",
        "kind": "http",
        "scope": "internal",
        "port": 8080,
        "component": "server",
    }
]


def _arm_prefect(prefect_manager_mock: Any) -> None:
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())


async def _seed_driver(session: AsyncSession) -> tuple[str, UUID, UUID]:
    """Seed ``v1`` (``server`` without a container) and ``v2`` (``server`` and
    ``worker`` with containers) of one driver, both with one service."""
    v1 = await seed_application_driver_version(session, version="1.0.0")
    driver = await session.get(ApplicationDriver, v1.application_driver_id)
    assert driver is not None
    driver_name = driver.name
    v2 = await seed_application_driver_version(session, driver=driver, version="2.0.0")
    # One flush per row: a batched UPDATE of both fails on SQLite.
    for adv in (v1, v2):
        adv.services = _SERVICES
        session.add(adv)
        await session.flush()
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
    environment_id: UUID | None = None,
) -> UUID:
    if environment_id is None:
        environment_id = (await seed_environment(session)).id
    name = f"version-input-{uuid4().hex[:8]}"
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("deploy_with_driver_version"),
            "variables": {
                "driver": driver_name,
                "environmentId": str(environment_id),
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
    version: str = "1.0.0",
) -> dict[str, Any]:
    variables: dict[str, Any] = {
        "deploymentId": str(deployment_id),
        "version": version,
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


async def _task_count(session: AsyncSession, deployment_id: UUID) -> int:
    tasks = await session.exec(select(Task).where(Task.deployment_id == deployment_id))
    return len(tasks.all())


async def _service_ids(session: AsyncSession, deployment_id: UUID) -> set[UUID]:
    session.expire_all()
    rows = await session.exec(
        select(DeployedService.id).where(DeployedService.deployment_id == deployment_id)
    )
    return set(rows.all())


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
    assert await _task_count(session, deployment_id) == 2  # the deploy and this update
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
    ("update_input", "code", "message"),
    [
        (
            {"components": [_component_env("server", "LOG_LEVEL", "debug")]},
            "COMPONENT_CONTAINER_NOT_DECLARED",
            "version 1.0.0 (application version 1.0.0)",
        ),
        (
            {"components": [_component_env("worker", "LOG_LEVEL", "debug")]},
            "UNKNOWN_COMPONENT_ENV_VAR",
            "version 1.0.0 (application version 1.0.0)",
        ),
        (
            {
                "serviceNameOverrides": [
                    {"driverServiceName": "typo", "overrideName": "renamed"}
                ]
            },
            "VALIDATION_ERROR",
            "'typo' does not match any declared service",
        ),
    ],
    ids=["container-dropped", "component-dropped", "unknown-service"],
)
async def test_input_the_target_version_cannot_apply_is_rejected(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    update_input: dict[str, Any],
    code: str,
    message: str,
) -> None:
    """Moving to ``v1``, which declares no ``server`` container, no ``worker`` and no
    ``typo`` service, rejects the input, names the checked versions, writes nothing
    and starts no task and no flow run."""
    _arm_prefect(prefect_manager_mock)
    driver_name, v1_id, v2_id = await _seed_driver(session)
    deployment_id = await _deploy(
        client, session, driver_name=driver_name, driver_version_id=v2_id
    )
    config_before = (await _stored(session, deployment_id)).config
    tasks_before = await _task_count(session, deployment_id)
    services_before = await _service_ids(session, deployment_id)
    flow_runs_before = prefect_manager_mock.run_action.await_count

    payload = await _update_version(client, deployment_id, v1_id, update_input)

    assert payload["errors"][0]["extensions"]["code"] == code, payload
    assert message in payload["errors"][0]["message"]
    stored = await _stored(session, deployment_id)
    assert stored.application_driver_version_id == v2_id
    assert stored.config == config_before
    assert await _task_count(session, deployment_id) == tasks_before
    assert await _service_ids(session, deployment_id) == services_before
    assert prefect_manager_mock.run_action.await_count == flow_runs_before


@pytest.mark.asyncio
async def test_image_override_invalid_at_the_target_application_version_is_rejected(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """An image override is checked at the target application version: a ``+`` in
    the version cannot be part of a tag."""
    _arm_prefect(prefect_manager_mock)
    driver_name, _v1_id, v2_id = await _seed_driver(session)
    deployment_id = await _deploy(
        client, session, driver_name=driver_name, driver_version_id=v2_id
    )
    tasks_before = await _task_count(session, deployment_id)

    payload = await _update_version(
        client,
        deployment_id,
        v2_id,
        {
            "components": [
                {"name": "server", "image": "registry.example/app:{{ app.version }}"}
            ]
        },
        version="1.0.0+build",
    )

    assert payload["errors"][0]["extensions"]["code"] == "INVALID_IMAGE_REFERENCE"
    stored = await _stored(session, deployment_id)
    assert stored.application_version == "1.0.0"
    assert not (stored.config or {}).get("components")
    assert await _task_count(session, deployment_id) == tasks_before


@pytest.mark.asyncio
async def test_name_used_in_the_environment_is_rejected(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """A rename to the name of another deployment of the environment is rejected
    before the version or the binding changes."""
    _arm_prefect(prefect_manager_mock)
    driver_name, v1_id, v2_id = await _seed_driver(session)
    environment_id = (await seed_environment(session)).id
    first_id = await _deploy(
        client,
        session,
        driver_name=driver_name,
        driver_version_id=v1_id,
        environment_id=environment_id,
    )
    taken_name = (await _stored(session, first_id)).name
    # The second deployment needs its own service name in the environment.
    v1 = await session.get(ApplicationDriverVersion, v1_id)
    assert v1 is not None
    v1.services = None
    session.add(v1)
    await session.commit()
    second_id = await _deploy(
        client,
        session,
        driver_name=driver_name,
        driver_version_id=v1_id,
        environment_id=environment_id,
    )
    tasks_before = await _task_count(session, second_id)

    payload = await _update_version(client, second_id, v2_id, {"name": taken_name})

    assert payload["errors"][0]["extensions"]["code"] == "ALREADY_EXISTS", payload
    stored = await _stored(session, second_id)
    assert stored.name != taken_name
    assert stored.application_driver_version_id == v1_id
    assert await _task_count(session, second_id) == tasks_before


@pytest.mark.asyncio
async def test_rename_at_the_current_version_is_kept_without_a_task(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """The name is not part of the instance, so a rename alone returns ``null`` and
    starts no task, but the new name is written, as on ``updateDeployment``."""
    _arm_prefect(prefect_manager_mock)
    driver_name, v1_id, _v2_id = await _seed_driver(session)
    deployment_id = await _deploy(
        client, session, driver_name=driver_name, driver_version_id=v1_id
    )
    tasks_before = await _task_count(session, deployment_id)
    status_before = (await _stored(session, deployment_id)).status
    new_name = f"renamed-{uuid4().hex[:8]}"

    payload = await _update_version(client, deployment_id, v1_id, {"name": new_name})

    assert "errors" not in payload, payload
    assert payload["data"]["updateDeploymentVersion"] is None
    stored = await _stored(session, deployment_id)
    assert stored.name == new_name
    assert stored.status == status_before
    assert await _task_count(session, deployment_id) == tasks_before


@pytest.mark.asyncio
async def test_config_change_at_the_current_version_is_an_update(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """Without a new application version or driver binding, the task is an
    ``update_instance`` and the deployment goes to ``pending``, as on
    ``updateDeployment``."""
    _arm_prefect(prefect_manager_mock)
    driver_name, _v1_id, v2_id = await _seed_driver(session)
    deployment_id = await _deploy(
        client, session, driver_name=driver_name, driver_version_id=v2_id
    )

    payload = await _update_version(
        client,
        deployment_id,
        v2_id,
        {"components": [_component_env("server", "LOG_LEVEL", "debug")]},
    )

    assert "errors" not in payload, payload
    assert payload["data"]["updateDeploymentVersion"]["type"] == "update_instance"
    stored = await _stored(session, deployment_id)
    assert stored.status == "pending"
    assert stored.config["components"] == {
        "server": {"env_vars": {"LOG_LEVEL": "debug"}}
    }


@pytest.mark.asyncio
async def test_noop_keeps_the_deployed_services(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """A call that changes nothing returns ``null`` and leaves the deployed
    services as they are, instead of recreating them."""
    _arm_prefect(prefect_manager_mock)
    driver_name, v1_id, _v2_id = await _seed_driver(session)
    deployment_id = await _deploy(
        client, session, driver_name=driver_name, driver_version_id=v1_id
    )
    name = (await _stored(session, deployment_id)).name
    services_before = await _service_ids(session, deployment_id)
    tasks_before = await _task_count(session, deployment_id)
    assert services_before

    payload = await _update_version(client, deployment_id, v1_id, {"name": name})

    assert "errors" not in payload, payload
    assert payload["data"]["updateDeploymentVersion"] is None
    assert await _service_ids(session, deployment_id) == services_before
    assert await _task_count(session, deployment_id) == tasks_before


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
