"""Propagation tests for the Deployment GraphQL surface (read negatives + internal-deployment guards)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Deployment

from ._queries import load_query
from .conftest import gql
from .seeds import seed_deployment, seed_environment


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
            "variables": {
                "deploymentId": str(deployment_id),
                "input": {"name": "renamed"},
            },
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


# ---------------------------------------------------------------------------
# Scoped + tombstone-aware name uniqueness (spec 008 follow-up)
# ---------------------------------------------------------------------------
#
# The rename success cases (cross-env reuse, tombstone reuse) flow
# through the full reconciliation pipeline and are heavy to exercise at
# the GraphQL level — the underlying contracts (per-env scope,
# tombstone-ignored uniqueness, partial-index enforcement) are proven
# end-to-end by the repository-level tests in
# ``backend/tests/unit/repository/test_deployment_repository.py``. The
# one assertion worth pinning at the GraphQL boundary is the
# conflict-error code, since the structured-error extension is what
# clients see — that's the test below.


# ---------------------------------------------------------------------------
# Lookup by natural identity: deployment(name, environmentId)
# (spec 009-deployments-apply, T005-T009)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_by_name_finds_real_deployment(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A real, non-internal, non-deleted deployment is projected by the
    new ``deployment(name, environmentId)`` shape."""
    env = await seed_environment(session, name="env-by-name-found")
    deployment = await seed_deployment(
        session, environment=env, name="real-deployment", internal=False
    )

    data = await gql(
        client,
        "get_deployment_by_name",
        {"name": "real-deployment", "environmentId": str(env.id)},
    )
    row = data["deployment"]
    assert row is not None
    assert row["id"] == str(deployment.id)
    assert row["name"] == "real-deployment"
    assert row["internal"] is False


@pytest.mark.asyncio
async def test_lookup_by_name_returns_null_when_no_row(
    client: AsyncClient, session: AsyncSession
) -> None:
    """No matching deployment → resolver returns null (not an error)."""
    env = await seed_environment(session, name="env-by-name-miss")

    data = await gql(
        client,
        "get_deployment_by_name",
        {"name": "does-not-exist", "environmentId": str(env.id)},
    )
    assert data["deployment"] is None


@pytest.mark.asyncio
async def test_lookup_by_name_hides_internal_deployment(
    client: AsyncClient, session: AsyncSession
) -> None:
    """An ``internal=True`` row matching ``(name, environment_id)`` is hidden
    by the resolver — same gate as the existing ``deployment(deploymentId)``
    shape."""
    env = await seed_environment(session, name="env-by-name-internal")
    await seed_deployment(
        session, environment=env, name="hidden-internal", internal=True
    )

    data = await gql(
        client,
        "get_deployment_by_name",
        {"name": "hidden-internal", "environmentId": str(env.id)},
    )
    assert data["deployment"] is None


@pytest.mark.asyncio
async def test_lookup_by_name_hides_soft_deleted_deployment(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A soft-deleted (``deleted_at IS NOT NULL``) row is excluded by the
    repository filter, so the resolver returns null."""
    env = await seed_environment(session, name="env-by-name-tombstone")
    deployment = await seed_deployment(
        session, environment=env, name="tombstoned-deployment", internal=False
    )
    deployment.deleted_at = datetime.now(tz=timezone.utc)
    session.add(deployment)
    await session.commit()

    data = await gql(
        client,
        "get_deployment_by_name",
        {"name": "tombstoned-deployment", "environmentId": str(env.id)},
    )
    assert data["deployment"] is None


@pytest.mark.asyncio
async def test_lookup_with_both_id_and_name_raises_structured_error(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Passing ``deploymentId`` alongside ``(name, environmentId)`` is
    rejected with a structured ``INVALID_DEPLOYMENT_LOOKUP_ARGS`` error."""
    env = await seed_environment(session, name="env-by-name-both-args")
    deployment = await seed_deployment(
        session, environment=env, name="ambiguous", internal=False
    )

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("get_deployment_with_both_args"),
            "variables": {
                "deploymentId": str(deployment.id),
                "name": "ambiguous",
                "environmentId": str(env.id),
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload, payload
    assert any(
        err["extensions"].get("code") == "INVALID_DEPLOYMENT_LOOKUP_ARGS"
        for err in payload["errors"]
    ), payload["errors"]


@pytest.mark.asyncio
async def test_rename_to_active_name_in_same_env_raises_conflict(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """Two active deployments cannot share a name in the same env —
    the rename mutation surfaces ``ALREADY_EXISTS`` via the structured-
    error extension."""
    from unittest.mock import AsyncMock

    from .seeds import seed_environment

    prefect_manager_mock.run_action = AsyncMock()

    env = await seed_environment(session, name="env-rename-conflict")
    await seed_deployment(session, environment=env, name="ansible")
    target = await seed_deployment(session, environment=env, name="other")

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment"),
            "variables": {
                "deploymentId": str(target.id),
                "input": {"name": "ansible"},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert any(
        err["extensions"].get("code") == "ALREADY_EXISTS" for err in payload["errors"]
    ), payload["errors"]
