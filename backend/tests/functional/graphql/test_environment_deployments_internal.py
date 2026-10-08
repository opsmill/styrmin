"""Propagation tests for ``Environment.deployments(includeInternal)`` (#253).

Internal deployments (the ingress controller of a dedicated ingress) are left
out of the environment's deployment list unless the caller asks for them.
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
async def test_environment_deployments_excludes_internal_by_default(
    client: AsyncClient, session: AsyncSession
) -> None:
    env = await seed_environment(session)
    app = await seed_deployment(session, environment=env)
    controller = await seed_deployment(session, environment=env, internal=True)

    data = await gql(
        client, "list_environment_deployments", {"environmentId": str(env.id)}
    )
    ids = {row["id"] for row in data["environment"]["deployments"]}

    assert ids == {str(app.id)}
    assert str(controller.id) not in ids


@pytest.mark.asyncio
async def test_environment_deployments_includes_internal_when_requested(
    client: AsyncClient, session: AsyncSession
) -> None:
    env = await seed_environment(session)
    app = await seed_deployment(session, environment=env)
    controller = await seed_deployment(session, environment=env, internal=True)

    data = await gql(
        client,
        "list_environment_deployments",
        {"environmentId": str(env.id), "includeInternal": True},
    )
    rows = {row["id"]: row for row in data["environment"]["deployments"]}

    assert set(rows) == {str(app.id), str(controller.id)}
    assert rows[str(controller.id)]["internal"] is True
    assert rows[str(app.id)]["internal"] is False


@pytest.mark.asyncio
async def test_environment_deployments_applies_both_filters_independently(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A tombstoned internal deployment needs both arguments to appear."""
    env = await seed_environment(session)
    controller = await seed_deployment(session, environment=env, internal=True)
    controller.status = DeploymentState.DELETED
    controller.deleted_at = datetime.now(tz=timezone.utc)
    session.add(controller)
    await session.commit()

    def listed(data: dict) -> set[str]:
        return {row["id"] for row in data["environment"]["deployments"]}

    variables = {"environmentId": str(env.id)}
    only_deleted = await gql(
        client,
        "list_environment_deployments",
        {**variables, "includeDeleted": True},
    )
    only_internal = await gql(
        client,
        "list_environment_deployments",
        {**variables, "includeInternal": True},
    )
    both = await gql(
        client,
        "list_environment_deployments",
        {**variables, "includeDeleted": True, "includeInternal": True},
    )

    assert str(controller.id) not in listed(only_deleted)
    assert str(controller.id) not in listed(only_internal)
    assert listed(both) == {str(controller.id)}
