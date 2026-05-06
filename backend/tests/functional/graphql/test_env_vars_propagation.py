"""GraphQL ↔ DB propagation tests for the env vars feature (T029, US1).

Per Constitution §V every new GraphQL field requires a propagation test that
proves the value flows through the **real** service + repository layers
between the GraphQL boundary and the DB. This module covers the
``Deployment.envVars`` read field.

The write path for deployment-level env vars rides the existing ``config:
JSON`` argument on ``updateDeployment`` (per ``contracts/graphql.md`` §3),
which is not yet exposed in the seed-and-query path used here. The test
below asserts the round-trip on the read projection: a deployment row
seeded with ``env_vars`` inside its persisted ``config`` JSON is observable
through ``Deployment.envVars`` exactly. A future write-path propagation
test will land alongside the GraphQL mutation surface (US3 / US4 follow-up).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Deployment

from .conftest import gql
from .seeds import seed_deployment


@pytest.mark.asyncio
async def test_deployment_env_vars_projects_persisted_config(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Seed a deployment whose config carries an ``env_vars`` block and
    assert the ``Deployment.envVars`` field projects every entry exactly.

    Reads back through ``session.get`` first to prove the value reached the
    DB before the resolver projects it (per the propagation-test recipe).
    """
    deployment = await seed_deployment(session)
    deployment.config = {"env_vars": {"LOG_LEVEL": "debug", "FOO": "bar"}}
    session.add(deployment)
    await session.commit()

    # Read back through the real repository / DB session — proves the value
    # reached the database, not just the resolver.
    db_row = await session.get(Deployment, deployment.id)
    assert db_row is not None
    assert db_row.config == {"env_vars": {"LOG_LEVEL": "debug", "FOO": "bar"}}

    data = await gql(
        client, "get_deployment_env_vars", {"deploymentId": str(deployment.id)}
    )
    env_vars = data["deployment"]["envVars"]
    assert {"name": "LOG_LEVEL", "value": "debug"} in env_vars
    assert {"name": "FOO", "value": "bar"} in env_vars
    assert len(env_vars) == 2


@pytest.mark.asyncio
async def test_deployment_env_vars_empty_when_unset(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Deployments without an ``env_vars`` block surface an empty list."""
    deployment = await seed_deployment(session)

    data = await gql(
        client, "get_deployment_env_vars", {"deploymentId": str(deployment.id)}
    )
    assert data["deployment"]["envVars"] == []


@pytest.mark.asyncio
async def test_deployment_env_vars_merges_environment_layer(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The read resolver merges environment-scope env vars into the
    deployment-level effective dict per FR-002 (deepest-wins). This test
    pins the ordering invariant before US2 lands the write path so the
    resolver behaviour is captured against the future US2 surface too.
    """
    from .seeds import seed_environment

    environment = await seed_environment(session)
    environment.config = {"env_vars": {"OTEL_ENDPOINT": "https://otel", "FOO": "env"}}
    session.add(environment)
    await session.commit()

    deployment = await seed_deployment(session, environment=environment)
    deployment.config = {"env_vars": {"FOO": "dep"}}
    session.add(deployment)
    await session.commit()

    data = await gql(
        client, "get_deployment_env_vars", {"deploymentId": str(deployment.id)}
    )
    env_vars = {row["name"]: row["value"] for row in data["deployment"]["envVars"]}
    assert env_vars["OTEL_ENDPOINT"] == "https://otel"
    # Deployment-scope wins over environment-scope per-key (FR-002).
    assert env_vars["FOO"] == "dep"
