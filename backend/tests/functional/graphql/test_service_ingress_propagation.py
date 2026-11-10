"""GraphQL ↔ DB propagation tests for the per-service ingress override (#598, T023).

Constitution §V: ``ServiceConfigInput`` written through ``updateDeployment``, ``deploy`` and
``updateDeploymentVersion(input:)`` reaches ``Deployment.config["services"]`` through the real
service and repository layers. The output fields (the stored overrides on ``Deployment`` and the
effective class and suffix on ``DeployedService``) project the persisted state.

Written before the implementation (T027, T028). Source: ``specs/033-service-ingress-override/``
``contracts/graphql-and-manifest.md``, ``data-model.md`` and FR-006.

Names assumed from the contract (the contract says its names are a proposal, and ``schema.graphql``
is the authority after T029):

* input ``ServiceConfigInput { name, ingressClass, fqdnSuffix }`` and ``DeploymentConfigInput.services``;
* output ``Deployment.services { name ingressClass fqdnSuffix }`` for the stored overrides (the
  contract says "on the deployment config type", but ``Deployment.config`` is untyped JSON, so the
  typed output has no other home than ``Deployment``);
* ``DeployedService.ingressClass``, ``ingressClassOverridden``, ``fqdnSuffixOverridden``.

The writes reuse the existing operation files and put ``services`` in the variables, so no
operation file names a field that ``schema.graphql`` does not have yet and ``uv run invoke
validate-graphql`` stays green. The reads of the new output fields cannot be a ``.graphql`` file
before T029 regenerates the schema; ``_read_deployment`` adds the new selections to an existing
operation through the ``graphql`` AST, as ``dev/guides/graphql-propagation-tests.md`` does for a
removed argument. T029 replaces this helper with ``.graphql`` files.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import graphql
import pytest
from graphql import FieldNode, NameNode, OperationDefinitionNode, SelectionSetNode
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
    Cluster,
    DeployedService,
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

ENVIRONMENT_NAME = "prod"
CLUSTER_SUFFIX = "test.styrmin.com"
CLUSTER_CLASS = "traefik"
OVERRIDE_CLASS = "tailscale"
OVERRIDE_SUFFIX = "tailnet.example.ts.net"

# ``infrahub`` is internal, ``task-manager`` and ``api`` are external.
DECLARED_SERVICES: list[dict[str, Any]] = [
    {
        "name": "infrahub",
        "kind": "http",
        "scope": "internal",
        "port": 8000,
        "component": "server",
    },
    {
        "name": "task-manager",
        "kind": "http",
        "scope": "external",
        "port": 4200,
        "component": "task-manager",
    },
    {
        "name": "api",
        "kind": "http",
        "scope": "external",
        "port": 9000,
        "component": "server",
    },
]

TASK_MANAGER_OVERRIDE_INPUT = {
    "name": "task-manager",
    "ingressClass": OVERRIDE_CLASS,
    "fqdnSuffix": OVERRIDE_SUFFIX,
}
TASK_MANAGER_OVERRIDE_STORED = {
    "ingress_class": OVERRIDE_CLASS,
    "fqdn_suffix": OVERRIDE_SUFFIX,
}


def _arm_prefect(prefect_manager_mock: Any) -> None:
    """Give the Prefect manager concrete return values, as the replica tests do."""
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())


async def _seed_environment(session: AsyncSession):
    """An environment named ``prod`` on a cluster that resolves a suffix and an ingress class."""
    environment = await seed_environment(session, name=ENVIRONMENT_NAME)
    cluster = await session.get(Cluster, environment.cluster_id)
    assert cluster is not None
    cluster.config = {
        **(cluster.config or {}),
        "fqdn_suffix": CLUSTER_SUFFIX,
        "ingress_class": CLUSTER_CLASS,
    }
    session.add(cluster)
    await session.commit()
    return environment


async def _seed_deployment(
    session: AsyncSession, config: dict[str, Any] | None = None
) -> UUID:
    """Seed a deployment whose driver version declares ``DECLARED_SERVICES``, with one
    ``DeployedService`` row for each, as ``deploy`` creates them."""
    environment = await _seed_environment(session)
    adv = await seed_application_driver_version(session)
    adv.services = DECLARED_SERVICES
    session.add(adv)
    await session.commit()
    deployment = await seed_deployment(session, environment=environment, adv=adv)
    for declared in DECLARED_SERVICES:
        session.add(
            DeployedService(
                driver_service_name=declared["name"],
                resolved_name=declared["name"],
                kind=declared["kind"],
                scope=declared["scope"],
                port=declared["port"],
                component=declared["component"],
                deployment_id=deployment.id,
                environment_id=environment.id,
            )
        )
    if config is not None:
        deployment.config = config
        session.add(deployment)
    await session.commit()
    return deployment.id


async def _seed_deploy_driver(session: AsyncSession) -> tuple[str, UUID]:
    """A driver version declaring ``DECLARED_SERVICES`` and an environment, for ``deploy``."""
    environment = await _seed_environment(session)
    environment_id = environment.id
    adv = await seed_application_driver_version(session, version="1.0.0")
    adv.services = DECLARED_SERVICES
    session.add(adv)
    await session.commit()
    driver = await session.get(ApplicationDriver, adv.application_driver_id)
    assert driver is not None
    return driver.name, environment_id


async def _seed_target_driver_version(
    session: AsyncSession, deployment_id: UUID
) -> UUID:
    """Version ``2.0.0`` of the deployment's driver, declaring the same services."""
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
    target.services = DECLARED_SERVICES
    session.add(target)
    await session.commit()
    return target.id


async def _post(
    client: AsyncClient, operation: str, variables: dict[str, Any]
) -> dict[str, Any]:
    response = await client.post(
        "/graphql", json={"query": load_query(operation), "variables": variables}
    )
    assert response.status_code == 200
    return response.json()


async def _post_update(
    client: AsyncClient, deployment_id: UUID, config: dict[str, Any]
) -> dict[str, Any]:
    return await _post(
        client,
        "update_deployment_config",
        {"deploymentId": str(deployment_id), "input": config},
    )


async def _post_deploy(
    client: AsyncClient,
    driver_name: str,
    environment_id: UUID,
    config: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    name = f"service-ingress-deploy-{uuid4().hex[:8]}"
    payload = await _post(
        client,
        "deploy_with_config",
        {
            "driver": driver_name,
            "environmentId": str(environment_id),
            "version": "1.0.0",
            "name": name,
            "config": config,
        },
    )
    return name, payload


async def _post_update_version(
    client: AsyncClient,
    deployment_id: UUID,
    driver_version_id: UUID,
    config: dict[str, Any],
) -> dict[str, Any]:
    """``updateDeploymentVersion`` with ``input``, what ``styrminctl deployments apply`` sends."""
    return await _post(
        client,
        "update_deployment_version_with_input",
        {
            "deploymentId": str(deployment_id),
            "version": "1.0.0",
            "driverVersionId": str(driver_version_id),
            "input": config,
        },
    )


async def _stored_row(session: AsyncSession, deployment_id: UUID) -> Deployment:
    # Fresh SELECT: ``session.get`` would return the stale identity-map object.
    session.expire_all()
    return (
        await session.exec(select(Deployment).where(Deployment.id == deployment_id))
    ).one()


async def _stored_services(
    session: AsyncSession, deployment_id: UUID
) -> dict[str, Any] | None:
    """The stored ``config["services"]`` with unset (``None``) fields removed from each block."""
    row = await _stored_row(session, deployment_id)
    services = (row.config or {}).get("services")
    if services is None:
        return None
    return {
        name: {key: value for key, value in block.items() if value is not None}
        for name, block in services.items()
    }


async def _task_count(session: AsyncSession, deployment_id: UUID) -> int:
    rows = await session.exec(select(Task).where(Task.deployment_id == deployment_id))
    return len(rows.all())


def _field(name: str, *children: str) -> FieldNode:
    return FieldNode(
        name=NameNode(value=name),
        selection_set=SelectionSetNode(
            selections=tuple(FieldNode(name=NameNode(value=c)) for c in children)
        )
        if children
        else None,
    )


async def _read_deployment(
    client: AsyncClient, deployment_id: UUID, *selections: FieldNode
) -> dict[str, Any]:
    """Read ``deployment(deploymentId:)`` through ``get_deployment_config`` plus ``selections``.

    The operation is parsed from its file and the selections are added through the AST, so the
    request is valid against the live schema only when the planned output fields exist. The
    request fails with a GraphQL validation error until T028 adds them.
    """
    document = graphql.parse(load_query("get_deployment_config"))
    [operation] = document.definitions
    assert isinstance(operation, OperationDefinitionNode)
    [deployment_field] = operation.selection_set.selections
    assert isinstance(deployment_field, FieldNode)
    assert deployment_field.selection_set is not None
    deployment_field.selection_set = SelectionSetNode(
        selections=(*deployment_field.selection_set.selections, *selections)
    )
    response = await client.post(
        "/graphql",
        json={
            "query": graphql.print_ast(document),
            "variables": {"deploymentId": str(deployment_id)},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    return payload["data"]["deployment"]


STORED_SERVICES_FIELD = _field("services", "name", "ingressClass", "fqdnSuffix")
DEPLOYED_SERVICES_FIELD = _field(
    "deployedServices",
    "driverServiceName",
    "scope",
    "ingressClass",
    "ingressClassOverridden",
    "fqdnSuffixOverridden",
    "humanReadableFqdn",
    "humanReadableUrl",
    "primaryFqdn",
)


def _by_name(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {row[key]: row for row in rows}


# ---------------------------------------------------------------------------
# Writes: the three mutations store the override in Deployment.config["services"]
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_deployment_stores_the_override(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """``updateDeployment`` stores class and suffix under the driver service name, and nothing else."""
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_deployment(session)

    payload = await _post_update(
        client, deployment_id, {"services": [TASK_MANAGER_OVERRIDE_INPUT]}
    )

    assert "errors" not in payload, payload
    row = await _stored_row(session, deployment_id)
    assert row.config == {"services": {"task-manager": TASK_MANAGER_OVERRIDE_STORED}}
    assert await _task_count(session, deployment_id) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("override_input", "stored"),
    [
        (
            {"name": "task-manager", "ingressClass": OVERRIDE_CLASS},
            {"ingress_class": OVERRIDE_CLASS},
        ),
        (
            {"name": "task-manager", "fqdnSuffix": OVERRIDE_SUFFIX},
            {"fqdn_suffix": OVERRIDE_SUFFIX},
        ),
    ],
    ids=["class-only", "suffix-only"],
)
async def test_update_deployment_stores_a_one_field_override(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    override_input: dict[str, Any],
    stored: dict[str, Any],
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_deployment(session)

    payload = await _post_update(client, deployment_id, {"services": [override_input]})

    assert "errors" not in payload, payload
    assert await _stored_services(session, deployment_id) == {"task-manager": stored}


@pytest.mark.asyncio
async def test_update_deployment_stores_one_block_for_each_service(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_deployment(session)

    payload = await _post_update(
        client,
        deployment_id,
        {
            "services": [
                TASK_MANAGER_OVERRIDE_INPUT,
                {"name": "api", "ingressClass": "other-class"},
            ]
        },
    )

    assert "errors" not in payload, payload
    assert await _stored_services(session, deployment_id) == {
        "task-manager": TASK_MANAGER_OVERRIDE_STORED,
        "api": {"ingress_class": "other-class"},
    }


@pytest.mark.asyncio
async def test_update_deployment_row_with_both_fields_null_stores_no_override(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """data-model: a block with both fields ``None`` is the same as no override."""
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_deployment(
        session, config={"services": {"api": {"ingress_class": "other-class"}}}
    )

    payload = await _post_update(
        client,
        deployment_id,
        {"services": [{"name": "task-manager"}, {"name": "api", "ingressClass": None}]},
    )

    assert "errors" not in payload, payload
    assert not await _stored_services(session, deployment_id)


@pytest.mark.asyncio
async def test_update_deployment_list_without_a_service_clears_its_override(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """Full replacement (user story 1, scenario 2): a service that is not in the list loses its override."""
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_deployment(
        session,
        config={
            "services": {
                "task-manager": TASK_MANAGER_OVERRIDE_STORED,
                "api": {"ingress_class": "other-class"},
            }
        },
    )

    payload = await _post_update(
        client,
        deployment_id,
        {"services": [{"name": "api", "ingressClass": "other-class"}]},
    )

    assert "errors" not in payload, payload
    assert await _stored_services(session, deployment_id) == {
        "api": {"ingress_class": "other-class"}
    }


@pytest.mark.asyncio
async def test_update_deployment_empty_list_clears_every_override(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_deployment(
        session, config={"services": {"task-manager": TASK_MANAGER_OVERRIDE_STORED}}
    )

    payload = await _post_update(client, deployment_id, {"services": []})

    assert "errors" not in payload, payload
    assert not await _stored_services(session, deployment_id)


@pytest.mark.asyncio
async def test_update_deployment_omitting_services_clears_them(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """Full replacement of the config: a write with another config field and no ``services`` clears
    the overrides (contract, research D-009)."""
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_deployment(
        session, config={"services": {"task-manager": TASK_MANAGER_OVERRIDE_STORED}}
    )

    payload = await _post_update(client, deployment_id, {"ipWhitelist": ["10.0.0.0/8"]})

    assert "errors" not in payload, payload
    row = await _stored_row(session, deployment_id)
    assert row.config == {"ip_whitelist": ["10.0.0.0/8"]}


@pytest.mark.asyncio
async def test_deploy_persists_the_override(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """``deploy(config: {services: [...]})`` stores the override on the new deployment."""
    _arm_prefect(prefect_manager_mock)
    driver_name, environment_id = await _seed_deploy_driver(session)

    name, payload = await _post_deploy(
        client, driver_name, environment_id, {"services": [TASK_MANAGER_OVERRIDE_INPUT]}
    )

    assert "errors" not in payload, payload
    session.expire_all()
    created = (
        await session.exec(select(Deployment).where(Deployment.name == name))
    ).one()
    assert created.config["services"] == {"task-manager": TASK_MANAGER_OVERRIDE_STORED}


@pytest.mark.asyncio
async def test_update_deployment_version_input_persists_the_override(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """``updateDeploymentVersion(input:)`` stores the override together with the driver version change."""
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_deployment(session)
    target_id = await _seed_target_driver_version(session, deployment_id)

    payload = await _post_update_version(
        client, deployment_id, target_id, {"services": [TASK_MANAGER_OVERRIDE_INPUT]}
    )

    assert "errors" not in payload, payload
    row = await _stored_row(session, deployment_id)
    assert row.application_driver_version_id == target_id
    assert row.config == {"services": {"task-manager": TASK_MANAGER_OVERRIDE_STORED}}
    assert await _task_count(session, deployment_id) == 1


@pytest.mark.asyncio
async def test_update_deployment_version_input_without_services_clears_them(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """``apply`` of a manifest with a ``config`` and no ``services`` clears the stored overrides."""
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_deployment(
        session, config={"services": {"task-manager": TASK_MANAGER_OVERRIDE_STORED}}
    )
    target_id = await _seed_target_driver_version(session, deployment_id)

    payload = await _post_update_version(
        client, deployment_id, target_id, {"ipWhitelist": ["10.0.0.0/8"]}
    )

    assert "errors" not in payload, payload
    row = await _stored_row(session, deployment_id)
    assert row.config == {"ip_whitelist": ["10.0.0.0/8"]}


# ---------------------------------------------------------------------------
# Reads: the output fields project the stored state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deployment_services_field_reads_the_stored_overrides(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment_id = await _seed_deployment(
        session,
        config={
            "services": {
                "task-manager": TASK_MANAGER_OVERRIDE_STORED,
                "api": {"ingress_class": "other-class"},
            }
        },
    )

    deployment = await _read_deployment(client, deployment_id, STORED_SERVICES_FIELD)

    assert _by_name(deployment["services"], "name") == {
        "task-manager": {
            "name": "task-manager",
            "ingressClass": OVERRIDE_CLASS,
            "fqdnSuffix": OVERRIDE_SUFFIX,
        },
        "api": {"name": "api", "ingressClass": "other-class", "fqdnSuffix": None},
    }


@pytest.mark.asyncio
async def test_deployment_services_field_is_empty_without_an_override(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment_id = await _seed_deployment(session)

    deployment = await _read_deployment(client, deployment_id, STORED_SERVICES_FIELD)

    assert not deployment["services"]


@pytest.mark.asyncio
async def test_deployment_config_json_reads_the_stored_overrides(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The untyped ``config`` field, which the CLI and the UI read today, returns the stored block."""
    deployment_id = await _seed_deployment(
        session, config={"services": {"task-manager": TASK_MANAGER_OVERRIDE_STORED}}
    )

    data = await gql(
        client, "get_deployment_config", {"deploymentId": str(deployment_id)}
    )

    assert data["deployment"]["config"]["services"] == {
        "task-manager": TASK_MANAGER_OVERRIDE_STORED
    }


@pytest.mark.asyncio
async def test_deployed_service_reads_the_override_and_marks_it(
    client: AsyncClient, session: AsyncSession
) -> None:
    """FR-006: the readable host and URL of the overridden service use the override suffix, the other
    services keep the resolved suffix and class, and ``primaryFqdn`` is unchanged (research D-003)."""
    deployment_id = await _seed_deployment(
        session, config={"services": {"task-manager": TASK_MANAGER_OVERRIDE_STORED}}
    )

    deployment = await _read_deployment(client, deployment_id, DEPLOYED_SERVICES_FIELD)

    services = _by_name(deployment["deployedServices"], "driverServiceName")
    primary_fqdn = services["api"]["primaryFqdn"]
    assert primary_fqdn is not None
    assert primary_fqdn.endswith(f".{CLUSTER_SUFFIX}")
    assert services["task-manager"] == {
        "driverServiceName": "task-manager",
        "scope": "external",
        "ingressClass": OVERRIDE_CLASS,
        "ingressClassOverridden": True,
        "fqdnSuffixOverridden": True,
        "humanReadableFqdn": f"task-manager-{ENVIRONMENT_NAME}.{OVERRIDE_SUFFIX}",
        "humanReadableUrl": f"https://task-manager-{ENVIRONMENT_NAME}.{OVERRIDE_SUFFIX}",
        "primaryFqdn": primary_fqdn,
    }
    assert services["api"]["ingressClass"] == CLUSTER_CLASS
    assert services["api"]["ingressClassOverridden"] is False
    assert services["api"]["fqdnSuffixOverridden"] is False
    assert services["api"]["humanReadableFqdn"] == (
        f"api-{ENVIRONMENT_NAME}.{CLUSTER_SUFFIX}"
    )
    assert services["api"]["humanReadableUrl"] == (
        f"https://api-{ENVIRONMENT_NAME}.{CLUSTER_SUFFIX}"
    )


@pytest.mark.asyncio
async def test_deployed_service_marks_only_the_field_that_is_overridden(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment_id = await _seed_deployment(
        session,
        config={"services": {"task-manager": {"fqdn_suffix": OVERRIDE_SUFFIX}}},
    )

    deployment = await _read_deployment(client, deployment_id, DEPLOYED_SERVICES_FIELD)

    task_manager = _by_name(deployment["deployedServices"], "driverServiceName")[
        "task-manager"
    ]
    assert task_manager["ingressClass"] == CLUSTER_CLASS
    assert task_manager["ingressClassOverridden"] is False
    assert task_manager["fqdnSuffixOverridden"] is True
    assert task_manager["humanReadableFqdn"] == (
        f"task-manager-{ENVIRONMENT_NAME}.{OVERRIDE_SUFFIX}"
    )


@pytest.mark.asyncio
async def test_deployed_service_without_an_override_reads_the_resolved_values(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment_id = await _seed_deployment(session)

    deployment = await _read_deployment(client, deployment_id, DEPLOYED_SERVICES_FIELD)

    services = _by_name(deployment["deployedServices"], "driverServiceName")
    for name in ("task-manager", "api"):
        assert services[name]["ingressClass"] == CLUSTER_CLASS
        assert services[name]["ingressClassOverridden"] is False
        assert services[name]["fqdnSuffixOverridden"] is False
        assert services[name]["humanReadableFqdn"] == (
            f"{name}-{ENVIRONMENT_NAME}.{CLUSTER_SUFFIX}"
        )


@pytest.mark.asyncio
async def test_deployed_service_ingress_class_is_null_for_an_internal_service(
    client: AsyncClient, session: AsyncSession
) -> None:
    """contract: ``ingressClass`` is null for a service that is not external."""
    deployment_id = await _seed_deployment(session)

    deployment = await _read_deployment(client, deployment_id, DEPLOYED_SERVICES_FIELD)

    infrahub = _by_name(deployment["deployedServices"], "driverServiceName")["infrahub"]
    assert infrahub["scope"] == "internal"
    assert infrahub["ingressClass"] is None
    assert infrahub["ingressClassOverridden"] is False
    assert infrahub["fqdnSuffixOverridden"] is False
