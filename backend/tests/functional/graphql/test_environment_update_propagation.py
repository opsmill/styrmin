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
from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterContext,
    DeploymentContext,
    EnvironmentContext,
    GlobalContext,
    InstanceContext,
)
from styrmin_backend.context.models.helm import (
    ChartInfo,
    HelmInfo,
    RepositoryInfo,
)
from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    ResolvedConfig,
)
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
    seed_application_driver_version,
    seed_deployment,
    seed_environment,
)

__all__ = ["gql"]


def _make_global_context_dict(env_config_dict: dict | None) -> dict:
    """Build a serialised ``GlobalContext`` JSON dict whose
    ``environment.config`` slice equals ``env_config_dict``.

    Mirrors the unit-test helper in ``test_environment_services.py``;
    used here to pre-seed an ``ApplicationInstance.context`` JSON column
    that ``_deployment_already_at_config`` can read back.
    """
    deployment_id = uuid4()
    chart_id = uuid4()
    repo_id = uuid4()
    env_config = (
        EnvironmentConfig.model_validate(env_config_dict)
        if env_config_dict is not None
        else EnvironmentConfig()
    )
    ctx = GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="prop-env", config=env_config),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(),
            deployment_id=deployment_id,
            namespace="prop-ns",
            release_reference="prop-ref",
        ),
        app=ApplicationContext(
            name="prop-app",
            version="1.0.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=chart_id,
                    name="prop-chart",
                    version="0.1.0",
                    values_template="",
                ),
                repository=RepositoryInfo(id=repo_id, url="https://example.com"),
            ),
        ),
    )
    return ctx.model_dump(mode="json")


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
        context=_make_global_context_dict(env_config_dict),
    )
    session.add(instance)
    await session.commit()
    deployment.active_application_instance_id = instance.id
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
            "config": {"env_vars": {"OTEL_ENDPOINT": "https://otel.staging"}},
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
        {"environmentId": str(environment_id), "config": target},
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
        {"environmentId": str(environment_id), "config": config_v2},
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
