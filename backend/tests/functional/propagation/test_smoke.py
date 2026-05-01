"""Foundational smoke test that proves the propagation conftest is wired up.

This is the canonical reference shape for every test under
``backend/tests/functional/propagation/`` — drive the GraphQL HTTP boundary,
then read the row back through the same DB session the resolver wrote to.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Cluster
from tests.functional.helpers import create_cluster_query


@pytest.mark.asyncio
async def test_create_cluster_persists_to_db(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await client.post(
        "/graphql",
        json={
            "query": create_cluster_query,
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
