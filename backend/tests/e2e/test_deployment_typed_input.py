"""End-to-end coverage for the typed ``UpdateDeploymentInput`` surface (011 / T032).

Exercises the new typed input shape end-to-end:

1. Provision a deployment running ``simple-app``.
2. Submit a single ``updateDeployment`` mutation that sets BOTH a
   per-component env var (``components.server.envVars``) AND a
   scheduling sub-tree (``scheduling.resources.requests.cpu``), via the
   typed SDK call ``client.deployments.update(deployment_id, input=...)``.
3. Wait one reconcile cycle.
4. Assert the ``server`` workload's rendered pod template carries both:
   * the per-component env entry on its container's ``env:`` block, and
   * the container's CPU request equal to the submitted value.
5. Submit a follow-up mutation with an invalid env-var name
   (``1invalid``) in the per-component block; assert the response
   carries ``extensions.code = "INVALID_ENV_VAR_NAME"`` with the
   offending name in the payload.

Marked ``@pytest.mark.api_only`` per AGENTS.md dual-entrypoint rule:
the SDK call path is the only thing under test — the UI's scheduling
dialog edits the same wire, but the per-component env-vars editor does
not exist in the UI yet, so a ``[ui-chromium]`` variant would either
re-run the same SDK call (no extra coverage) or fail on the missing UI
surface. See research.md §7 for the rationale.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, AsyncGenerator, Callable

import pytest
from kubernetes_asyncio import client as kubeclient
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import StyrminAPIError
from styrmin_sdk.graphql._generated.input_types import (
    ComponentConfigInput,
    EnvVarInput,
    ResourceRequirementsInput,
    ResourceSpecInput,
    SchedulingInput,
    UpdateDeploymentInput,
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
    """Poll workloads in ``namespace`` matching ``label_selector`` until one
    satisfies ``predicate``. Scans Deployments, StatefulSets, and
    DaemonSets so the simple-app's StatefulSet-backed postgres
    component is reachable too.
    """
    apps = kubeclient.AppsV1Api(vcluster["api"])
    deadline = time.time() + timeout
    last_seen: str = "(no matching workloads)"
    while time.time() < deadline:
        deployments = (
            await apps.list_namespaced_deployment(
                namespace=namespace, label_selector=label_selector
            )
        ).items
        statefulsets = (
            await apps.list_namespaced_stateful_set(
                namespace=namespace, label_selector=label_selector
            )
        ).items
        daemonsets = (
            await apps.list_namespaced_daemon_set(
                namespace=namespace, label_selector=label_selector
            )
        ).items
        workloads = list(deployments) + list(statefulsets) + list(daemonsets)
        for workload in workloads:
            try:
                if predicate(workload):
                    return workload
            except Exception:
                continue
        if workloads:
            last_seen = f"{len(workloads)} workload(s) did not satisfy predicate"
        await asyncio.sleep(RECONCILE_POLL_INTERVAL)
    raise TimeoutError(
        f"Timed out waiting for {description} in namespace {namespace} "
        f"(selector={label_selector!r}): {last_seen}"
    )


def _container_envs(dep: Any) -> list[dict[str, str]]:
    """Flatten ``env`` entries across every container on the rendered pod
    template, normalised to plain ``{name, value}`` dicts.
    """
    envs: list[dict[str, str]] = []
    for container in dep.spec.template.spec.containers or []:
        for entry in container.env or []:
            envs.append(
                {
                    "name": entry.name,
                    "value": entry.value if entry.value is not None else "",
                }
            )
    return envs


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def typed_input_environment(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> AsyncGenerator[dict, None]:
    """Dedicated environment for the typed-input E2E.

    No env-level scheduling config so the deployment-level submission
    drives the resulting pod template by itself.
    """
    driver, client = session_scenario_driver
    cluster_id = styrmin_resources["cluster_id"]
    env = await driver.create_environment(
        name=f"typed-input-e2e-{uuid.uuid4().hex[:8]}",
        cluster_id=cluster_id,
        config={},
    )
    yield {
        "environment_id": str(env.id),
        "client": client,
    }


@pytest.fixture(scope="module")
async def typed_input_deployment(
    typed_input_environment: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    simple_app_image: str,  # noqa: ARG001 — builds the image
    vcluster: dict,
) -> dict:
    """Fresh simple-app deployment dedicated to the typed-input test."""
    driver, _ = session_scenario_driver
    deployment = await driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=typed_input_environment["environment_id"],
        name="typed-input",
    )
    deployment = await driver.wait_for_deployment_running(deployment_id=deployment.id)
    return {
        "deployment_id": str(deployment.id),
        "namespace": f"styrmin-{deployment.id}",
        "kubeconfig_path": vcluster["kubeconfig_path"],
    }


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.api_only(
    reason=(
        "SDK-driven; no UI flow exercised — the [ui-chromium] variant "
        "would just re-run the same SDK call."
    )
)
@pytest.mark.ci
async def test_update_deployment_typed_input_propagates_component_env_var_and_scheduling(
    typed_input_environment: dict,
    typed_input_deployment: dict,
    vcluster: dict,
) -> None:
    """End-to-end T032: per ``research.md`` §7.

    Drives the SDK ``client.deployments.update`` with a typed
    :class:`UpdateDeploymentInput` carrying a per-component env var on
    ``server`` AND a ``scheduling.resources.requests.cpu`` constraint
    in a single mutation. Waits for reconciliation, then asserts both
    landed on the rendered pod template. Finally submits an invalid
    env-var name in the same per-component block and asserts the typed
    ``INVALID_ENV_VAR_NAME`` code reaches the SDK caller.
    """
    client: StyrminClient = typed_input_environment["client"]
    deployment_id = typed_input_deployment["deployment_id"]
    namespace = typed_input_deployment["namespace"]

    # ------------------------------------------------------------------
    # Happy path: per-component env var + scheduling in one mutation
    # ------------------------------------------------------------------
    happy_input = UpdateDeploymentInput(
        components=[
            ComponentConfigInput(
                name="server",
                envVars=[EnvVarInput(name="OTEL", value="https://otel.staging")],
            )
        ],
        scheduling=SchedulingInput(
            resources=ResourceRequirementsInput(
                requests=ResourceSpecInput(cpu="200m"),
            ),
        ),
    )
    await client.deployments.update(deployment_id, input=happy_input)

    # Wait for the workflow to reach RUNNING again before polling k8s.
    deadline = time.time() + RECONCILE_TIMEOUT_SECONDS
    while time.time() < deadline:
        dep = await client.deployments.get(deployment_id)
        if getattr(dep, "status", None) == "running":
            break
        await asyncio.sleep(3.0)
    else:
        raise TimeoutError(
            f"deployment {deployment_id} did not reach 'running' within "
            f"{RECONCILE_TIMEOUT_SECONDS}s after typed update"
        )

    # The ``server`` workload must carry OTEL=https://otel.staging on its
    # container's ``env:`` block AND have a CPU request of 200m.
    def _both_features_landed(workload: Any) -> bool:
        containers = workload.spec.template.spec.containers or []
        has_env = any(
            entry.name == "OTEL" and entry.value == "https://otel.staging"
            for container in containers
            for entry in container.env or []
        )
        # CPU request resolves to the operator-set value on the first
        # container of the workload (the chart renders the operator-set
        # request via the resources post-renderer).
        first = containers[0] if containers else None
        requests = (
            first.resources.requests
            if first is not None and first.resources is not None
            else None
        )
        has_cpu = bool(requests) and requests.get("cpu") == "200m"
        return has_env and has_cpu

    workload = await _wait_for_pod_template(
        vcluster,
        namespace=namespace,
        label_selector="app.kubernetes.io/name=simple-app",
        predicate=_both_features_landed,
        description=(
            "server workload to carry OTEL=https://otel.staging and "
            "container CPU request of 200m via typed input"
        ),
    )
    envs = _container_envs(workload)
    assert {"name": "OTEL", "value": "https://otel.staging"} in envs

    # ------------------------------------------------------------------
    # Negative path: invalid env-var name surfaces the typed code
    # ------------------------------------------------------------------
    bad_input = UpdateDeploymentInput(
        components=[
            ComponentConfigInput(
                name="server",
                envVars=[EnvVarInput(name="1invalid", value="x")],
            )
        ],
    )
    raised = False
    try:
        await client.deployments.update(deployment_id, input=bad_input)
    except StyrminAPIError as exc:
        raised = True
        assert exc.typename == "INVALID_ENV_VAR_NAME", (
            f"expected typename INVALID_ENV_VAR_NAME, got {exc.typename!r} "
            f"(message={str(exc)!r})"
        )
        assert "1invalid" in str(exc), (
            f"expected offending name '1invalid' in message, got {str(exc)!r}"
        )
    assert raised, (
        "submitting an invalid env var name must surface a typed error; "
        "the SDK silently accepted the bad input instead"
    )
