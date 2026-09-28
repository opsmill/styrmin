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
async def test_delete_cluster_with_environments_is_refused_as_in_use(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A cluster that still has environments is refused with ``IN_USE`` (#366).

    Deleting it used to make SQLAlchemy null out ``environment.cluster_id``,
    a ``NOT NULL`` column, and the resulting ``IntegrityError`` surfaced as
    ``INTERNAL_ERROR``.
    """
    cluster = Cluster(name="busy-cluster", config=VALID_CLUSTER_CONFIG)
    session.add(cluster)
    await session.commit()
    cluster_id = cluster.id
    session.add_all(
        [
            Environment(name="env-b", cluster_id=cluster_id),
            Environment(name="env-a", cluster_id=cluster_id),
        ]
    )
    await session.commit()

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("delete_cluster"),
            "variables": {"clusterId": str(cluster_id)},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload, payload
    error = payload["errors"][0]
    assert error["extensions"]["code"] == "IN_USE", payload
    assert error["extensions"]["environment_names"] == ["env-a", "env-b"], payload
    assert "env-a, env-b" in error["message"], payload

    # The refusal leaves the cluster and its environments untouched.
    session.expire_all()
    assert await session.get(Cluster, cluster_id) is not None
    environments = (
        await session.exec(
            select(Environment).where(Environment.cluster_id == cluster_id)
        )
    ).all()
    assert sorted(env.name for env in environments) == ["env-a", "env-b"]


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


# ---------------------------------------------------------------------------
# 016 — backup_ttl through the cluster surface (FR-004, SC-003)
# ---------------------------------------------------------------------------
#
# ``backup_ttl`` lives on ``BaseConfigSection``, so one validator governs the
# cluster, environment, and deployment scopes. The environment surface is proven
# end-to-end by ``test_update_environment_rejects_malformed_backup_ttl``; these
# two cover the cluster one, which reaches the validator by a different route —
# an untyped ``config: JSON`` argument rather than a typed Strawberry input.
#
# That difference is visible in the casing. Raw-JSON ``config`` surfaces
# (``createCluster``, ``createEnvironment``) take **snake_case** ``backup_ttl``,
# because ``BaseConfigSection`` sets ``extra="forbid"`` with no alias generator.
# The typed-input surfaces (``deploy``, ``updateDeployment``,
# ``updateEnvironment``) take camelCase ``backupTtl``, which Strawberry converts.


@pytest.mark.asyncio
async def test_create_cluster_accepts_snake_case_backup_ttl(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A cluster-scope retention policy persists through ``createCluster``.

    The cluster is the shallowest scope, so this value is what a backup falls
    back to when neither its deployment nor its environment sets one.
    """
    data = await gql(
        client,
        "create_cluster",
        {
            "name": "ttl-cluster",
            "config": {**VALID_CLUSTER_CONFIG, "backup_ttl": "2160h"},
        },
    )
    cluster_id = UUID(data["createCluster"]["id"])

    db_row = await session.get(Cluster, cluster_id)
    assert db_row is not None
    assert db_row.config is not None
    assert db_row.config["backup_ttl"] == "2160h"


@pytest.mark.asyncio
async def test_create_cluster_rejects_malformed_backup_ttl(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``backup_ttl: "30d"`` is rejected at the cluster boundary, and nothing persists.

    ``30d`` looks like a plausible retention, but Go has no day unit — Velero
    would reject it asynchronously at apply time, long after the operator walked
    away. Hence "rejected at submission" (SC-003).

    The message contract is the same one FR-004 sets for every surface: name the
    field, hint the syntax. The cluster surface goes through
    ``validate_cluster_config`` → ``InvalidClusterContextError`` →
    ``InvalidContextError``, a longer chain than the environment's, so the hint
    has to survive two re-wrappings to get here.
    """
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("create_cluster"),
            "variables": {
                "name": "bad-ttl-cluster",
                "config": {**VALID_CLUSTER_CONFIG, "backup_ttl": "30d"},
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload, payload
    error = payload["errors"][0]
    assert error["extensions"]["code"] == "VALIDATION_ERROR", payload
    assert "backup_ttl" in error["message"], payload
    assert "720h" in error["message"], payload

    # Nothing malformed reached storage — and since a cluster is created in one
    # shot, "nothing persisted" means no row at all.
    session.expire_all()
    rows = (await session.exec(select(Cluster))).all()
    assert rows == [], f"a rejected createCluster left rows behind: {rows}"


@pytest.mark.asyncio
async def test_create_cluster_rejects_camel_case_backup_ttl(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``backupTtl`` is not a key on this surface — raw JSON is snake_case only.

    ``BaseConfigSection`` sets ``extra="forbid"`` and declares no alias
    generator, so a client that copies the camelCase spelling from the typed
    input surfaces gets an unknown-key rejection rather than a silently ignored
    retention policy. Pinned because silent acceptance is the dangerous
    outcome: the operator would believe a policy was set.
    """
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("create_cluster"),
            "variables": {
                "name": "camel-ttl-cluster",
                "config": {**VALID_CLUSTER_CONFIG, "backupTtl": "2160h"},
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload, payload
    error = payload["errors"][0]
    assert error["extensions"]["code"] == "VALIDATION_ERROR", payload
    assert "backupTtl" in error["message"], payload

    session.expire_all()
    assert (await session.exec(select(Cluster))).all() == []


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
