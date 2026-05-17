"""E2E coverage for editing Environment Variables through the unified
configuration drawer (011 / US2, T051).

Adds a new deployment-scoped env var via the drawer's Environment
Variables section, applies the change, and asserts the entry surfaces on
the simple-app server container's ``env:`` block after reconciliation.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, Any, AsyncGenerator, Callable

import pytest
from kubernetes_asyncio import client as kubeclient
from playwright.async_api import expect
from styrmin_sdk import StyrminClient

from tests.e2e.drivers import ScenarioDriver
from tests.e2e.pages.deployment_detail import DeploymentDetailPage

if TYPE_CHECKING:
    from playwright.async_api import Page

RECONCILE_TIMEOUT_SECONDS = 480.0
RECONCILE_POLL_INTERVAL = 3.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def env_vars_edit_environment(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> AsyncGenerator[dict, None]:
    driver, client = session_scenario_driver
    cluster_id = styrmin_resources["cluster_id"]
    env = await driver.create_environment(
        name=f"drawer-envvars-{uuid.uuid4().hex[:8]}",
        cluster_id=cluster_id,
        config={},
    )
    yield {"environment_id": str(env.id), "client": client}


@pytest.fixture(scope="module")
async def env_vars_edit_deployment(
    env_vars_edit_environment: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    simple_app_image: str,  # noqa: ARG001 — builds the image
    vcluster: dict,
) -> dict:
    driver, _ = session_scenario_driver
    deployment = await driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=env_vars_edit_environment["environment_id"],
        name="drawer-envvars",
    )
    deployment = await driver.wait_for_deployment_running(
        deployment_id=deployment.id, timeout=RECONCILE_TIMEOUT_SECONDS
    )
    return {
        "deployment_id": str(deployment.id),
        "namespace": f"styrmin-{deployment.id}",
        "kubeconfig_path": vcluster["kubeconfig_path"],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _wait_for_pod_env(
    vcluster: dict,
    *,
    namespace: str,
    label_selector: str,
    predicate: Callable[[Any], bool],
    timeout: float,
) -> Any:
    """Poll the server workload's pod template until ``predicate`` holds.

    Mirrors the helper in ``test_deployment_typed_input.py``; we look at
    both Deployments and StatefulSets so the simple-app's StatefulSet-
    backed components are reachable.
    """
    apps = kubeclient.AppsV1Api(vcluster["api"])
    deadline = time.time() + timeout
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
        for workload in list(deployments) + list(statefulsets):
            try:
                if predicate(workload):
                    return workload
            except Exception:
                continue
        await asyncio.sleep(RECONCILE_POLL_INTERVAL)
    raise AssertionError(
        f"Timed out waiting for pod-template predicate in {namespace} "
        f"(selector={label_selector!r})"
    )


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.ci
@pytest.mark.ui_only(
    reason=(
        "Drives the unified drawer's Env Vars section through the UI. No "
        "SDK equivalent for 'open drawer / Add env var / Apply' — the "
        "API variant would just re-run the existing SDK env-var test."
    ),
)
async def test_drawer_env_vars_edit(
    env_vars_edit_environment: dict,
    env_vars_edit_deployment: dict,
    session_ui_page: "Page",
    vcluster: dict,
) -> None:
    page = session_ui_page
    environment_id = env_vars_edit_environment["environment_id"]
    deployment_id = env_vars_edit_deployment["deployment_id"]
    namespace = env_vars_edit_deployment["namespace"]

    new_env_name = "DRAWER_E2E_FLAG"
    new_env_value = f"on-{uuid.uuid4().hex[:6]}"

    detail = DeploymentDetailPage(page)
    await detail.goto(environment_id=environment_id, deployment_id=deployment_id)
    await detail.wait_for_status(expected="running", timeout=180.0)

    await page.get_by_role("button", name="Configuration", exact=True).click()
    await expect(page.locator("[data-testid=configuration-tab]")).to_be_visible()
    await page.locator("[data-testid=hero-edit-config-button]").click()
    drawer = page.locator("[role=dialog][aria-labelledby=config-edit-drawer-title]")
    await expect(drawer).to_be_visible()

    # Scroll the Env Vars section into view.
    await page.locator("[data-testid=section-nav-envVars]").click()

    # Add a new env-var row. The form starts with no rows for an empty-
    # config deployment, so the new row's index will be 0.
    await page.locator("[data-testid=add-env-var]").click()
    name_input = page.locator("[data-testid=envvar-name-0]")
    value_input = page.locator("[data-testid=envvar-value-0]")
    await expect(name_input).to_be_visible()
    await name_input.fill(new_env_name)
    await value_input.fill(new_env_value)
    await value_input.press("Tab")

    review_button = page.locator("[data-testid=drawer-review-apply-button]")
    await expect(review_button).to_be_enabled()
    await review_button.click()

    diff_dialog = page.locator("[data-testid=config-diff-dialog]")
    await expect(diff_dialog).to_be_visible()

    env_section = diff_dialog.locator("[data-testid=diff-section-envVars]")
    await expect(env_section).to_be_visible()
    await expect(env_section).to_contain_text(new_env_name)

    impact_section = diff_dialog.locator("[data-testid=diff-dialog-impact-section]")
    await expect(impact_section).to_be_visible()
    await expect(impact_section).to_contain_text(
        "Pods will be recreated to pick up new environment"
    )

    await page.locator("[data-testid=diff-dialog-apply-button]").click()
    await expect(diff_dialog).to_be_hidden(timeout=60_000)

    def _has_new_env(workload: Any) -> bool:
        for container in workload.spec.template.spec.containers or []:
            for entry in container.env or []:
                if entry.name == new_env_name and entry.value == new_env_value:
                    return True
        return False

    await _wait_for_pod_env(
        vcluster,
        namespace=namespace,
        label_selector="app.kubernetes.io/name=simple-app",
        predicate=_has_new_env,
        timeout=RECONCILE_TIMEOUT_SECONDS,
    )
