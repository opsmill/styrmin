"""Foundational smoke test that proves the conftest wiring works end-to-end.

Uses the raw ``client.post`` form — every other test in this package goes
through the ``gql`` helper, so the smoke test's job is to prove the bare
session/client/Strawberry path before any helper sits on top of it.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Cluster

from ._queries import load_query


@pytest.mark.asyncio
async def test_create_cluster_persists_to_db(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("create_cluster"),
            "variables": {
                "name": "smoke-cluster",
                "config": {"runtime_class": "example_runtime_class"},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    cluster_id = UUID(payload["data"]["createCluster"]["id"])

    db_row = await session.get(Cluster, cluster_id)
    assert db_row is not None
    assert db_row.name == "smoke-cluster"
    assert db_row.config is not None
    assert db_row.config["runtime_class"] == "example_runtime_class"
