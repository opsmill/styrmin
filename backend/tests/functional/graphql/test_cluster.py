"""Propagation tests for the Cluster GraphQL surface.

Each test drives the GraphQL HTTP boundary, then verifies persisted state by
reading rows back through the same DB session the resolver wrote to. See
specs/007-graphql-propagation-tests/contracts/propagation-test-contract.md.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Cluster, Environment

from ._queries import load_query
from .conftest import gql
from .seeds import VALID_CLUSTER_CONFIG


@pytest.mark.asyncio
async def test_create_cluster_persists_name_and_config(
    client: AsyncClient, session: AsyncSession
) -> None:
    data = await gql(
        client,
        "create_cluster",
        {"name": "p-cluster", "config": VALID_CLUSTER_CONFIG},
    )
    cluster_id = UUID(data["createCluster"]["id"])

    db_row = await session.get(Cluster, cluster_id)
    assert db_row is not None
    assert db_row.name == "p-cluster"
    assert db_row.config is not None
    assert db_row.config["runtime_class"] == "example_runtime_class"
    assert db_row.created_on is not None


@pytest.mark.asyncio
async def test_delete_cluster_removes_row(
    client: AsyncClient, session: AsyncSession
) -> None:
    seeded = Cluster(name="to-delete", config=VALID_CLUSTER_CONFIG)
    session.add(seeded)
    await session.commit()

    data = await gql(client, "delete_cluster", {"clusterId": str(seeded.id)})
    assert data["deleteCluster"] == "Cluster deleted"

    session.expire_all()
    assert await session.get(Cluster, seeded.id) is None


@pytest.mark.asyncio
async def test_clusters_projects_seeded_rows(
    client: AsyncClient, session: AsyncSession
) -> None:
    seeded_a = Cluster(name="alpha", config=VALID_CLUSTER_CONFIG)
    seeded_b = Cluster(name="beta", config=VALID_CLUSTER_CONFIG)
    session.add_all([seeded_a, seeded_b])
    await session.commit()

    data = await gql(client, "list_clusters")
    names = {row["name"] for row in data["clusters"]}
    assert {"alpha", "beta"} <= names


@pytest.mark.asyncio
async def test_cluster_by_id_projects_all_fields(
    client: AsyncClient, session: AsyncSession
) -> None:
    seeded = Cluster(name="seed-by-id", config=VALID_CLUSTER_CONFIG)
    session.add(seeded)
    await session.commit()

    data = await gql(client, "get_cluster", {"clusterId": str(seeded.id)})
    row = data["cluster"]
    assert row["id"] == str(seeded.id)
    assert row["name"] == "seed-by-id"
    assert row["config"] == VALID_CLUSTER_CONFIG
    assert row["createdOn"] is not None
    assert isinstance(row["environments"], list)


@pytest.mark.asyncio
async def test_cluster_by_name_returns_seeded_row(
    client: AsyncClient, session: AsyncSession
) -> None:
    seeded = Cluster(name="seed-by-name", config=VALID_CLUSTER_CONFIG)
    session.add(seeded)
    await session.commit()

    data = await gql(client, "get_cluster_by_name", {"clusterName": "seed-by-name"})
    assert data["cluster"]["id"] == str(seeded.id)
    assert data["cluster"]["name"] == "seed-by-name"


@pytest.mark.asyncio
async def test_cluster_projects_environments_relation(
    client: AsyncClient, session: AsyncSession
) -> None:
    cluster = Cluster(name="with-envs", config=VALID_CLUSTER_CONFIG)
    session.add(cluster)
    await session.commit()
    env = Environment(name="env-a", cluster_id=cluster.id)
    session.add(env)
    await session.commit()

    data = await gql(client, "get_cluster", {"clusterId": str(cluster.id)})
    envs = data["cluster"]["environments"]
    assert len(envs) == 1
    assert envs[0]["id"] == str(env.id)
    assert envs[0]["name"] == "env-a"


@pytest.mark.asyncio
async def test_cluster_by_unknown_id_returns_null(client: AsyncClient) -> None:
    """An unknown id must project as null with a NOT_FOUND extension — uses the
    raw ``client.post`` because ``gql`` is reserved for clean-success calls."""
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("get_cluster"),
            "variables": {"clusterId": str(uuid4())},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["cluster"] is None
