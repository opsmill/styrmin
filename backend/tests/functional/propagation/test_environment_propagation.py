"""Propagation tests for the Environment GraphQL surface."""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Cluster, Environment

from ._queries import load_query

VALID_CLUSTER_CONFIG = {"runtime_class": "example_runtime_class"}
VALID_ENV_CONFIG = {"ip_whitelist": ["10.0.0.0/24"]}


async def _seed_cluster(session: AsyncSession, name: str = "p-cluster") -> Cluster:
    cluster = Cluster(name=name, config=VALID_CLUSTER_CONFIG)
    session.add(cluster)
    await session.commit()
    return cluster


@pytest.mark.asyncio
async def test_create_environment_persists_with_cluster_id(
    client: AsyncClient, session: AsyncSession
) -> None:
    cluster = await _seed_cluster(session)

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("create_environment"),
            "variables": {
                "name": "p-env",
                "clusterId": str(cluster.id),
                "config": VALID_ENV_CONFIG,
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    env_id = UUID(payload["data"]["createEnvironment"]["id"])

    db_row = await session.get(Environment, env_id)
    assert db_row is not None
    assert db_row.name == "p-env"
    assert db_row.cluster_id == cluster.id
    assert db_row.config is not None
    assert db_row.config["ip_whitelist"] == ["10.0.0.0/24"]


@pytest.mark.asyncio
async def test_create_environment_persists_with_cluster_name(
    client: AsyncClient, session: AsyncSession
) -> None:
    cluster = await _seed_cluster(session, name="lookup-by-name")

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("create_environment"),
            "variables": {
                "name": "env-with-name-lookup",
                "clusterName": "lookup-by-name",
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    env_id = UUID(payload["data"]["createEnvironment"]["id"])

    db_row = await session.get(Environment, env_id)
    assert db_row is not None
    assert db_row.cluster_id == cluster.id


@pytest.mark.asyncio
async def test_delete_environment_by_id_removes_row(
    client: AsyncClient, session: AsyncSession
) -> None:
    cluster = await _seed_cluster(session)
    env = Environment(name="to-delete", cluster_id=cluster.id)
    session.add(env)
    await session.commit()

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("delete_environment"),
            "variables": {"environmentId": str(env.id)},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    session.expire_all()
    assert await session.get(Environment, env.id) is None


@pytest.mark.asyncio
async def test_delete_environment_by_name_and_cluster_name_removes_row(
    client: AsyncClient, session: AsyncSession
) -> None:
    cluster = await _seed_cluster(session, name="delete-cluster")
    env = Environment(name="delete-env", cluster_id=cluster.id)
    session.add(env)
    await session.commit()
    env_id = env.id

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("delete_environment"),
            "variables": {
                "environmentName": "delete-env",
                "clusterName": "delete-cluster",
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    session.expire_all()
    assert await session.get(Environment, env_id) is None


@pytest.mark.asyncio
async def test_environments_projects_seeded_rows(
    client: AsyncClient, session: AsyncSession
) -> None:
    cluster = await _seed_cluster(session)
    session.add_all(
        [
            Environment(name="env-a", cluster_id=cluster.id),
            Environment(name="env-b", cluster_id=cluster.id),
        ]
    )
    await session.commit()

    response = await client.post(
        "/graphql", json={"query": load_query("list_environments")}
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    names = {row["name"] for row in payload["data"]["environments"]}
    assert {"env-a", "env-b"} <= names


@pytest.mark.parametrize(
    "lookup",
    [
        "by-id",
        "by-name-and-cluster-id",
        "by-name-and-cluster-name",
    ],
)
@pytest.mark.asyncio
async def test_environment_by_each_lookup_arg(
    client: AsyncClient, session: AsyncSession, lookup: str
) -> None:
    cluster = await _seed_cluster(session, name="lookup-cluster")
    env = Environment(name="lookup-env", cluster_id=cluster.id)
    session.add(env)
    await session.commit()

    if lookup == "by-id":
        variables = {"environmentId": str(env.id)}
    elif lookup == "by-name-and-cluster-id":
        variables = {"environmentName": "lookup-env", "clusterId": str(cluster.id)}
    else:
        variables = {
            "environmentName": "lookup-env",
            "clusterName": "lookup-cluster",
        }

    response = await client.post(
        "/graphql",
        json={"query": load_query("get_environment"), "variables": variables},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    data = payload["data"]["environment"]
    assert data["id"] == str(env.id)
    assert data["name"] == "lookup-env"


@pytest.mark.asyncio
async def test_environment_projects_cluster_relation(
    client: AsyncClient, session: AsyncSession
) -> None:
    cluster = await _seed_cluster(session, name="parent-cluster")
    env = Environment(name="child-env", cluster_id=cluster.id)
    session.add(env)
    await session.commit()

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("get_environment"),
            "variables": {"environmentId": str(env.id)},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    cluster_data = payload["data"]["environment"]["cluster"]
    assert cluster_data["id"] == str(cluster.id)
    assert cluster_data["name"] == "parent-cluster"
