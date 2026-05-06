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

from styrmin_backend.db.models import Deployment, Environment

from .conftest import gql
from .seeds import seed_deployment, seed_environment


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


# ---------------------------------------------------------------------------
# US2 — Environment.envVars propagation (T036)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_environment_env_vars_round_trip_through_mutation(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``updateEnvironment(config: { env_vars: ... })`` → ``Environment.envVars``.

    Drives the write path through the real ``update_environment`` service,
    proves the value reached the DB by reading the row back through
    ``session.get``, and asserts the ``Environment.envVars`` field projects
    every entry exactly. Mirrors the US1 deployment-side propagation test.
    """
    environment = await seed_environment(session)

    update_payload = await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment.id),
            "config": {
                "env_vars": {"OTEL_EXPORTER_OTLP_ENDPOINT": "https://otel.staging"}
            },
        },
    )
    assert update_payload["updateEnvironment"]["config"] == {
        "env_vars": {"OTEL_EXPORTER_OTLP_ENDPOINT": "https://otel.staging"}
    }

    # Prove the value reached the database via the real session, not just
    # the resolver in-memory object.
    await session.refresh(environment)
    db_row = await session.get(Environment, environment.id)
    assert db_row is not None
    assert db_row.config == {
        "env_vars": {"OTEL_EXPORTER_OTLP_ENDPOINT": "https://otel.staging"}
    }

    data = await gql(
        client,
        "get_environment_env_vars",
        {"environmentId": str(environment.id)},
    )
    env_vars = data["environment"]["envVars"]
    assert env_vars == [
        {"name": "OTEL_EXPORTER_OTLP_ENDPOINT", "value": "https://otel.staging"}
    ]


@pytest.mark.asyncio
async def test_environment_env_vars_empty_when_unset(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Environments without any ``env_vars`` block surface an empty list."""
    environment = await seed_environment(session)
    data = await gql(
        client,
        "get_environment_env_vars",
        {"environmentId": str(environment.id)},
    )
    assert data["environment"]["envVars"] == []


@pytest.mark.asyncio
async def test_environment_env_vars_projects_persisted_config(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A pre-seeded environment config with multiple env vars surfaces every
    entry through ``Environment.envVars``.
    """
    environment = await seed_environment(session)
    environment.config = {"env_vars": {"OTEL": "https://otel", "TIER": "staging"}}
    session.add(environment)
    await session.commit()

    db_row = await session.get(Environment, environment.id)
    assert db_row is not None
    assert db_row.config == {"env_vars": {"OTEL": "https://otel", "TIER": "staging"}}

    data = await gql(
        client,
        "get_environment_env_vars",
        {"environmentId": str(environment.id)},
    )
    env_vars = data["environment"]["envVars"]
    assert {"name": "OTEL", "value": "https://otel"} in env_vars
    assert {"name": "TIER", "value": "staging"} in env_vars
    assert len(env_vars) == 2
