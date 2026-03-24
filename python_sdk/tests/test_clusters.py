"""Tests for cluster resource operations."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from styrmin_sdk import Cluster, ResourceAlreadyExistsError, ResourceNotFoundError, StyrminClient


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

    assert isinstance(cluster, Cluster)
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
            }
        }
    }

    cluster = await client.clusters.get("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

    assert isinstance(cluster, Cluster)
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
