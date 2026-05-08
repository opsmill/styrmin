"""End-to-end coverage for environment-config update + fanout (009).

Drives the user-facing path for ``updateEnvironment`` (SDK / GraphQL):
the env-config row is persisted, every active deployment receives a
redeploy Task, and the new env-config slice lands on the rendered pod
spec on the vcluster. The flow is API/SDK-only (no UI page navigation),
hence the ``api_only`` markers per AGENTS.md "Dual-entrypoint scope".

Scenarios:

* ``test_us1_environment_update_fans_out_to_all_deployments`` — Quickstart
  Steps 1-3: an ``updateEnvironment`` call setting a single env var on
  three peer deployments propagates to each deployment's container[0]
  ``env`` block within ``RECONCILE_TIMEOUT_SECONDS``, and each
  deployment's timeline gains a fresh entry whose ``contextDiff``
  records the env-config change (FR-006 / FR-010 / FR-023).
* ``test_us1_environment_update_failure_isolation`` — Quickstart Step 7:
  one deployment's chart fails to render under a specific scheduling
  override; the env-config row still persists, the healthy peer
  converges, and the failing deployment's timeline records a failed
  Task. Currently skipped pending a multi-driver fixture (see body for
  unskip path).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, AsyncGenerator, Callable

import pytest
from kubernetes_asyncio import client as kubeclient
from styrmin_sdk import StyrminClient
from styrmin_sdk.graphql._generated.input_types import (
    EnvVarInput,
    SchedulingInput,
    UpdateEnvironmentInput,
)

from tests.e2e.drivers import ScenarioDriver

RECONCILE_TIMEOUT_SECONDS = 480.0
RECONCILE_POLL_INTERVAL = 3.0


async def _wait_for_pod_template(
    vcluster: dict,
    *,
    namespace: str,
    label_selector: str,
    predicate: Callable[[Any], bool],
    description: str,
    timeout: float = RECONCILE_TIMEOUT_SECONDS,
) -> Any:
    apps = kubeclient.AppsV1Api(vcluster["api"])
    deadline = time.time() + timeout
    last_seen: str = "(no matching Deployments)"
    while time.time() < deadline:
        resp = await apps.list_namespaced_deployment(
            namespace=namespace, label_selector=label_selector
        )
        deployments = list(resp.items)
        for dep in deployments:
            try:
                if predicate(dep):
                    return dep
            except Exception:
                continue
        if deployments:
            last_seen = f"{len(deployments)} deployment(s) did not satisfy predicate"
        await asyncio.sleep(RECONCILE_POLL_INTERVAL)
    raise TimeoutError(
        f"Timed out waiting for {description} in namespace {namespace} "
        f"(selector={label_selector!r}): {last_seen}"
    )


def _container_zero_envs(dep: Any) -> list[dict[str, str]]:
    """Return the ``env`` entries on ``container[0]`` only (per the
    post-008 narrowing — env var injection lands on the first container).
    """
    containers = dep.spec.template.spec.containers or []
    if not containers:
        return []
    container = containers[0]
    return [
        {
            "name": entry.name,
            "value": entry.value if entry.value is not None else "",
        }
        for entry in container.env or []
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def env_update_environment(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> AsyncGenerator[dict, None]:
    """Empty environment that the US1 fanout test owns end-to-end."""
    driver, client = session_scenario_driver
    cluster_id = styrmin_resources["cluster_id"]
    env = await driver.create_environment(
        name=f"env-update-e2e-{uuid.uuid4().hex[:8]}",
        cluster_id=cluster_id,
        config={},
    )
    yield {
        "environment_id": str(env.id),
        "client": client,
    }


@pytest.fixture(scope="module")
async def env_update_three_deployments(
    env_update_environment: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    simple_app_image: str,  # noqa: ARG001 — builds the image
    vcluster: dict,
) -> list[dict]:
    """Three peer ``simple-app`` deployments parked in RUNNING — the
    fanout target set for the US1 headline scenario.
    """
    driver, _ = session_scenario_driver
    deployments: list[dict] = []
    for suffix in ("a", "b", "c"):
        deployment = await driver.create_deployment(
            driver="simple-app",
            version="0.1.0",
            environment_id=env_update_environment["environment_id"],
            name=f"env-update-{suffix}",
        )
        deployment = await driver.wait_for_deployment_running(
            deployment_id=deployment.id
        )
        deployments.append(
            {
                "deployment_id": str(deployment.id),
                "namespace": f"styrmin-{deployment.id}",
                "kubeconfig_path": vcluster["kubeconfig_path"],
            }
        )
    return deployments


@pytest.fixture
def _env_update_driver_bound(
    env_update_environment: dict,
    env_update_three_deployments: list[dict],  # noqa: ARG001 — force ordering
    scenario_driver: ScenarioDriver,
) -> None:
    scenario_driver.attach_to_deployment(
        environment_id=env_update_environment["environment_id"]
    )


# ---------------------------------------------------------------------------
# T025 — US1 headline (Quickstart Steps 1-3)
# ---------------------------------------------------------------------------


@pytest.mark.api_only(
    reason=(
        "API/SDK-only flow (Quickstart Steps 1-3); no UI page navigation. "
        "The [ui-chromium] variant would just re-run the same SDK calls. "
        "The env-config fanout is exercised through the typed environment "
        "GraphQL surface and asserted on rendered pod env entries."
    )
)
@pytest.mark.ci
async def test_us1_environment_update_fans_out_to_all_deployments(
    env_update_environment: dict,
    env_update_three_deployments: list[dict],
    vcluster: dict,
    scenario_driver: ScenarioDriver,
    _env_update_driver_bound: None,
) -> None:
    """Quickstart Steps 1-3: ``updateEnvironment`` with a single env var
    propagates to every active deployment in the environment.

    * Set ``OTEL_EXPORTER_OTLP_ENDPOINT`` at the environment scope.
    * Wait for each deployment to reconcile within
      ``RECONCILE_TIMEOUT_SECONDS``.
    * Assert every deployment's ``container[0]`` carries the new env entry.
    * Assert each deployment's timeline received a fresh entry whose
      ``contextDiff`` records the env-config change (FR-023).
    """
    client: StyrminClient = env_update_environment["client"]
    environment_id = env_update_environment["environment_id"]
    target_value = "https://otel.staging"

    # Snapshot timeline length per deployment BEFORE the fanout — so we
    # can assert "exactly one new entry" instead of just "non-empty".
    pre_timeline_lengths: dict[str, int] = {}
    for dep in env_update_three_deployments:
        timeline = await client.deployments.timeline(deployment_id=dep["deployment_id"])
        pre_timeline_lengths[dep["deployment_id"]] = len(timeline)

    await client.environments.update(
        environment_id=environment_id,
        input=UpdateEnvironmentInput(
            env_vars=[
                EnvVarInput(
                    name="OTEL_EXPORTER_OTLP_ENDPOINT",
                    value=target_value,
                )
            ],
        ),
    )

    # Each deployment must reconcile to RUNNING with the new env entry on
    # container[0] of its rendered pod template.
    for dep in env_update_three_deployments:
        await scenario_driver.wait_for_deployment_running(
            deployment_id=dep["deployment_id"], timeout=RECONCILE_TIMEOUT_SECONDS
        )
        rendered = await _wait_for_pod_template(
            vcluster,
            namespace=dep["namespace"],
            label_selector="app.kubernetes.io/name=simple-app",
            predicate=lambda d: any(
                entry.name == "OTEL_EXPORTER_OTLP_ENDPOINT"
                and entry.value == target_value
                for container in (d.spec.template.spec.containers or [])[:1]
                for entry in container.env or []
            ),
            description=(
                f"OTEL_EXPORTER_OTLP_ENDPOINT to land on container[0] of "
                f"deployment {dep['deployment_id']}"
            ),
        )
        envs = _container_zero_envs(rendered)
        assert {
            "name": "OTEL_EXPORTER_OTLP_ENDPOINT",
            "value": target_value,
        } in envs, (
            f"deployment {dep['deployment_id']} did not pick up the env "
            f"var on container[0] — saw {envs}"
        )

    # Each deployment's timeline gained at least one new entry whose
    # ``contextDiff`` mentions the env-config change. We don't lock the
    # exact count to "+1" because the reconciliation loop may produce
    # follow-up entries (status-only) — what we DO lock is that a fresh
    # entry exists with the new env var in its diff.
    for dep in env_update_three_deployments:
        timeline_after = await client.deployments.timeline(
            deployment_id=dep["deployment_id"]
        )
        assert len(timeline_after) > pre_timeline_lengths[dep["deployment_id"]], (
            f"deployment {dep['deployment_id']} timeline did not grow after "
            "the env-config fanout"
        )
        # At least one new entry must record the env-config change in
        # its context diff — the additions must reference the env var
        # name we set.
        new_entries = timeline_after[pre_timeline_lengths[dep["deployment_id"]] :]
        env_var_in_diff = False
        for entry in new_entries:
            ctx_diff = getattr(entry, "context_diff", None)
            if ctx_diff is None:
                continue
            changes = getattr(ctx_diff, "changes", None) or []
            for change in changes:
                path = getattr(change, "path", "") or ""
                new_value = getattr(change, "new_value", None)
                if "OTEL_EXPORTER_OTLP_ENDPOINT" in path or (
                    isinstance(new_value, str) and target_value in new_value
                ):
                    env_var_in_diff = True
                    break
            if env_var_in_diff:
                break
        assert env_var_in_diff, (
            f"deployment {dep['deployment_id']} timeline grew but no new "
            "entry carries the env-config change in its contextDiff"
        )


# ---------------------------------------------------------------------------
# T026 — US1 failure isolation (Quickstart Step 7)
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "Needs a multi-driver fixture or a chart-render-failure path: the "
        "test asserts that an env-config update with a scheduling override "
        "fails on deployment B (chart can't render) while deployment A "
        "converges, and that A/B/the env-config row are properly isolated. "
        "Body fully written so unskipping is a one-line change once the "
        "fixture lands. Tracking issue: see tasks T026 in "
        "specs/009-environment-update/tasks.md."
    )
)
@pytest.mark.api_only(
    reason=(
        "API/SDK-only flow (Quickstart Step 7); no UI page navigation. "
        "The [ui-chromium] variant would just re-run the same SDK calls."
    )
)
@pytest.mark.ci
async def test_us1_environment_update_failure_isolation(
    env_update_environment: dict,
    env_update_three_deployments: list[dict],
    vcluster: dict,
    scenario_driver: ScenarioDriver,
    _env_update_driver_bound: None,
) -> None:
    """Quickstart Step 7: env-config fanout failure isolation.

    Setup: an environment with two deployments A and B. Submit
    ``updateEnvironment`` with a scheduling override that B's chart
    cannot render plus an env var that A's chart can.

    Assertions:
    * The env-config row on the environment persists with the submitted
      values (FR-009a — committed before fanout).
    * Deployment A reconciles to RUNNING with the new env var on its
      ``container[0]`` (peer-isolation invariant).
    * Deployment B's timeline records a failed Task — the failure must
      not propagate to peer A or roll back the env-config row.
    """
    client: StyrminClient = env_update_environment["client"]
    environment_id = env_update_environment["environment_id"]
    deployment_a = env_update_three_deployments[0]
    deployment_b = env_update_three_deployments[1]

    # A scheduling override that A accepts and B's chart rejects on
    # render — the exact value depends on the multi-driver fixture; the
    # placeholder below is the shape the test will use once the fixture
    # exists.
    bad_override = SchedulingInput(runtime_class="nonexistent")
    typed_input = UpdateEnvironmentInput(
        env_vars=[
            EnvVarInput(
                name="OTEL_EXPORTER_OTLP_ENDPOINT",
                value="https://otel.staging",
            )
        ],
        scheduling=bad_override,
    )

    await client.environments.update(
        environment_id=environment_id,
        input=typed_input,
    )

    # The env-config row persists despite the per-deployment failure.
    fresh_env = await client.environments.get(environment_id=environment_id)
    assert fresh_env.config == {
        "env_vars": {"OTEL_EXPORTER_OTLP_ENDPOINT": "https://otel.staging"},
        "scheduling": {"runtime_class": "nonexistent"},
    }

    # A converges with the new env var.
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_a["deployment_id"],
        timeout=RECONCILE_TIMEOUT_SECONDS,
    )
    rendered_a = await _wait_for_pod_template(
        vcluster,
        namespace=deployment_a["namespace"],
        label_selector="app.kubernetes.io/name=simple-app",
        predicate=lambda d: any(
            entry.name == "OTEL_EXPORTER_OTLP_ENDPOINT"
            for container in (d.spec.template.spec.containers or [])[:1]
            for entry in container.env or []
        ),
        description="deployment A to converge with new env var (peer isolation)",
    )
    envs_a = _container_zero_envs(rendered_a)
    assert {
        "name": "OTEL_EXPORTER_OTLP_ENDPOINT",
        "value": "https://otel.staging",
    } in envs_a

    # B's timeline records a failed Task.
    timeline_b = await client.deployments.timeline(
        deployment_id=deployment_b["deployment_id"]
    )
    failed_tasks = [
        entry
        for entry in timeline_b
        if getattr(entry.task, "status", "").upper() == "FAILED"
    ]
    assert failed_tasks, (
        "deployment B should have logged a failed Task in its timeline; "
        "found no FAILED entries"
    )


# ---------------------------------------------------------------------------
# T047 — typed-input rejection scenario (Quickstart Step 6)
# ---------------------------------------------------------------------------


@pytest.mark.api_only(
    reason=(
        "API/SDK-only flow (Quickstart Step 6); the rejection happens at "
        "the GraphQL boundary before any cluster interaction. The "
        "[ui-chromium] variant would just re-run the same SDK call."
    )
)
@pytest.mark.ci
async def test_us2_environment_update_invalid_env_var_name_rejected(
    env_update_environment: dict,
) -> None:
    """Quickstart Step 6: an ``updateEnvironment`` with an invalid env var
    name (regex violation) is rejected with
    ``extensions.code = "INVALID_ENV_VAR_NAME"`` (FR-006 / SC-003).

    The regenerated SDK surfaces the error as
    :class:`styrmin_sdk.exceptions.OperationFailedError` whose
    ``typename`` carries the GraphQL extensions code; we assert directly
    on that to keep the contract pinned.
    """
    from styrmin_sdk.exceptions import OperationFailedError

    client: StyrminClient = env_update_environment["client"]
    environment_id = env_update_environment["environment_id"]

    with pytest.raises(OperationFailedError) as exc_info:
        await client.environments.update(
            environment_id=environment_id,
            input=UpdateEnvironmentInput(
                env_vars=[EnvVarInput(name="1invalid", value="y")],
            ),
        )
    assert exc_info.value.typename == "INVALID_ENV_VAR_NAME"
