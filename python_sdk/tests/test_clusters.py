"""Tests for cluster resource operations."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from styrmin_sdk import (
    OperationFailedError,
    ResourceAlreadyExistsError,
    ResourceNotFoundError,
    StyrminClient,
)
from styrmin_sdk.models import IngressControllerAction
from styrmin_sdk.resources.clusters import UPDATE_CLUSTER_TIMEOUT_SECONDS


async def test_create_cluster_success(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {
            "createCluster": {
                "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "name": "test-cluster",
                "config": {"key": "value"},
            },
        }
    }

    cluster = await client.clusters.create(name="test-cluster", config={"key": "value"})

    assert cluster.name == "test-cluster"
    assert str(cluster.id) == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert cluster.config == {"key": "value"}


async def test_create_cluster_already_exists(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {"createCluster": None},
        "errors": [{"message": "Cluster already exists", "extensions": {"code": "ALREADY_EXISTS"}}],
    }

    with pytest.raises(ResourceAlreadyExistsError, match="Cluster already exists"):
        await client.clusters.create(name="test-cluster")


async def test_list_clusters(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {
            "clusters": [
                {"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "name": "cluster-1", "config": None},
                {"id": "11111111-2222-3333-4444-555555555555", "name": "cluster-2", "config": {}},
            ]
        }
    }

    clusters = await client.clusters.list()

    assert len(clusters) == 2
    assert clusters[0].name == "cluster-1"
    assert clusters[1].name == "cluster-2"


async def test_list_clusters_empty(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {"data": {"clusters": []}}

    clusters = await client.clusters.list()
    assert clusters == []


async def test_get_cluster_success(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {
            "cluster": {
                "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "name": "test-cluster",
                "config": None,
                "capabilities": None,
            }
        }
    }

    cluster = await client.clusters.get("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

    assert cluster.name == "test-cluster"


async def test_get_cluster_not_found(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {"cluster": None},
        "errors": [{"message": "Cluster not found", "extensions": {"code": "NOT_FOUND"}}],
    }

    with pytest.raises(ResourceNotFoundError, match="Cluster not found"):
        await client.clusters.get("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


async def test_delete_cluster_success(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {"data": {"deleteCluster": "Cluster deleted"}}

    await client.clusters.delete("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


async def test_delete_cluster_not_found(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {"deleteCluster": None},
        "errors": [{"message": "Cluster not found", "extensions": {"code": "NOT_FOUND"}}],
    }

    with pytest.raises(ResourceNotFoundError, match="Cluster not found"):
        await client.clusters.delete("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


_UPDATED_CLUSTER = {
    "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "name": "test-cluster",
    "config": {"fqdn_suffix": "apps.example.com", "ingress_class": "nginx", "runtime_class": "default"},
    "capabilities": {"ingress": True},
    "createdOn": "2026-10-12T10:00:00+00:00",
    "updatedOn": "2026-10-12T11:00:00+00:00",
}

_REDEPLOYED = {
    "deploymentId": "11111111-2222-3333-4444-555555555555",
    "deploymentName": "web",
    "environmentId": "66666666-7777-8888-9999-000000000000",
    "environmentName": "staging",
    "taskId": "99999999-8888-7777-6666-555555555555",
}

_UPDATE_RESULT = {
    "cluster": _UPDATED_CLUSTER,
    "dryRun": False,
    "redeployed": [_REDEPLOYED],
    "waitingForIngress": [],
    "skippedRestoring": [],
    "failedToStart": [],
    "unchangedCount": 2,
    "ingressControllers": [
        {
            "environmentId": "66666666-7777-8888-9999-000000000000",
            "environmentName": "staging",
            "action": "CREATE",
            "failed": False,
        }
    ],
    "failedEnvironments": [],
}


async def test_update_cluster_by_name_sends_camelcase_input(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {"data": {"updateCluster": _UPDATE_RESULT}}

    result = await client.clusters.update(
        {
            "fqdn_suffix": "apps.example.com",
            "ingressClass": "nginx",
            "external_url_scheme": "HTTPS",
            "dedicated_ingress": {"service": {"type": "LoadBalancer"}},
            "standard_storage": {"storage_class": "standard"},
            "db_size": None,
        },
        cluster_name="test-cluster",
    )

    _, variables = mock_transport.execute.call_args.args
    assert variables == {
        "clusterName": "test-cluster",
        "dryRun": False,
        "input": {
            "fqdnSuffix": "apps.example.com",
            "ingressClass": "nginx",
            "externalUrlScheme": "HTTPS",
            "dedicatedIngress": {"service": {"type": "LoadBalancer"}},
            "standardStorage": {"storageClass": "standard"},
        },
    }
    assert mock_transport.execute.call_args.kwargs == {"request_timeout": UPDATE_CLUSTER_TIMEOUT_SECONDS}
    assert result.cluster.name == "test-cluster"
    assert result.cluster.config == _UPDATED_CLUSTER["config"]
    assert result.cluster.updated_on is not None
    [redeployed] = result.redeployed
    assert redeployed.deployment_name == "web"
    assert str(redeployed.task_id) == _REDEPLOYED["taskId"]
    assert result.unchanged_count == 2
    assert result.ingress_controllers[0].action == IngressControllerAction.CREATE


async def test_update_cluster_by_id_dry_run(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {"data": {"updateCluster": {**_UPDATE_RESULT, "dryRun": True}}}

    result = await client.clusters.update(
        {"dedicated_ingress": {}}, cluster_id=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"), dry_run=True
    )

    _, variables = mock_transport.execute.call_args.args
    assert variables == {
        "clusterId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "dryRun": True,
        "input": {"dedicatedIngress": {}},
    }
    assert result.dry_run


async def test_update_cluster_accepts_the_config_that_get_returns(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    """Read the config, change one value, send it back: the stored enum values are accepted."""
    mock_transport.execute.return_value = {"data": {"updateCluster": _UPDATE_RESULT}}
    stored = {
        "external_url_scheme": "http",
        "external_dns_endpoints_type": "NodeExternalIP",
    }

    await client.clusters.update({**stored, "fqdn_suffix": "new.example.com"}, cluster_name="test-cluster")

    _, variables = mock_transport.execute.call_args.args
    sent = variables["input"]
    assert sent["externalUrlScheme"] == "HTTP"
    assert sent["externalDnsEndpointsType"] == "NODE_EXTERNAL_IP"
    assert sent["fqdnSuffix"] == "new.example.com"


@pytest.mark.parametrize(
    ("config", "key_path"),
    [
        ({"ingress_class": "nginx", "fqdn_sufix": "apps.example.com"}, "fqdn_sufix"),
        ({"dedicated_ingres": {}}, "dedicated_ingres"),
        ({"dedicated_ingress": {"servce": {"type": "LoadBalancer"}}}, "dedicated_ingress.servce"),
        ({"scheduling": {"tolerations": [{"key": "x", "operator": "Exists"}]}}, "scheduling"),
    ],
    ids=["top_level", "dedicated_ingress_typo", "nested", "cluster_scheduling"],
)
async def test_update_cluster_refuses_unknown_keys_before_any_request(
    client: StyrminClient, mock_transport: AsyncMock, config: dict[str, Any], key_path: str
) -> None:
    with pytest.raises(ValueError, match="Unknown config key") as exc:
        await client.clusters.update(config, cluster_name="test-cluster")

    assert key_path in str(exc.value)
    mock_transport.execute.assert_not_called()


async def test_update_cluster_refuses_a_typed_input(client: StyrminClient, mock_transport: AsyncMock) -> None:
    with pytest.raises(TypeError, match="mapping"):
        await client.clusters.update("not a dict", cluster_name="test-cluster")  # type: ignore[arg-type]

    mock_transport.execute.assert_not_called()


async def test_update_cluster_not_found(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {"updateCluster": None},
        "errors": [{"message": "Cluster not found", "extensions": {"code": "NOT_FOUND"}}],
    }

    with pytest.raises(ResourceNotFoundError, match="Cluster not found"):
        await client.clusters.update({}, cluster_name="missing")


async def test_update_cluster_validation_error(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {"updateCluster": None},
        "errors": [{"message": "Invalid cluster config", "extensions": {"code": "VALIDATION_ERROR"}}],
    }

    with pytest.raises(OperationFailedError, match="Invalid cluster config") as exc:
        await client.clusters.update({"external_url_port": 0}, cluster_name="test-cluster")
    assert exc.value.typename == "VALIDATION_ERROR"
