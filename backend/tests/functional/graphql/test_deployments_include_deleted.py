"""Propagation tests for the deployment-deletion read surface (spec 008).

Covers ``Environment.deployments(includeDeleted)`` filtering, the
``Deployment.deletedAt`` scalar field, and the unfiltered
``deployment(id)`` lookup. The mutation is exercised by
``test_delete_deployment.py``; this file covers the read paths that
expose tombstoned state to clients.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import DeploymentState

from .conftest import gql
from .seeds import seed_deployment, seed_environment


@pytest.mark.asyncio
async def test_environment_deployments_excludes_tombstoned_by_default(
    client: AsyncClient, session: AsyncSession
) -> None:
    env = await seed_environment(session)
    live = await seed_deployment(session, environment=env)
    tombstoned = await seed_deployment(session, environment=env)
    tombstoned.status = DeploymentState.DELETED
    tombstoned.deleted_at = datetime.now(tz=timezone.utc)
    session.add(tombstoned)
    await session.commit()

    data = await gql(
        client,
        "list_environment_deployments",
        {"environmentId": str(env.id), "includeDeleted": False},
    )
    rows = data["environment"]["deployments"]
    ids = {row["id"] for row in rows}

    assert str(live.id) in ids
    assert str(tombstoned.id) not in ids


@pytest.mark.asyncio
async def test_environment_deployments_includes_tombstoned_when_requested(
    client: AsyncClient, session: AsyncSession
) -> None:
    env = await seed_environment(session)
    live = await seed_deployment(session, environment=env)
    deleted_at_value = datetime.now(tz=timezone.utc)
    tombstoned = await seed_deployment(session, environment=env)
    tombstoned.status = DeploymentState.DELETED
    tombstoned.deleted_at = deleted_at_value
    session.add(tombstoned)
    await session.commit()

    data = await gql(
        client,
        "list_environment_deployments",
        {"environmentId": str(env.id), "includeDeleted": True},
    )
    rows = {row["id"]: row for row in data["environment"]["deployments"]}

    assert str(live.id) in rows
    assert rows[str(live.id)]["deletedAt"] is None

    assert str(tombstoned.id) in rows
    tombstoned_row = rows[str(tombstoned.id)]
    assert tombstoned_row["deletedAt"] is not None
    assert tombstoned_row["status"] == "deleted"


@pytest.mark.asyncio
async def test_environment_deployments_keeps_deleting_visible_in_default_view(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A DELETING deployment has deleted_at IS NULL until terminal, so it
    must remain visible in the default list (Spec FR-028 / US3 #1)."""

    env = await seed_environment(session)
    deleting = await seed_deployment(session, environment=env)
    deleting.status = DeploymentState.DELETING
    session.add(deleting)
    await session.commit()

    data = await gql(
        client,
        "list_environment_deployments",
        {"environmentId": str(env.id), "includeDeleted": False},
    )
    rows = {row["id"]: row for row in data["environment"]["deployments"]}

    assert str(deleting.id) in rows
    assert rows[str(deleting.id)]["deletedAt"] is None
    assert rows[str(deleting.id)]["status"] == "deleting"


@pytest.mark.asyncio
async def test_deployment_by_id_returns_tombstoned_unfiltered(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``deployment(id)`` is unfiltered — direct id lookup must reach
    tombstoned records forever (Spec FR-022 / FR-032)."""

    deployment = await seed_deployment(session)
    deployment.status = DeploymentState.DELETED
    deployment.deleted_at = datetime.now(tz=timezone.utc)
    session.add(deployment)
    await session.commit()

    data = await gql(
        client, "get_deployment_deleted_at", {"deploymentId": str(deployment.id)}
    )
    row = data["deployment"]
    assert row is not None
    assert row["id"] == str(deployment.id)
    assert row["status"] == "deleted"
    assert row["deletedAt"] is not None
