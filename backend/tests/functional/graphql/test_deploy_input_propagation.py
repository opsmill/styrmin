"""GraphQL ↔ DB propagation tests for the ``deploy`` (create) mutation's
typed ``DeploymentConfigInput`` / ``[ParameterValueInput!]`` inputs (009).

The ``deploy`` mutation used to take a freeform ``JSON`` config + ``JSON``
parameters payload, while ``updateDeployment`` took a typed list-based input —
so the same manifest could be accepted on update but rejected on create (the
reported ``env_vars`` list-vs-dict mismatch). ``deploy`` now shares
``DeploymentConfigInput`` with ``updateDeployment`` and takes
``[ParameterValueInput!]`` for parameters, so both mutations accept an
identical configuration shape.

These tests prove the typed create inputs reach ``Deployment.config`` /
``Deployment.parameters`` after the resolver-side list→dict flatten — the
exact path the original error report exercised.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Deployment

from ._queries import load_query
from .conftest import gql
from .seeds import seed_application_driver_version, seed_deployment, seed_environment


async def _deploy(
    client: AsyncClient,
    *,
    driver: str,
    environment_id,
    config: dict | None = None,
    parameters: list[dict] | None = None,
) -> dict:
    """Run the ``deploy`` mutation and return the parsed JSON payload."""
    variables: dict = {
        "driver": driver,
        "version": "1.0.0",
        "environmentId": str(environment_id),
        "name": f"app-{uuid4().hex[:8]}",
    }
    if config is not None:
        variables["config"] = config
    if parameters is not None:
        variables["parameters"] = parameters
    response = await client.post(
        "/graphql",
        json={"query": load_query("deploy"), "variables": variables},
    )
    assert response.status_code == 200
    return response.json()


async def _created_deployment(session: AsyncSession) -> Deployment:
    """Return the single Deployment row created by a ``deploy`` call."""
    session.expire_all()
    rows = list((await session.exec(select(Deployment))).all())
    assert len(rows) == 1, f"expected exactly one deployment row, got {len(rows)}"
    return rows[0]


@pytest.mark.asyncio
async def test_deploy_env_vars_list_propagates_to_config(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
) -> None:
    """The reported scenario: ``config.envVars`` as a ``[{name, value}]`` list
    is accepted by the create mutation and flattened to the ``{name: value}``
    dict on ``Deployment.config.env_vars`` — the same shape ``updateDeployment``
    persists.
    """
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())

    await seed_application_driver_version(session, driver_name="deploy-cfg-driver")
    env = await seed_environment(session)

    payload = await _deploy(
        client,
        driver="deploy-cfg-driver",
        environment_id=env.id,
        config={"envVars": [{"name": "MY_ENV", "value": "value01"}]},
    )
    assert "errors" not in payload, payload
    assert payload["data"]["deploy"] is not None

    deployment = await _created_deployment(session)
    assert deployment.config == {"env_vars": {"MY_ENV": "value01"}}


@pytest.mark.asyncio
async def test_deploy_backup_ttl_propagates_to_config(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
) -> None:
    """``config.backupTtl`` at create time lands on ``Deployment.config``.

    016 / FR-005 (US2): the deployment scope is the deepest hop of the
    retention precedence chain, so an operator must be able to pin a
    longer-than-environment retention on a critical deployment at the
    moment it is deployed — not only via a follow-up update.
    """
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())

    await seed_application_driver_version(session, driver_name="deploy-ttl-driver")
    env = await seed_environment(session)

    payload = await _deploy(
        client,
        driver="deploy-ttl-driver",
        environment_id=env.id,
        config={"backupTtl": "8760h"},
    )
    assert "errors" not in payload, payload
    assert payload["data"]["deploy"] is not None

    deployment = await _created_deployment(session)
    assert deployment.config == {"backup_ttl": "8760h"}


@pytest.mark.asyncio
async def test_deploy_parameters_list_propagates(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
) -> None:
    """``parameters`` submitted as a ``[ParameterValueInput!]`` list flattens to
    the ``{name: value}`` dict on ``Deployment.parameters``.
    """
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())

    adv = await seed_application_driver_version(
        session, driver_name="deploy-param-driver"
    )
    adv.parameters = [
        {"name": "replicas", "label": "Replicas", "kind": "integer", "default": 1},
    ]
    session.add(adv)
    await session.commit()
    env = await seed_environment(session)

    payload = await _deploy(
        client,
        driver="deploy-param-driver",
        environment_id=env.id,
        parameters=[{"name": "replicas", "value": 3}],
    )
    assert "errors" not in payload, payload

    deployment = await _created_deployment(session)
    assert deployment.parameters == {"replicas": 3}


@pytest.mark.asyncio
async def test_deploy_deployment_ref_name_is_stored_as_the_id(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
) -> None:
    """``deploymentRef.deploymentName`` reaches ``Deployment.config`` as the named
    deployment's id, with no name, and the ``config`` read returns the same (027 FR-001)."""
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())

    adv = await seed_application_driver_version(
        session, driver_name="deploy-ref-driver"
    )
    env = await seed_environment(session)
    named = await seed_deployment(session, environment=env, adv=adv, name="db")

    payload = await _deploy(
        client,
        driver="deploy-ref-driver",
        environment_id=env.id,
        config={
            "scheduling": {
                "podAffinity": {
                    "required": [
                        {
                            "topologyKey": "kubernetes.io/hostname",
                            "deploymentRef": {"deploymentName": "db"},
                        }
                    ]
                }
            }
        },
    )
    assert "errors" not in payload, payload
    deployment_id = UUID(payload["data"]["deploy"]["deploymentId"])

    expected = {
        "scheduling": {
            "pod_affinity": {
                "required": [
                    {
                        "topology_key": "kubernetes.io/hostname",
                        "deployment_ref": {"deployment_id": str(named.id)},
                    }
                ]
            }
        }
    }
    session.expire_all()
    db_row = await session.get(Deployment, deployment_id)
    assert db_row is not None
    assert db_row.config == expected
    data = await gql(
        client, "get_deployment_config", {"deploymentId": str(deployment_id)}
    )
    assert data["deployment"]["config"] == expected
