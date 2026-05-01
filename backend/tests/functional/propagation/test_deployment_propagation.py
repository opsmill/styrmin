"""Propagation tests for the Deployment GraphQL surface (read negatives + internal-deployment guards)."""

from __future__ import annotations


import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Deployment

from .seeds import seed_deployment

get_deployment_query = """
    query GetDeployment($deploymentId: UUID!) {
        deployment(deploymentId: $deploymentId) {
            id
            name
            internal
            status
        }
    }
"""

update_deployment_mutation = """
    mutation UpdateDeployment($deploymentId: UUID!, $name: String) {
        updateDeployment(deploymentId: $deploymentId, name: $name) {
            id
        }
    }
"""

update_deployment_version_mutation = """
    mutation UpdateDeploymentVersion($deploymentId: UUID!, $version: String!) {
        updateDeploymentVersion(deploymentId: $deploymentId, version: $version) {
            id
        }
    }
"""


@pytest.mark.asyncio
async def test_internal_deployment_returns_null(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Seed an internal=True deployment, expect Query.deployment to project null
    (the resolver explicitly returns None for internal deployments). Asserts
    the row is in the DB but the projection is gated."""
    deployment = await seed_deployment(session, internal=True)
    deployment_id = deployment.id

    # Confirm the seed exists in DB
    db_row = await session.get(Deployment, deployment_id)
    assert db_row is not None
    assert db_row.internal is True

    response = await client.post(
        "/graphql",
        json={
            "query": get_deployment_query,
            "variables": {"deploymentId": str(deployment_id)},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["deployment"] is None


@pytest.mark.asyncio
async def test_non_internal_deployment_projects_fields(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment = await seed_deployment(session, internal=False)
    deployment_id = deployment.id

    response = await client.post(
        "/graphql",
        json={
            "query": get_deployment_query,
            "variables": {"deploymentId": str(deployment_id)},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    data = payload["data"]["deployment"]
    assert data["id"] == str(deployment_id)
    assert data["name"] == deployment.name
    assert data["internal"] is False


@pytest.mark.asyncio
async def test_update_internal_deployment_raises(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Negative path: updating an internal=True deployment must raise the typed
    InternalDeploymentError and MUST NOT mutate the DB row."""
    deployment = await seed_deployment(session, internal=True, name="internal-dep")
    deployment_id = deployment.id

    response = await client.post(
        "/graphql",
        json={
            "query": update_deployment_mutation,
            "variables": {"deploymentId": str(deployment_id), "name": "renamed"},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload
    assert any(
        err["extensions"].get("code") == "OPERATION_DENIED" for err in payload["errors"]
    ), payload["errors"]

    session.expire_all()
    refreshed = await session.get(Deployment, deployment_id)
    assert refreshed is not None
    assert refreshed.name == "internal-dep"  # unchanged


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
            "query": update_deployment_version_mutation,
            "variables": {"deploymentId": str(deployment_id), "version": "9.9.9"},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload
    assert any(
        err["extensions"].get("code") == "OPERATION_DENIED" for err in payload["errors"]
    ), payload["errors"]

    session.expire_all()
    refreshed = await session.get(Deployment, deployment_id)
    assert refreshed is not None
    assert refreshed.application_version == original_version
