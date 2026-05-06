"""End-to-end coverage for deployment environment variables (008 / US1+).

Drives the full user-facing path: ``updateDeployment(config: { env_vars: ... })``
(SDK / GraphQL) → server reconciler → FluxCD HelmRelease post-renderers →
rendered pod spec on the vcluster. Asserts by reading the resulting
``apps/v1.Deployment`` back from the vcluster API server and inspecting
the container ``env`` block.

US1 scenario corresponds to Quickstart Step 1: deploy ``simple-app``, set
``LOG_LEVEL=debug`` on the deployment, observe the env entry on every
container's ``env:`` list. The flow is API/SDK-only (no UI page navigation),
hence the ``api_only`` marker per AGENTS.md "Dual-entrypoint scope".
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, AsyncGenerator, Callable

import pytest
from kubernetes_asyncio import client as kubeclient
from styrmin_sdk import StyrminClient

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


def _container_envs(dep: Any) -> list[dict[str, str]]:
    """Return the flattened list of ``env`` entries across every container in
    the rendered pod template, normalised to plain ``{name, value}`` dicts.
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
async def env_vars_environment(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> AsyncGenerator[dict, None]:
    driver, client = session_scenario_driver
    cluster_id = styrmin_resources["cluster_id"]
    env = await driver.create_environment(
        name=f"env-vars-e2e-{uuid.uuid4().hex[:8]}",
        cluster_id=cluster_id,
        config={},
    )
    yield {
        "environment_id": str(env.id),
        "client": client,
    }


@pytest.fixture(scope="module")
async def env_vars_deployment(
    env_vars_environment: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    simple_app_image: str,  # noqa: ARG001 — builds the image
    vcluster: dict,
) -> dict:
    driver, _ = session_scenario_driver
    deployment = await driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=env_vars_environment["environment_id"],
        name="env-vars-a",
    )
    deployment = await driver.wait_for_deployment_running(deployment_id=deployment.id)
    return {
        "deployment_id": str(deployment.id),
        "namespace": f"styrmin-{deployment.id}",
        "kubeconfig_path": vcluster["kubeconfig_path"],
    }


@pytest.fixture
def _env_vars_driver_bound(
    env_vars_environment: dict,
    env_vars_deployment: dict,  # noqa: ARG001 — force fixture ordering
    scenario_driver: ScenarioDriver,
) -> None:
    scenario_driver.attach_to_deployment(
        environment_id=env_vars_environment["environment_id"]
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.api_only(
    reason=(
        "API/SDK-only flow (Quickstart Step 1); no UI page navigation. "
        "The [ui-chromium] variant would just re-run the same SDK call."
    )
)
@pytest.mark.ci
async def test_us1_deployment_level_env_var(
    env_vars_environment: dict,
    env_vars_deployment: dict,
    vcluster: dict,
    scenario_driver: ScenarioDriver,
    _env_vars_driver_bound: None,
) -> None:
    """Quickstart Step 1: set ``LOG_LEVEL=debug`` at deployment scope and
    assert the entry reaches every container's ``env:`` block.
    """
    deployment_id = env_vars_deployment["deployment_id"]
    namespace = env_vars_deployment["namespace"]

    await scenario_driver.update_deployment(
        deployment_id=deployment_id,
        config={"env_vars": {"LOG_LEVEL": "debug"}},
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )

    dep = await _wait_for_pod_template(
        vcluster,
        namespace=namespace,
        label_selector="app.kubernetes.io/name=simple-app",
        predicate=lambda d: any(
            entry.name == "LOG_LEVEL" and entry.value == "debug"
            for container in d.spec.template.spec.containers or []
            for entry in container.env or []
        ),
        description="LOG_LEVEL=debug to land on every container",
    )

    envs = _container_envs(dep)
    assert {"name": "LOG_LEVEL", "value": "debug"} in envs

    # Every container in the pod template should have received the entry
    # (FR-026 strategic-merge wildcard injection).
    for container in dep.spec.template.spec.containers or []:
        names = {entry.name for entry in container.env or []}
        assert "LOG_LEVEL" in names, (
            f"container {container.name!r} missing LOG_LEVEL env entry"
        )
