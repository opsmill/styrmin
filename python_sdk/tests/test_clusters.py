"""Tests for cluster resource operations."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from styrmin_sdk import (
    OperationFailedError,
    ResourceAlreadyExistsError,
    ResourceNotFoundError,
    StyrminClient,
    UpdateClusterInput,
)


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


async def test_update_cluster_by_name_sends_camelcase_input(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {"data": {"updateCluster": _UPDATED_CLUSTER}}

    update_input = UpdateClusterInput.model_validate(
        {
            "fqdn_suffix": "apps.example.com",
            "ingress_class": "nginx",
            "external_url_scheme": "HTTPS",
            "dedicated_ingress": {"service": {"type": "LoadBalancer"}},
            "standard_storage": {"storage_class": "standard"},
        }
    )
    cluster = await client.clusters.update(update_input, cluster_name="test-cluster")

    _, variables = mock_transport.execute.call_args.args
    assert variables == {
        "clusterName": "test-cluster",
        "input": {
            "fqdnSuffix": "apps.example.com",
            "ingressClass": "nginx",
            "externalUrlScheme": "HTTPS",
            "dedicatedIngress": {"service": {"type": "LoadBalancer"}},
            "standardStorage": {"storageClass": "standard"},
        },
    }
    assert cluster.name == "test-cluster"
    assert str(cluster.id) == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert cluster.config == _UPDATED_CLUSTER["config"]
    assert cluster.capabilities == {"ingress": True}
    assert cluster.updated_on is not None


async def test_update_cluster_by_id_sends_cluster_id(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {"data": {"updateCluster": _UPDATED_CLUSTER}}

    await client.clusters.update(
        UpdateClusterInput.model_validate({"dedicated_ingress": {}}),
        cluster_id=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
    )

    _, variables = mock_transport.execute.call_args.args
    assert variables == {
        "clusterId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "input": {"dedicatedIngress": {}},
    }


async def test_update_cluster_not_found(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {"updateCluster": None},
        "errors": [{"message": "Cluster not found", "extensions": {"code": "NOT_FOUND"}}],
    }

    with pytest.raises(ResourceNotFoundError, match="Cluster not found"):
        await client.clusters.update(UpdateClusterInput(), cluster_name="missing")


async def test_update_cluster_validation_error(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {"updateCluster": None},
        "errors": [{"message": "Invalid cluster config", "extensions": {"code": "VALIDATION_ERROR"}}],
    }

    with pytest.raises(OperationFailedError, match="Invalid cluster config") as exc:
        await client.clusters.update(
            UpdateClusterInput.model_validate({"external_url_port": 0}), cluster_name="test-cluster"
        )
    assert exc.value.typename == "VALIDATION_ERROR"
