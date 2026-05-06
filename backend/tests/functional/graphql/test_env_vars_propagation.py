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

from styrmin_backend.db.models import (
    Component,
    ComponentConfig,
    Deployment,
    Environment,
)

from ._queries import load_query
from .conftest import gql
from .seeds import (
    seed_application_driver_version,
    seed_deployment,
    seed_environment,
)


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


# ---------------------------------------------------------------------------
# US3 — Deployment.componentEnvVars propagation (T045)
# ---------------------------------------------------------------------------


async def _seed_deployment_with_components(
    session: AsyncSession,
    *,
    component_names: list[str],
) -> Deployment:
    """Seed a deployment whose driver declares ``component_names`` and whose
    Component rows mirror those names (the deployment-side records the
    resolver uses as its driver-component map).
    """
    adv = await seed_application_driver_version(session)
    for name in component_names:
        cc = ComponentConfig(
            name=name,
            config={
                "identifier": {
                    "label": {"app.kubernetes.io/name": f"{name}-app"},
                },
            },
            application_driver_version_id=adv.id,
        )
        session.add(cc)
    await session.commit()
    deployment = await seed_deployment(session, adv=adv)
    for name in component_names:
        comp = Component(
            name=name,
            config={
                "identifier": {
                    "label": {"app.kubernetes.io/name": f"{name}-app"},
                },
            },
            enabled=True,
            deployment_id=deployment.id,
        )
        session.add(comp)
    await session.commit()
    return deployment


@pytest.mark.asyncio
async def test_deployment_component_env_vars_projects_persisted_block(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Seed a deployment whose ``config.components.<name>.env_vars`` is set
    and assert ``Deployment.componentEnvVars`` projects the merged dict
    with ``isOrphaned=false`` (US5 will add the orphan path).
    """
    deployment = await _seed_deployment_with_components(
        session, component_names=["api", "worker"]
    )
    deployment.config = {
        "env_vars": {"LOG_LEVEL": "info"},
        "components": {
            "worker": {
                "env_vars": {"LOG_LEVEL": "debug", "WORKER_QUEUE": "orders"},
            }
        },
    }
    session.add(deployment)
    await session.commit()

    db_row = await session.get(Deployment, deployment.id)
    assert db_row is not None
    assert db_row.config["components"]["worker"]["env_vars"] == {
        "LOG_LEVEL": "debug",
        "WORKER_QUEUE": "orders",
    }

    data = await gql(
        client,
        "get_deployment_component_env_vars",
        {"deploymentId": str(deployment.id)},
    )
    rows = {row["component"]: row for row in data["deployment"]["componentEnvVars"]}
    assert set(rows) == {"api", "worker"}

    # api inherits the deployment-level dict (no component override).
    api_row = rows["api"]
    assert api_row["isOrphaned"] is False
    assert {"name": "LOG_LEVEL", "value": "info"} in api_row["envVars"]
    api_names = {ev["name"] for ev in api_row["envVars"]}
    assert "WORKER_QUEUE" not in api_names

    # worker overrides LOG_LEVEL and adds WORKER_QUEUE.
    worker_row = rows["worker"]
    assert worker_row["isOrphaned"] is False
    worker_pairs = {ev["name"]: ev["value"] for ev in worker_row["envVars"]}
    assert worker_pairs["LOG_LEVEL"] == "debug"
    assert worker_pairs["WORKER_QUEUE"] == "orders"


@pytest.mark.asyncio
async def test_deployment_component_env_vars_empty_when_no_components(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A deployment whose driver declares no components surfaces an empty
    ``componentEnvVars`` list — the deployment-level dict is consumed via
    ``Deployment.envVars`` instead (FR-004 broadcast)."""
    deployment = await seed_deployment(session)
    deployment.config = {"env_vars": {"LOG_LEVEL": "debug"}}
    session.add(deployment)
    await session.commit()

    data = await gql(
        client,
        "get_deployment_component_env_vars",
        {"deploymentId": str(deployment.id)},
    )
    assert data["deployment"]["componentEnvVars"] == []


@pytest.mark.asyncio
async def test_update_deployment_rejects_unknown_component_env_var(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,  # noqa: ARG001 — prevents Prefect dispatch in mutation path
) -> None:
    """``updateDeployment(config: { components: { does_not_exist: { env_vars: ... } } })``
    is rejected at the service boundary with
    ``extensions.code = "UNKNOWN_COMPONENT_ENV_VAR"`` listing the driver's
    known component names (FR-010 / Quickstart Step 4 negative case).

    Surfaces the error through the GraphQL boundary directly — the recipe
    hits the mutation endpoint, expects a non-empty ``errors`` array, and
    asserts on ``extensions.code``. Bypasses the ``gql()`` helper because
    that helper asserts ``"errors" not in payload``.
    """
    deployment = await _seed_deployment_with_components(
        session, component_names=["api", "worker"]
    )
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment_config"),
            "variables": {
                "deploymentId": str(deployment.id),
                "config": {
                    "components": {
                        "does_not_exist": {"env_vars": {"X": "y"}},
                    },
                },
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload, payload
    errors = payload["errors"]
    assert len(errors) == 1
    extensions = errors[0].get("extensions") or {}
    assert extensions.get("code") == "UNKNOWN_COMPONENT_ENV_VAR"
    # The error must list the driver's known component names so the operator
    # can fix the typo without a round-trip. ``StructuredErrorExtension``
    # flattens ``error_metadata`` directly into ``extensions``.
    assert sorted(extensions.get("known_components") or []) == ["api", "worker"]
    assert extensions.get("component_name") == "does_not_exist"


@pytest.mark.asyncio
async def test_update_deployment_rejects_invalid_env_var_name(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,  # noqa: ARG001 — prevents Prefect dispatch in mutation path
) -> None:
    """``updateDeployment(config: { env_vars: { "1BAD": "x" } })`` is rejected
    at the service boundary with ``extensions.code = "INVALID_ENV_VAR_NAME"``
    (FR-006 / SC-003). Pre-validation runs ahead of Pydantic's
    ``ValidationError`` rewrap so the typed code reaches the GraphQL caller
    instead of collapsing to ``INVALID_CONTEXT``.
    """
    deployment = await seed_deployment(session)
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment_config"),
            "variables": {
                "deploymentId": str(deployment.id),
                "config": {"env_vars": {"1BAD": "x"}},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload, payload
    extensions = payload["errors"][0].get("extensions") or {}
    assert extensions.get("code") == "INVALID_ENV_VAR_NAME"
    assert extensions.get("name") == "1BAD"


@pytest.mark.asyncio
async def test_update_deployment_rejects_oversized_env_var_value(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,  # noqa: ARG001 — prevents Prefect dispatch in mutation path
) -> None:
    """A value exceeding the per-value 64 KiB cap is rejected with
    ``extensions.code = "ENV_VAR_SIZE_LIMIT_EXCEEDED"`` (FR-007 / SC-003).
    """
    deployment = await seed_deployment(session)
    oversized = "x" * (64 * 1024 + 1)
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment_config"),
            "variables": {
                "deploymentId": str(deployment.id),
                "config": {"env_vars": {"BIG": oversized}},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload, payload
    extensions = payload["errors"][0].get("extensions") or {}
    assert extensions.get("code") == "ENV_VAR_SIZE_LIMIT_EXCEEDED"
    assert extensions.get("name") == "BIG"


@pytest.mark.asyncio
async def test_update_environment_rejects_invalid_env_var_name(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """``updateEnvironment(config: { env_vars: { "1BAD": "x" } })`` is rejected
    with ``extensions.code = "INVALID_ENV_VAR_NAME"`` (FR-006 / FR-020 /
    SC-003) — exercises the environment-scope pre-validation path.
    """
    environment = await seed_environment(session)
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_environment"),
            "variables": {
                "environmentId": str(environment.id),
                "config": {"env_vars": {"1BAD": "x"}},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload, payload
    extensions = payload["errors"][0].get("extensions") or {}
    assert extensions.get("code") == "INVALID_ENV_VAR_NAME"
    assert extensions.get("name") == "1BAD"


@pytest.mark.asyncio
async def test_deployment_component_env_vars_pre_seeded_persists_block(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Sibling of the rejection test: when a component-level env var block
    targets a driver-declared component, the persisted config round-trips
    through the read resolver intact. Bypasses the mutation path (which
    triggers the full Prefect-flow workflow) by pre-seeding the deployment
    config — the read resolver path is what propagation tests are supposed
    to exercise, and the write-side typed validation is already covered by
    the rejection test above.
    """
    deployment = await _seed_deployment_with_components(
        session, component_names=["api", "worker"]
    )
    deployment.config = {
        "components": {
            "worker": {"env_vars": {"WORKER_QUEUE": "orders"}},
        },
    }
    session.add(deployment)
    await session.commit()

    db_row = await session.get(Deployment, deployment.id)
    assert db_row is not None
    assert db_row.config["components"]["worker"]["env_vars"] == {
        "WORKER_QUEUE": "orders"
    }

    data = await gql(
        client,
        "get_deployment_component_env_vars",
        {"deploymentId": str(deployment.id)},
    )
    rows = {row["component"]: row for row in data["deployment"]["componentEnvVars"]}
    assert rows["worker"]["isOrphaned"] is False
    worker_pairs = {ev["name"]: ev["value"] for ev in rows["worker"]["envVars"]}
    assert worker_pairs == {"WORKER_QUEUE": "orders"}
    # api inherits the empty deployment-level dict and therefore does not
    # appear in the result (the resolver omits components whose merged dict
    # is empty to keep the surface tidy).
    assert "api" not in rows
