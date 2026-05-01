"""Propagation tests for the Deployment GraphQL surface (read negatives + internal-deployment guards)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Deployment

from ._queries import load_query
from .conftest import gql
from .seeds import seed_deployment


@pytest.mark.asyncio
async def test_internal_deployment_returns_null(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Internal deployments live in the DB but the resolver explicitly projects
    null — verify both the DB row and the gated projection."""
    deployment = await seed_deployment(session, internal=True)

    db_row = await session.get(Deployment, deployment.id)
    assert db_row is not None
    assert db_row.internal is True

    data = await gql(client, "get_deployment", {"deploymentId": str(deployment.id)})
    assert data["deployment"] is None


@pytest.mark.asyncio
async def test_non_internal_deployment_projects_fields(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment = await seed_deployment(session, internal=False)

    data = await gql(client, "get_deployment", {"deploymentId": str(deployment.id)})
    row = data["deployment"]
    assert row["id"] == str(deployment.id)
    assert row["name"] == deployment.name
    assert row["internal"] is False


@pytest.mark.asyncio
async def test_update_internal_deployment_raises(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Updating an internal=True deployment must raise the typed
    InternalDeploymentError and MUST NOT mutate the DB row."""
    deployment = await seed_deployment(session, internal=True, name="internal-dep")
    deployment_id = deployment.id

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment"),
            "variables": {"deploymentId": str(deployment_id), "name": "renamed"},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert any(
        err["extensions"].get("code") == "OPERATION_DENIED" for err in payload["errors"]
    ), payload["errors"]

    session.expire_all()
    refreshed = await session.get(Deployment, deployment_id)
    assert refreshed is not None
    assert refreshed.name == "internal-dep"


@pytest.mark.asyncio
async def test_update_version_internal_deployment_raises(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment = await seed_deployment(session, internal=True)
    deployment_id = deployment.id
    original_version = deployment.application_version

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment_version"),
            "variables": {"deploymentId": str(deployment_id), "version": "9.9.9"},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert any(
        err["extensions"].get("code") == "OPERATION_DENIED" for err in payload["errors"]
    ), payload["errors"]

    session.expire_all()
    refreshed = await session.get(Deployment, deployment_id)
    assert refreshed is not None
    assert refreshed.application_version == original_version
