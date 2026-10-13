"""GraphQL to database propagation tests for ``updateCluster`` (021-cluster-config-update).

Each test drives the mutation over HTTP, then reads the ``cluster`` row back
through the database session. See ``specs/archive/021-cluster-config-update/contracts/graphql.md``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.context.models.config import ClusterConfig
from styrmin_backend.db.models import Cluster, Role, Task, TaskType
from styrmin_backend.services.auth.session import create_session

from ._queries import load_query
from .conftest import gql
from .seeds import (
    seed_application_driver_version,
    seed_cluster,
    seed_deployment,
    seed_environment,
    seed_user,
)

FULL_INPUT: dict[str, Any] = {
    "ingressClass": "nginx",
    "runtimeClass": "gvisor",
    "nodeSelector": "pool=apps",
    "fqdnSuffix": "apps.example.com",
    "externalUrlScheme": "HTTP",
    "externalUrlPort": 8443,
    "externalDnsEndpointsType": "NODE_EXTERNAL_IP",
    "dedicatedIngress": {
        "implementation": "traefik",
        "type": "ingress",
        "service": {
            "type": "NodePort",
            "annotations": {"lb.example.com/reuse": "true"},
            "loadBalancerIp": "10.0.0.10",
            "externalTrafficPolicy": "Local",
            "ipFamilies": ["IPv4"],
            "ipFamilyPolicy": "SingleStack",
            "nodePort": 30443,
        },
    },
    "standardStorage": {"storageClass": "standard-rwo"},
    "fastStorage": {"storageClass": "local-nvme"},
    "scheduling": {
        "tolerations": [
            {
                "key": "dedicated",
                "operator": "EQUAL",
                "value": "apps",
                "effect": "NO_SCHEDULE",
            }
        ],
        "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}},
        "runtimeClass": "kata",
    },
    "dbSize": "10Gi",
    "backupTtl": "720h",
}

FULL_CONFIG: dict[str, Any] = {
    "ingress_class": "nginx",
    "runtime_class": "gvisor",
    "node_selector": "pool=apps",
    "fqdn_suffix": "apps.example.com",
    "external_url_scheme": "http",
    "external_url_port": 8443,
    "external_dns_endpoints_type": "NodeExternalIP",
    "dedicated_ingress": {
        "implementation": "traefik",
        "type": "ingress",
        "service": {
            "type": "NodePort",
            "annotations": {"lb.example.com/reuse": "true"},
            "load_balancer_ip": "10.0.0.10",
            "external_traffic_policy": "Local",
            "ip_families": ["IPv4"],
            "ip_family_policy": "SingleStack",
            "node_port": 30443,
        },
    },
    "standard_storage": {"storage_class": "standard-rwo"},
    "fast_storage": {"storage_class": "local-nvme"},
    "scheduling": {
        "tolerations": [
            {
                "key": "dedicated",
                "operator": "Equal",
                "value": "apps",
                "effect": "NoSchedule",
            }
        ],
        "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}},
        "runtime_class": "kata",
    },
    "db_size": "10Gi",
    "backup_ttl": "720h",
}


async def _post_update(
    client: AsyncClient, variables: dict[str, Any], **kwargs: Any
) -> dict[str, Any]:
    response = await client.post(
        "/graphql",
        json={"query": load_query("update_cluster"), "variables": variables},
        **kwargs,
    )
    assert response.status_code == 200
    return response.json()


async def _stored_cluster(session: AsyncSession, cluster_id: UUID) -> Cluster:
    session.expire_all()
    row = await session.get(Cluster, cluster_id)
    assert row is not None
    return row


def test_update_cluster_input_covers_every_cluster_config_field() -> None:
    """Every ``ClusterConfig`` field has an ``UpdateClusterInput`` field of the same name, and no more."""
    from styrmin_backend.api.definitions.cluster.inputs import UpdateClusterInput

    input_fields = {
        f.python_name for f in UpdateClusterInput.__strawberry_definition__.fields
    }
    assert input_fields == set(ClusterConfig.model_fields)


@pytest.mark.asyncio
async def test_update_cluster_persists_every_input_field(
    client: AsyncClient, session: AsyncSession
) -> None:
    cluster = await seed_cluster(session)

    data = await gql(
        client,
        "update_cluster",
        {"clusterId": str(cluster.id), "input": FULL_INPUT},
    )

    assert data["updateCluster"]["cluster"]["id"] == str(cluster.id)
    assert data["updateCluster"]["cluster"]["config"] == FULL_CONFIG
    stored = await _stored_cluster(session, cluster.id)
    assert stored.config == FULL_CONFIG
    ClusterConfig.model_validate(stored.config)


@pytest.mark.asyncio
async def test_update_cluster_clears_omitted_fields_and_applies_defaults(
    client: AsyncClient, session: AsyncSession
) -> None:
    cluster = await seed_cluster(session)
    cluster.config = {
        "ingress_class": "nginx",
        "runtime_class": "gvisor",
        "fqdn_suffix": "old.example.com",
        "standard_storage": {"storage_class": "old-class"},
        "dedicated_ingress": {},
    }
    session.add(cluster)
    await session.commit()

    data = await gql(
        client,
        "update_cluster",
        {"clusterId": str(cluster.id), "input": {"nodeSelector": "pool=apps"}},
    )

    expected = {
        "node_selector": "pool=apps",
        "ingress_class": "traefik",
        "runtime_class": "default",
    }
    assert data["updateCluster"]["cluster"]["config"] == expected
    stored = await _stored_cluster(session, cluster.id)
    assert stored.config == expected


@pytest.mark.asyncio
async def test_update_cluster_recomputes_capabilities(
    client: AsyncClient, session: AsyncSession
) -> None:
    cluster = await seed_cluster(session)
    assert not cluster.capabilities

    data = await gql(
        client,
        "update_cluster",
        {
            "clusterId": str(cluster.id),
            "input": {
                "fqdnSuffix": "apps.example.com",
                "standardStorage": {"storageClass": "standard-rwo"},
                "fastStorage": {"storageClass": "local-nvme"},
            },
        },
    )

    expected = {
        "ingress": {
            "external": {"ingress_class": "traefik", "fqdn_suffix": "apps.example.com"}
        },
        "storage": {
            "standard": {"storage_class": "standard-rwo"},
            "fast": {"storage_class": "local-nvme"},
        },
    }
    assert data["updateCluster"]["cluster"]["capabilities"] == expected
    assert (await _stored_cluster(session, cluster.id)).capabilities == expected
    read_back = await gql(
        client, "get_cluster_capabilities", {"clusterId": str(cluster.id)}
    )
    assert read_back["cluster"]["capabilities"] == expected

    # Removing the FQDN suffix and the storage removes those capabilities.
    data = await gql(
        client, "update_cluster", {"clusterId": str(cluster.id), "input": {}}
    )
    assert data["updateCluster"]["cluster"]["capabilities"] == {}
    assert not (await _stored_cluster(session, cluster.id)).capabilities


@pytest.mark.asyncio
async def test_update_cluster_by_name(
    client: AsyncClient, session: AsyncSession
) -> None:
    cluster = await seed_cluster(session, name="by-name")

    data = await gql(
        client,
        "update_cluster",
        {"clusterName": "by-name", "input": {"fqdnSuffix": "apps.example.com"}},
    )

    assert data["updateCluster"]["cluster"]["id"] == str(cluster.id)
    stored = await _stored_cluster(session, cluster.id)
    assert stored.config is not None
    assert stored.config["fqdn_suffix"] == "apps.example.com"


@pytest.mark.asyncio
async def test_update_cluster_dry_run_lists_the_redeploys_and_saves_nothing(
    client: AsyncClient, session: AsyncSession
) -> None:
    cluster = await seed_cluster(session)
    original = dict(cluster.config or {})
    environment = await seed_environment(session, cluster=cluster, name="staging")
    deployment = await seed_deployment(session, environment=environment, name="web")
    cluster_id = cluster.id
    environment_id = environment.id
    deployment_id = deployment.id

    data = await gql(
        client,
        "update_cluster",
        {
            "clusterId": str(cluster_id),
            "input": {"fqdnSuffix": "apps.example.com"},
            "dryRun": True,
        },
    )

    result = data["updateCluster"]
    assert result["dryRun"] is True
    assert result["cluster"]["config"] == original
    assert result["redeployed"] == [
        {
            "deploymentId": str(deployment_id),
            "deploymentName": "web",
            "environmentId": str(environment_id),
            "environmentName": "staging",
            "taskId": None,
        }
    ]
    assert result["failedToStart"] == []
    assert result["unchangedCount"] == 0
    stored = await _stored_cluster(session, cluster_id)
    assert stored.config == original
    tasks = (
        await session.exec(select(Task).where(Task.deployment_id == deployment_id))
    ).all()
    assert tasks == []


@pytest.mark.asyncio
async def test_update_cluster_unknown_cluster_returns_not_found(
    client: AsyncClient,
) -> None:
    payload = await _post_update(
        client, {"clusterName": "missing", "input": {"fqdnSuffix": "x.example.com"}}
    )

    error = payload["errors"][0]
    assert error["extensions"]["code"] == "NOT_FOUND", payload
    assert "missing" in error["message"], payload
    assert error["path"] == ["updateCluster"], payload


@pytest.mark.asyncio
async def test_update_cluster_invalid_config_is_refused_and_not_saved(
    client: AsyncClient, session: AsyncSession
) -> None:
    cluster = await seed_cluster(session)
    # The service rolls back on the error, which expires ``cluster``; read its values first.
    cluster_id = cluster.id
    original = dict(cluster.config or {})

    payload = await _post_update(
        client, {"clusterId": str(cluster_id), "input": {"externalUrlPort": 70000}}
    )

    error = payload["errors"][0]
    assert error["extensions"]["code"] == "VALIDATION_ERROR", payload
    assert "external_url_port" in error["message"], payload
    assert error["path"] == ["updateCluster"], payload
    assert (await _stored_cluster(session, cluster_id)).config == original


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", [Role.READ_ONLY, Role.READ_WRITE], ids=["read_only", "read_write"]
)
async def test_update_cluster_refuses_non_admin_and_leaves_row_unchanged(
    unauth_client: AsyncClient, session: AsyncSession, role: Role
) -> None:
    cluster = await seed_cluster(session)
    cluster_id = cluster.id
    original = dict(cluster.config or {})
    user = await seed_user(session, role=role)
    _row, token = await create_session(session, user.id)

    payload = await _post_update(
        unauth_client,
        {"clusterId": str(cluster_id), "input": FULL_INPUT},
        headers={"Authorization": f"Bearer {token}"},
    )

    error = payload["errors"][0]
    assert error["extensions"]["code"] == "FORBIDDEN", payload
    assert error["path"] == ["updateCluster"], payload
    stored = await _stored_cluster(session, cluster_id)
    assert stored.config == original
    assert not stored.capabilities


@pytest.mark.asyncio
async def test_update_cluster_redeploys_deployment_of_the_cluster(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """The mutation runs the config fan-out on the real repositories: a deployment not at config gets one task."""
    prefect_manager_mock.run_action = AsyncMock(
        return_value=type("FlowInfo", (), {"id": uuid4()})()
    )
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())
    cluster = await seed_cluster(session)
    environment = await seed_environment(session, cluster=cluster)
    adv = await seed_application_driver_version(session)
    deployment = await seed_deployment(session, environment=environment, adv=adv)

    await gql(
        client,
        "update_cluster",
        {"clusterId": str(cluster.id), "input": {"fqdnSuffix": "apps.example.com"}},
    )

    result = await session.exec(select(Task).where(Task.deployment_id == deployment.id))
    tasks = list(result.all())
    assert [task.type for task in tasks] == [TaskType.UPDATE_INSTANCE]
