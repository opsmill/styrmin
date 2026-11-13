"""Propagation tests for the Environment GraphQL surface."""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Environment, Role
from styrmin_backend.services.auth.session import create_session

from ._queries import load_query
from .conftest import gql
from .seeds import seed_cluster, seed_environment, seed_user

VALID_ENV_CONFIG = {"ip_whitelist": ["10.0.0.0/24"]}


@pytest.mark.asyncio
async def test_create_environment_persists_with_cluster_id(
    client: AsyncClient, session: AsyncSession
) -> None:
    cluster = await seed_cluster(session)

    data = await gql(
        client,
        "create_environment",
        {
            "name": "p-env",
            "clusterId": str(cluster.id),
            "config": VALID_ENV_CONFIG,
        },
    )
    env_id = UUID(data["createEnvironment"]["id"])

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
    cluster = await seed_cluster(session, name="lookup-by-name")

    data = await gql(
        client,
        "create_environment",
        {"name": "env-with-name-lookup", "clusterName": "lookup-by-name"},
    )
    env_id = UUID(data["createEnvironment"]["id"])

    db_row = await session.get(Environment, env_id)
    assert db_row is not None
    assert db_row.cluster_id == cluster.id


@pytest.mark.asyncio
async def test_delete_environment_by_id_removes_row(
    client: AsyncClient, session: AsyncSession
) -> None:
    env = await seed_environment(session, name="to-delete")

    await gql(client, "delete_environment", {"environmentId": str(env.id)})

    session.expire_all()
    assert await session.get(Environment, env.id) is None


@pytest.mark.asyncio
async def test_delete_environment_by_name_and_cluster_name_removes_row(
    client: AsyncClient, session: AsyncSession
) -> None:
    cluster = await seed_cluster(session, name="delete-cluster")
    env = await seed_environment(session, cluster=cluster, name="delete-env")
    env_id = env.id

    await gql(
        client,
        "delete_environment",
        {"environmentName": "delete-env", "clusterName": "delete-cluster"},
    )

    session.expire_all()
    assert await session.get(Environment, env_id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", [Role.READ_ONLY, Role.READ_WRITE], ids=["read_only", "read_write"]
)
async def test_delete_environment_refuses_non_admin_and_keeps_row(
    unauth_client: AsyncClient, session: AsyncSession, role: Role
) -> None:
    """``deleteEnvironment`` is ADMIN-only (ADR-017): a caller with a lower
    role gets ``FORBIDDEN`` and the environment row stays in the database.
    """
    env = await seed_environment(session, name="protected-env")
    env_id = env.id
    user = await seed_user(session, role=role)
    _row, token = await create_session(session, user.id)

    response = await unauth_client.post(
        "/graphql",
        json={
            "query": load_query("delete_environment"),
            "variables": {"environmentId": str(env_id)},
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    error = payload["errors"][0]
    assert error["extensions"]["code"] == "FORBIDDEN", payload
    assert error["path"] == ["deleteEnvironment"], payload
    assert payload["data"] is None or payload["data"]["deleteEnvironment"] is None
    session.expire_all()
    assert await session.get(Environment, env_id) is not None


@pytest.mark.asyncio
async def test_environments_projects_seeded_rows(
    client: AsyncClient, session: AsyncSession
) -> None:
    cluster = await seed_cluster(session)
    await seed_environment(session, cluster=cluster, name="env-a")
    await seed_environment(session, cluster=cluster, name="env-b")

    data = await gql(client, "list_environments")
    names = {row["name"] for row in data["environments"]}
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
    cluster = await seed_cluster(session, name="lookup-cluster")
    env = await seed_environment(session, cluster=cluster, name="lookup-env")

    if lookup == "by-id":
        variables = {"environmentId": str(env.id)}
    elif lookup == "by-name-and-cluster-id":
        variables = {"environmentName": "lookup-env", "clusterId": str(cluster.id)}
    else:
        variables = {
            "environmentName": "lookup-env",
            "clusterName": "lookup-cluster",
        }

    data = await gql(client, "get_environment", variables)
    row = data["environment"]
    assert row["id"] == str(env.id)
    assert row["name"] == "lookup-env"


@pytest.mark.asyncio
async def test_environment_projects_cluster_relation(
    client: AsyncClient, session: AsyncSession
) -> None:
    cluster = await seed_cluster(session, name="parent-cluster")
    env = await seed_environment(session, cluster=cluster, name="child-env")

    data = await gql(client, "get_environment", {"environmentId": str(env.id)})
    cluster_data = data["environment"]["cluster"]
    assert cluster_data["id"] == str(cluster.id)
    assert cluster_data["name"] == "parent-cluster"
