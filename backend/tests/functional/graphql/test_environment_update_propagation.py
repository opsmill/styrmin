"""GraphQL ↔ DB propagation tests for ``updateEnvironment`` fanout (009).

Cover the three end-to-end propagation invariants the fanout owes the
GraphQL boundary (Phase 3 / US1):

1. **Fanout-dispatch + mutation-result coupling (T022):** the mutation
   succeeds, the env-config row is persisted, and exactly one new Task is
   created per non-tombstoned/non-internal deployment in the
   environment.
2. **Per-deployment no-op skip (T023):** when every deployment is already
   at the target config, the mutation succeeds and zero new Tasks are
   created (FR-010 / per-deployment no-op).
3. **Partial-fanout recovery (T024):** when the env-config row is already
   at the target config but one deployment lags (its active instance was
   generated against the previous config), submitting the same input
   dispatches a Task for the laggard only — the regression guard for
   critique X1.

The tests drive the **real** ``update_environment`` service via the
GraphQL mutation, with the Prefect dispatch wired through
``prefect_manager_mock`` so ``apply_state`` returns without a real
workflow runtime.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession  # noqa: F401
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.context.models.config import EnvironmentConfig
from styrmin_backend.db.models import (
    ApplicationInstance,
    Deployment,
    Environment,
    InstanceStatus,
    Task,
)

from ._queries import load_query  # noqa: F401  — kept for parity with 008
from .conftest import gql
from .seeds import (
    global_context_dict,
    seed_application_driver_version,
    seed_deployment,
    seed_environment,
)

__all__ = ["gql"]


async def _attach_instance_at_config(
    session: AsyncSession,
    deployment: Deployment,
    env_config_dict: dict | None,
) -> ApplicationInstance:
    """Persist an ``ApplicationInstance`` for ``deployment`` whose context's
    environment-config slice equals ``env_config_dict``, and wire it as
    the deployment's active instance. Used to emulate the post-fanout
    "already at config" state for no-op + partial-recovery tests.
    """
    instance = ApplicationInstance(
        name=f"instance-{uuid4().hex[:8]}",
        application_version=deployment.application_version,
        status=InstanceStatus.PENDING,
        deployment_id=deployment.id,
        application_driver_version_id=deployment.application_driver_version_id,
        context=global_context_dict(environment_config=env_config_dict),
        sequence=1,
    )
    session.add(instance)
    await session.commit()
    deployment.active_application_instance_id = instance.id
    deployment.last_instance_sequence = instance.sequence
    session.add(deployment)
    await session.commit()
    return instance


async def _count_tasks_for_environment(session: AsyncSession, environment_id) -> int:
    """Count Tasks across every deployment in ``environment_id``."""
    result = await session.exec(
        select(Task).join(Deployment).where(Deployment.environment_id == environment_id)
    )
    return len(list(result.all()))


# ---------------------------------------------------------------------------
# T022 — fanout dispatch + mutation-result coupling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_environment_dispatches_only_active_deployments(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """Pre-seed an environment with 1 active and 1 tombstoned deployment.
    ``updateEnvironment`` must succeed, persist the env-config row, and
    dispatch exactly one new Task (the active deployment only — the
    tombstoned row is excluded per FR-012).
    """
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())

    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session)
    active = await seed_deployment(session, environment=environment, adv=adv)
    tombstoned = await seed_deployment(
        session, environment=environment, adv=adv, name="tombstoned-dep"
    )
    # Tombstone the second deployment by setting deleted_at directly
    # (the soft-delete mechanism the fanout filters on).
    from datetime import datetime, timezone

    tombstoned.deleted_at = datetime.now(timezone.utc)
    session.add(tombstoned)
    await session.commit()
    active_id = active.id
    tombstoned_id = tombstoned.id
    environment_id = environment.id

    # Pre-flight: zero Tasks.
    pre_count = await _count_tasks_for_environment(session, environment_id)
    assert pre_count == 0

    payload = await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment_id),
            "input": {
                "envVars": [{"name": "OTEL_ENDPOINT", "value": "https://otel.staging"}]
            },
        },
    )
    assert payload["updateEnvironment"]["config"] == {
        "env_vars": {"OTEL_ENDPOINT": "https://otel.staging"}
    }

    # The env-config row is committed before any dispatch.
    session.expire_all()
    refreshed_env = await session.get(Environment, environment_id)
    assert refreshed_env is not None
    assert refreshed_env.config == {
        "env_vars": {"OTEL_ENDPOINT": "https://otel.staging"}
    }

    # Exactly one Task — for the active deployment.
    result = await session.exec(select(Task).where(Task.deployment_id == active_id))
    active_tasks = list(result.all())
    assert len(active_tasks) == 1

    result = await session.exec(select(Task).where(Task.deployment_id == tombstoned_id))
    tombstoned_tasks = list(result.all())
    assert tombstoned_tasks == []


# ---------------------------------------------------------------------------
# T023 — per-deployment no-op skip (FR-010)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_environment_skips_when_all_deployments_at_config(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """Pre-seed two deployments whose active instances are already at the
    target config. Submitting that config dispatches zero Tasks
    (per-deployment no-op detection per FR-010).
    """
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())

    target = {"env_vars": {"OTEL_ENDPOINT": "https://otel.staging"}}
    environment = await seed_environment(session)
    environment.config = target
    session.add(environment)
    await session.commit()

    adv = await seed_application_driver_version(session)
    dep_a = await seed_deployment(session, environment=environment, adv=adv)
    dep_b = await seed_deployment(
        session, environment=environment, adv=adv, name="dep-noop-b"
    )
    await _attach_instance_at_config(session, dep_a, target)
    await _attach_instance_at_config(session, dep_b, target)
    environment_id = environment.id

    pre_count = await _count_tasks_for_environment(session, environment_id)
    assert pre_count == 0

    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment_id),
            "input": {
                "envVars": [{"name": "OTEL_ENDPOINT", "value": "https://otel.staging"}]
            },
        },
    )

    # No Tasks — both deployments were skipped.
    post_count = await _count_tasks_for_environment(session, environment_id)
    assert post_count == 0


# ---------------------------------------------------------------------------
# T024 — partial-fanout recovery (critique X1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_environment_partial_recovery_dispatches_only_laggard(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """Pre-seed three deployments where two are at v2 and one is at v1
    (e.g. a previous fanout failed mid-flight on the laggard). Submitting
    v2 must dispatch exactly one new Task (the laggard).
    """
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())

    config_v1 = {"env_vars": {"FOO": "v1"}}
    config_v2 = {"env_vars": {"FOO": "v2"}}

    environment = await seed_environment(session)
    environment.config = config_v2
    session.add(environment)
    await session.commit()

    adv = await seed_application_driver_version(session)
    dep_a = await seed_deployment(
        session, environment=environment, adv=adv, name="dep-at-v2-a"
    )
    dep_b = await seed_deployment(
        session, environment=environment, adv=adv, name="dep-laggard-b"
    )
    dep_c = await seed_deployment(
        session, environment=environment, adv=adv, name="dep-at-v2-c"
    )
    await _attach_instance_at_config(session, dep_a, config_v2)
    await _attach_instance_at_config(session, dep_b, config_v1)
    await _attach_instance_at_config(session, dep_c, config_v2)
    dep_a_id, dep_b_id, dep_c_id = dep_a.id, dep_b.id, dep_c.id
    dep_a_name, dep_c_name = dep_a.name, dep_c.name
    environment_id = environment.id

    pre_count = await _count_tasks_for_environment(session, environment_id)
    assert pre_count == 0

    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment_id),
            "input": {"envVars": [{"name": "FOO", "value": "v2"}]},
        },
    )

    # Exactly one Task — for the laggard (B).
    result = await session.exec(select(Task).where(Task.deployment_id == dep_b_id))
    laggard_tasks = list(result.all())
    assert len(laggard_tasks) == 1

    for converged_id, converged_name in (
        (dep_a_id, dep_a_name),
        (dep_c_id, dep_c_name),
    ):
        result = await session.exec(
            select(Task).where(Task.deployment_id == converged_id)
        )
        assert list(result.all()) == [], (
            f"deployment {converged_name} unexpectedly received a Task; "
            "partial-fanout recovery must skip already-converged peers"
        )


# ---------------------------------------------------------------------------
# T041 — typed-input top-level field round-trips (one assertion per
# `contracts/graphql.md` §4 row)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_environment_input_env_vars_round_trip(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``input.envVars`` round-trips to ``Environment.config.env_vars``."""
    environment = await seed_environment(session)
    payload = await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment.id),
            "input": {"envVars": [{"name": "X", "value": "y"}]},
        },
    )
    assert payload["updateEnvironment"]["config"] == {"env_vars": {"X": "y"}}
    db_row = await session.get(Environment, environment.id)
    assert db_row is not None
    assert db_row.config == {"env_vars": {"X": "y"}}


@pytest.mark.asyncio
async def test_update_environment_input_ip_whitelist_round_trip(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``input.ipWhitelist`` round-trips to ``Environment.config.ip_whitelist``."""
    environment = await seed_environment(session)
    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment.id),
            "input": {"ipWhitelist": ["10.0.0.0/8"]},
        },
    )
    db_row = await session.get(Environment, environment.id)
    assert db_row is not None
    assert db_row.config == {"ip_whitelist": ["10.0.0.0/8"]}


@pytest.mark.asyncio
async def test_update_environment_input_fqdn_suffix_round_trip(
    client: AsyncClient, session: AsyncSession
) -> None:
    environment = await seed_environment(session)
    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment.id),
            "input": {"fqdnSuffix": "test.example.com"},
        },
    )
    db_row = await session.get(Environment, environment.id)
    assert db_row is not None
    assert db_row.config == {"fqdn_suffix": "test.example.com"}


@pytest.mark.asyncio
async def test_update_environment_input_external_url_scheme_round_trip(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``ExternalUrlScheme`` enum lowers to the ``Literal`` string."""
    environment = await seed_environment(session)
    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment.id),
            "input": {"externalUrlScheme": "HTTPS"},
        },
    )
    db_row = await session.get(Environment, environment.id)
    assert db_row is not None
    assert db_row.config == {"external_url_scheme": "https"}


@pytest.mark.asyncio
async def test_update_environment_input_external_url_port_round_trip(
    client: AsyncClient, session: AsyncSession
) -> None:
    environment = await seed_environment(session)
    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment.id),
            "input": {"externalUrlPort": 8443},
        },
    )
    db_row = await session.get(Environment, environment.id)
    assert db_row is not None
    assert db_row.config == {"external_url_port": 8443}


@pytest.mark.asyncio
async def test_update_environment_input_external_dns_endpoints_type_round_trip(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``ExternalDnsEndpointsType.NODE_EXTERNAL_IP`` lowers to ``"NodeExternalIP"``."""
    environment = await seed_environment(session)
    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment.id),
            "input": {"externalDnsEndpointsType": "NODE_EXTERNAL_IP"},
        },
    )
    db_row = await session.get(Environment, environment.id)
    assert db_row is not None
    assert db_row.config == {"external_dns_endpoints_type": "NodeExternalIP"}


@pytest.mark.asyncio
async def test_update_environment_input_ingress_class_round_trip(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``input.ingressClass`` round-trips to ``Environment.config.ingress_class`` (011 / FR-001)."""
    environment = await seed_environment(session)
    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment.id),
            "input": {"ingressClass": "nginx"},
        },
    )
    db_row = await session.get(Environment, environment.id)
    assert db_row is not None
    assert db_row.config == {"ingress_class": "nginx"}


@pytest.mark.asyncio
async def test_update_environment_input_db_size_round_trip(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``input.dbSize`` round-trips to ``Environment.config.db_size`` (011 / FR-001)."""
    environment = await seed_environment(session)
    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment.id),
            "input": {"dbSize": "10Gi"},
        },
    )
    db_row = await session.get(Environment, environment.id)
    assert db_row is not None
    assert db_row.config == {"db_size": "10Gi"}


@pytest.mark.asyncio
async def test_update_environment_input_backup_ttl_round_trip(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``input.backupTtl`` round-trips to ``Environment.config.backup_ttl``.

    016 / FR-005 — the environment scope is the feature's primary setter, so
    the typed input must actually land the value on the persisted config.
    """
    environment = await seed_environment(session)
    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment.id),
            "input": {"backupTtl": "2160h"},
        },
    )
    db_row = await session.get(Environment, environment.id)
    assert db_row is not None
    assert db_row.config == {"backup_ttl": "2160h"}


@pytest.mark.asyncio
async def test_update_environment_input_backup_ttl_preserved_when_resubmitted(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Re-submitting ``backupTtl`` alongside other fields keeps the policy.

    016 / FR-005 — a client that carries the stored value through its
    full-replacement input keeps the environment-scope policy intact.
    """
    environment = await seed_environment(session)
    environment.config = {"backup_ttl": "2160h"}
    session.add(environment)
    await session.commit()
    environment_id = environment.id

    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment_id),
            "input": {
                "backupTtl": "2160h",
                "envVars": [{"name": "LOG_LEVEL", "value": "debug"}],
            },
        },
    )
    session.expire_all()
    db_row = await session.get(Environment, environment_id)
    assert db_row is not None
    assert db_row.config == {
        "backup_ttl": "2160h",
        "env_vars": {"LOG_LEVEL": "debug"},
    }


@pytest.mark.asyncio
async def test_update_environment_omitting_backup_ttl_clears_it(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Omitting ``backupTtl`` clears it — full-replacement semantics.

    016 / FR-005 — this is exactly why every client that hand-assembles an
    ``UpdateEnvironmentInput`` (e.g. the web UI's
    ``buildFullReplacementInput``) MUST carry the stored value through:
    a submission without the field is a request to drop the policy.
    """
    environment = await seed_environment(session)
    environment.config = {"backup_ttl": "2160h"}
    session.add(environment)
    await session.commit()
    environment_id = environment.id

    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment_id),
            "input": {"envVars": [{"name": "LOG_LEVEL", "value": "debug"}]},
        },
    )
    session.expire_all()
    db_row = await session.get(Environment, environment_id)
    assert db_row is not None
    assert db_row.config == {"env_vars": {"LOG_LEVEL": "debug"}}
    assert db_row.config is not None
    assert "backup_ttl" not in db_row.config


# ---------------------------------------------------------------------------
# 016 / T027 — malformed backup_ttl rejected at the mutation boundary
# (US3, FR-004, SC-003)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_environment_rejects_malformed_backup_ttl(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``backupTtl: "30d"`` is rejected loudly and persists nothing.

    016 / FR-004 + SC-003. Two halves, both load-bearing:

    1. The mutation returns a typed error — ``extensions.code`` set by the
       ``Invalid*ContextError`` family — whose message names ``backup_ttl``
       and hints the ``720h`` syntax, so the operator can fix the value
       without reading our source.
    2. The environment's stored config is byte-identical to what it was
       before the call. ``30d`` looks like a plausible retention but Go has
       no day unit, so Velero would reject it asynchronously at apply time,
       long after the operator walked away — hence "rejected at submission".
    """
    environment = await seed_environment(session)
    stored_config = {"backup_ttl": "2160h", "ingress_class": "nginx"}
    environment.config = stored_config
    session.add(environment)
    await session.commit()
    environment_id = environment.id

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_environment"),
            "variables": {
                "environmentId": str(environment_id),
                "input": {"backupTtl": "30d", "ingressClass": "nginx"},
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload, payload
    error = payload["errors"][0]
    assert error["extensions"]["code"] == "VALIDATION_ERROR", payload
    assert "backup_ttl" in error["message"], payload
    assert "720h" in error["message"], payload

    # SC-003: nothing malformed reached storage — the prior policy survives.
    session.expire_all()
    db_row = await session.get(Environment, environment_id)
    assert db_row is not None
    assert db_row.config == stored_config


# ---------------------------------------------------------------------------
# 011 / T005 — schema-walking input completeness check (FR-002)
# ---------------------------------------------------------------------------


def test_update_environment_input_covers_every_environment_config_field() -> None:
    """Schema-walking completeness check (011 / FR-002).

    Walks ``EnvironmentConfig.model_fields`` (Pydantic) and asserts that for
    every public field, an equivalently-named Strawberry field exists on
    ``UpdateEnvironmentInput``. Future schema drift — e.g., adding a field
    to ``BaseConfigSection`` without updating the input — fails this test
    with a precise message naming the missing field.

    Compares on ``python_name`` (snake_case) so the assertion is robust
    against Strawberry's automatic GraphQL camelCase conversion.
    """
    from styrmin_backend.api.definitions.environment.inputs import (
        UpdateEnvironmentInput,
    )

    input_field_names = {
        f.python_name for f in UpdateEnvironmentInput.__strawberry_definition__.fields
    }
    pydantic_field_names = set(EnvironmentConfig.model_fields.keys())

    missing = pydantic_field_names - input_field_names
    assert not missing, (
        f"UpdateEnvironmentInput is missing {missing} — every "
        f"EnvironmentConfig field MUST have a corresponding input field "
        f"(FR-002). Add the field to "
        f"backend/styrmin_backend/api/definitions/environment/inputs.py."
    )


@pytest.mark.asyncio
async def test_update_environment_input_dedicated_ingress_round_trip(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Nested ``DedicatedIngressInput`` fields project onto ``Environment.config``."""
    environment = await seed_environment(session)
    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment.id),
            "input": {
                "dedicatedIngress": {
                    "implementation": "traefik",
                    "type": "ingress",
                }
            },
        },
    )
    db_row = await session.get(Environment, environment.id)
    assert db_row is not None
    assert db_row.config == {
        "dedicated_ingress": {"implementation": "traefik", "type": "ingress"}
    }


@pytest.mark.asyncio
async def test_update_environment_input_scheduling_round_trip(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Nested ``SchedulingInput.runtimeClass`` projects onto ``Environment.config``."""
    environment = await seed_environment(session)
    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment.id),
            "input": {"scheduling": {"runtimeClass": "kata"}},
        },
    )
    db_row = await session.get(Environment, environment.id)
    assert db_row is not None
    assert db_row.config == {"scheduling": {"runtime_class": "kata"}}


# ---------------------------------------------------------------------------
# T042 — nested-input field projections (per `contracts/graphql.md` §4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_environment_deployment_ref_name_is_stored_as_the_id(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """``deploymentRef.deploymentName`` reaches ``Environment.config`` as the named
    deployment's id, with no name, and the ``config`` read returns the same (027 FR-001).
    The fan-out redeploy of the named deployment resolves the stored id."""
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())
    environment = await seed_environment(session)
    named = await seed_deployment(session, environment=environment, name="db")
    environment_id, named_id = environment.id, named.id

    payload = await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment_id),
            "input": {
                "scheduling": {
                    "podAntiAffinity": {
                        "preferred": [
                            {
                                "weight": 100,
                                "term": {
                                    "topologyKey": "kubernetes.io/hostname",
                                    "deploymentRef": {"deploymentName": "db"},
                                },
                            }
                        ]
                    }
                }
            },
        },
    )

    expected = {
        "scheduling": {
            "pod_anti_affinity": {
                "preferred": [
                    {
                        "weight": 100,
                        "term": {
                            "topology_key": "kubernetes.io/hostname",
                            "deployment_ref": {"deployment_id": str(named_id)},
                        },
                    }
                ]
            }
        }
    }
    assert payload["updateEnvironment"]["config"] == expected
    session.expire_all()
    db_row = await session.get(Environment, environment_id)
    assert db_row is not None
    assert db_row.config == expected
    data = await gql(
        client, "get_environment_config", {"environmentId": str(environment_id)}
    )
    assert data["environment"]["config"] == expected
    tasks = await session.exec(select(Task).where(Task.deployment_id == named_id))
    assert len(list(tasks.all())) == 1


@pytest.mark.asyncio
async def test_update_environment_refuses_a_term_that_names_a_missing_deployment(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """A term whose ``deploymentName`` matches no deployment of the environment is
    refused with the term's path, the stored config is unchanged and no deployment is
    redeployed (027 FR-002, US3 scenario 1)."""
    prefect_manager_mock.run_action = AsyncMock()
    environment = await seed_environment(session)
    environment.config = {"ip_whitelist": ["10.0.0.0/8"]}
    session.add(environment)
    await session.commit()
    deployment = await seed_deployment(session, environment=environment, name="db")
    environment_id, deployment_id = environment.id, deployment.id

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_environment"),
            "variables": {
                "environmentId": str(environment_id),
                "input": {
                    "scheduling": {
                        "podAntiAffinity": {
                            "preferred": [
                                {
                                    "weight": 100,
                                    "term": {
                                        "topologyKey": "kubernetes.io/hostname",
                                        "deploymentRef": {"deploymentName": "missing"},
                                    },
                                }
                            ]
                        }
                    }
                },
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload, payload
    extensions = payload["errors"][0].get("extensions") or {}
    assert extensions.get("code") == "VALIDATION_ERROR"
    assert (
        extensions.get("path")
        == "environment.config.scheduling.pod_anti_affinity.preferred[0].term"
    )
    assert extensions.get("deployment_name") == "missing"
    session.expire_all()
    db_row = await session.get(Environment, environment_id)
    assert db_row is not None
    assert db_row.config == {"ip_whitelist": ["10.0.0.0/8"]}
    tasks = await session.exec(select(Task).where(Task.deployment_id == deployment_id))
    assert list(tasks.all()) == []
    prefect_manager_mock.run_action.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("ref_field", ["deployment_name", "deployment_id"])
async def test_create_environment_refuses_a_term_that_names_a_deployment(
    client: AsyncClient, session: AsyncSession, ref_field: str
) -> None:
    """A new environment has no deployment, so a term that names one, by name or by
    id, is refused with the term's path and no environment is created (027 FR-002,
    US3 scenario 2). The named deployment exists in another environment."""
    other_environment = await seed_environment(session)
    other = await seed_deployment(session, environment=other_environment, name="db")
    cluster_id = other_environment.cluster_id
    identifier = other.name if ref_field == "deployment_name" else str(other.id)

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("create_environment"),
            "variables": {
                "name": "new-env",
                "clusterId": str(cluster_id),
                "config": {
                    "scheduling": {
                        "pod_anti_affinity": {
                            "preferred": [
                                {
                                    "weight": 100,
                                    "term": {
                                        "topology_key": "kubernetes.io/hostname",
                                        "deployment_ref": {ref_field: identifier},
                                    },
                                }
                            ]
                        }
                    }
                },
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload, payload
    extensions = payload["errors"][0].get("extensions") or {}
    assert extensions.get("code") == "VALIDATION_ERROR"
    assert (
        extensions.get("path")
        == "environment.config.scheduling.pod_anti_affinity.preferred[0].term"
    )
    assert extensions.get(ref_field) == identifier
    named = (
        "deployment 'db'"
        if ref_field == "deployment_name"
        else f"deployment id {identifier}"
    )
    assert payload["errors"][0]["message"] == (
        "Affinity term at environment.config.scheduling.pod_anti_affinity.preferred[0].term "
        f"names {named}, but a new environment has no deployments yet. Add the term "
        "with updateEnvironment once the deployment exists."
    )
    session.expire_all()
    created = await session.exec(
        select(Environment).where(Environment.name == "new-env")
    )
    assert list(created.all()) == []


@pytest.mark.asyncio
async def test_update_environment_input_dedicated_ingress_service_nested(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``DedicatedIngressInput.service.loadBalancerIp`` round-trips."""
    environment = await seed_environment(session)
    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment.id),
            "input": {
                "dedicatedIngress": {
                    "service": {
                        "type": "LoadBalancer",
                        "loadBalancerIp": "10.0.0.1",
                    }
                }
            },
        },
    )
    db_row = await session.get(Environment, environment.id)
    assert db_row is not None
    assert db_row.config == {
        "dedicated_ingress": {
            "service": {"type": "LoadBalancer", "load_balancer_ip": "10.0.0.1"}
        }
    }


@pytest.mark.asyncio
async def test_update_environment_input_scheduling_resources_nested(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``SchedulingInput.resources.requests`` round-trips."""
    environment = await seed_environment(session)
    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment.id),
            "input": {
                "scheduling": {
                    "resources": {
                        "requests": {"cpu": "100m", "memory": "256Mi"},
                        "limits": {"cpu": "500m", "memory": "512Mi"},
                    }
                }
            },
        },
    )
    db_row = await session.get(Environment, environment.id)
    assert db_row is not None
    assert db_row.config == {
        "scheduling": {
            "resources": {
                "requests": {"cpu": "100m", "memory": "256Mi"},
                "limits": {"cpu": "500m", "memory": "512Mi"},
            }
        }
    }


@pytest.mark.asyncio
async def test_update_environment_input_scheduling_tolerations_nested(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``SchedulingInput.tolerations`` with enums round-trips."""
    environment = await seed_environment(session)
    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment.id),
            "input": {
                "scheduling": {
                    "tolerations": [
                        {
                            "key": "node-role.kubernetes.io/control-plane",
                            "operator": "EXISTS",
                            "effect": "NO_SCHEDULE",
                        }
                    ]
                }
            },
        },
    )
    db_row = await session.get(Environment, environment.id)
    assert db_row is not None
    assert db_row.config == {
        "scheduling": {
            "tolerations": [
                {
                    "key": "node-role.kubernetes.io/control-plane",
                    "operator": "Exists",
                    "effect": "NoSchedule",
                }
            ]
        }
    }


@pytest.mark.asyncio
async def test_update_environment_input_scheduling_topology_spread_nested(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``SchedulingInput.topologySpreadConstraints`` with ``WhenUnsatisfiable``."""
    environment = await seed_environment(session)
    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment.id),
            "input": {
                "scheduling": {
                    "topologySpreadConstraints": [
                        {
                            "maxSkew": 1,
                            "topologyKey": "topology.kubernetes.io/zone",
                            "whenUnsatisfiable": "DO_NOT_SCHEDULE",
                        }
                    ]
                }
            },
        },
    )
    db_row = await session.get(Environment, environment.id)
    assert db_row is not None
    assert db_row.config == {
        "scheduling": {
            "topology_spread_constraints": [
                {
                    "max_skew": 1,
                    "topology_key": "topology.kubernetes.io/zone",
                    "when_unsatisfiable": "DoNotSchedule",
                }
            ]
        }
    }


@pytest.mark.asyncio
async def test_update_environment_input_scheduling_inject_nested(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``SchedulingInput.inject`` boolean opt-out flags round-trip."""
    environment = await seed_environment(session)
    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment.id),
            "input": {
                "scheduling": {"inject": {"tolerations": False, "resources": True}}
            },
        },
    )
    db_row = await session.get(Environment, environment.id)
    assert db_row is not None
    assert db_row.config == {
        "scheduling": {"inject": {"tolerations": False, "resources": True}}
    }


# ---------------------------------------------------------------------------
# T043 — typed-error rejection paths (per `contracts/graphql.md` §4 behavioural rows)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_environment_typed_input_rejects_invalid_env_var_name(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``input.envVars[].name = "1bad"`` → ``extensions.code = "INVALID_ENV_VAR_NAME"``.

    The persisted env-config row must remain unchanged (the mutation
    failed before ``uow.commit()``).
    """
    environment = await seed_environment(session)
    environment_id = environment.id
    pre_config = environment.config
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_environment"),
            "variables": {
                "environmentId": str(environment_id),
                "input": {"envVars": [{"name": "1bad", "value": "y"}]},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload, payload
    extensions = payload["errors"][0].get("extensions") or {}
    assert extensions.get("code") == "INVALID_ENV_VAR_NAME"
    session.expire_all()
    db_row = await session.get(Environment, environment_id)
    assert db_row is not None
    assert db_row.config == pre_config


@pytest.mark.asyncio
async def test_update_environment_typed_input_rejects_oversized_value(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``input.envVars[].value`` exceeding the per-value cap →
    ``extensions.code = "ENV_VAR_SIZE_LIMIT_EXCEEDED"``.
    """
    environment = await seed_environment(session)
    environment_id = environment.id
    pre_config = environment.config
    oversized = "x" * (64 * 1024 + 1)
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_environment"),
            "variables": {
                "environmentId": str(environment_id),
                "input": {"envVars": [{"name": "BIG", "value": oversized}]},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload, payload
    extensions = payload["errors"][0].get("extensions") or {}
    assert extensions.get("code") == "ENV_VAR_SIZE_LIMIT_EXCEEDED"
    session.expire_all()
    db_row = await session.get(Environment, environment_id)
    assert db_row is not None
    assert db_row.config == pre_config


@pytest.mark.asyncio
async def test_update_environment_typed_input_rejects_duplicate_env_var_name(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``input.envVars`` carrying two rows with the same name →
    ``extensions.code = "DUPLICATE_ENV_VAR_NAME"``.
    """
    environment = await seed_environment(session)
    environment_id = environment.id
    pre_config = environment.config
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_environment"),
            "variables": {
                "environmentId": str(environment_id),
                "input": {
                    "envVars": [
                        {"name": "X", "value": "1"},
                        {"name": "X", "value": "2"},
                    ]
                },
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload, payload
    extensions = payload["errors"][0].get("extensions") or {}
    assert extensions.get("code") == "DUPLICATE_ENV_VAR_NAME"
    session.expire_all()
    db_row = await session.get(Environment, environment_id)
    assert db_row is not None
    assert db_row.config == pre_config


# ---------------------------------------------------------------------------
# T044 — full-replacement semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_environment_full_replacement_clears_omitted_fields(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Pre-seed environment with ``ipWhitelist=["10.0.0.0/8"]``. Submit
    ``updateEnvironment(input: { envVars: [...] })`` (omitting
    ``ipWhitelist``). The persisted ``Environment.config`` must NOT carry
    the prior ``ip_whitelist`` value (full-replacement semantics).
    """
    environment = await seed_environment(session)
    environment.config = {"ip_whitelist": ["10.0.0.0/8"]}
    session.add(environment)
    await session.commit()
    environment_id = environment.id

    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment_id),
            "input": {"envVars": [{"name": "X", "value": "y"}]},
        },
    )
    session.expire_all()
    db_row = await session.get(Environment, environment_id)
    assert db_row is not None
    # Full-replacement: only env_vars is set; ip_whitelist is gone
    # (omitted from the persisted config dict).
    assert db_row.config == {"env_vars": {"X": "y"}}
    assert db_row.config is not None
    assert "ip_whitelist" not in db_row.config


# ---------------------------------------------------------------------------
# T045 — ENVIRONMENT_NOT_FOUND rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_environment_unknown_id_returns_not_found(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A random ``environmentId`` → ``extensions.code = "NOT_FOUND"`` (the
    code surfaced by ``EnvironmentNotFoundError``, per
    ``services/exceptions.py``). No DB writes occur, no Tasks dispatched.
    """
    random_id = str(uuid4())
    pre_task_count = len((await session.exec(select(Task))).all())
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_environment"),
            "variables": {
                "environmentId": random_id,
                "input": {"envVars": [{"name": "X", "value": "y"}]},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload, payload
    extensions = payload["errors"][0].get("extensions") or {}
    assert extensions.get("code") == "NOT_FOUND"
    # No env-config row was written and no Tasks were dispatched.
    post_task_count = len((await session.exec(select(Task))).all())
    assert post_task_count == pre_task_count
