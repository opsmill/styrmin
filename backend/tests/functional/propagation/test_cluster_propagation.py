"""Propagation tests for the Cluster GraphQL surface.

Each test drives the GraphQL HTTP boundary, then verifies persisted state by
reading rows back through the same DB session the resolver wrote to. See
specs/007-graphql-propagation-tests/contracts/propagation-test-contract.md.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Cluster, Environment

from ._queries import load_query

VALID_CLUSTER_CONFIG = {"runtime_class": "example_runtime_class"}


@pytest.mark.asyncio
async def test_create_cluster_persists_name_and_config(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("create_cluster"),
            "variables": {"name": "p-cluster", "config": VALID_CLUSTER_CONFIG},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    cluster_id = UUID(payload["data"]["createCluster"]["id"])

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

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("delete_cluster"),
            "variables": {"clusterId": str(seeded.id)},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    assert payload["data"]["deleteCluster"] == "Cluster deleted"

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

    response = await client.post(
        "/graphql", json={"query": load_query("list_clusters")}
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    names = {row["name"] for row in payload["data"]["clusters"]}
    assert {"alpha", "beta"} <= names


@pytest.mark.asyncio
async def test_cluster_by_id_projects_all_fields(
    client: AsyncClient, session: AsyncSession
) -> None:
    seeded = Cluster(name="seed-by-id", config=VALID_CLUSTER_CONFIG)
    session.add(seeded)
    await session.commit()

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("get_cluster"),
            "variables": {"clusterId": str(seeded.id)},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    data = payload["data"]["cluster"]
    assert data["id"] == str(seeded.id)
    assert data["name"] == "seed-by-id"
    assert data["config"] == VALID_CLUSTER_CONFIG
    assert data["createdOn"] is not None
    assert isinstance(data["environments"], list)


@pytest.mark.asyncio
async def test_cluster_by_name_returns_seeded_row(
    client: AsyncClient, session: AsyncSession
) -> None:
    seeded = Cluster(name="seed-by-name", config=VALID_CLUSTER_CONFIG)
    session.add(seeded)
    await session.commit()

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("get_cluster_by_name"),
            "variables": {"clusterName": "seed-by-name"},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    assert payload["data"]["cluster"]["id"] == str(seeded.id)
    assert payload["data"]["cluster"]["name"] == "seed-by-name"


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

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("get_cluster"),
            "variables": {"clusterId": str(cluster.id)},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    envs = payload["data"]["cluster"]["environments"]
    assert len(envs) == 1
    assert envs[0]["id"] == str(env.id)
    assert envs[0]["name"] == "env-a"


@pytest.mark.asyncio
async def test_cluster_by_unknown_id_returns_null(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Negative path — proves the lookup actually queries the DB and a missing
    row produces no projection. Asserts via an absent DB row that the
    resolver did not silently fabricate a value."""
    bogus_id = uuid4()
    rows = (await session.exec(select(Cluster))).all()
    assert all(row.id != bogus_id for row in rows)

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("get_cluster"),
            "variables": {"clusterId": str(bogus_id)},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["cluster"] is None
