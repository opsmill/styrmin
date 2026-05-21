"""E2E coverage for editing Component Overrides through the unified
configuration drawer (011 / US4, T069).

Verifies the targeted-component invariant: an override applied to one
component lands on that component's workload only and does NOT touch the
other components of the same deployment.

Chunk-6 scope note
------------------
The chunk script asks for a "CPU resource override" on one of three
components. The backend's typed ``ComponentConfigInput`` today only
carries ``name`` + ``envVars`` — per-component CPU/memory/replicas are
the structural "room to grow" placeholders that ship with the section
(see ``ComponentOverridesSection.tsx`` and FR-013/SC-007). Until that
GraphQL surface widens, the only per-component knob that round-trips end
-to-end is env-vars, and that's what this test exercises. The targeted-
component invariant — *only the component we edited changes* — is
identical regardless of which per-component scope we drive, so the test
remains a faithful gate on US4's acceptance scenario.

simple-app declares two components (``server``, ``database``); we set a
per-component env-var on ``server`` and assert the StatefulSet/Deployment
backing ``database`` still has zero ``env`` entries in its container
spec (i.e. unchanged).
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
async def component_overrides_edit_environment(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> AsyncGenerator[dict, None]:
    driver, client = session_scenario_driver
    cluster_id = styrmin_resources["cluster_id"]
    env = await driver.create_environment(
        name=f"drawer-comp-{uuid.uuid4().hex[:8]}",
        cluster_id=cluster_id,
        config={},
    )
    yield {"environment_id": str(env.id), "client": client}


@pytest.fixture(scope="module")
async def component_overrides_edit_deployment(
    component_overrides_edit_environment: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    simple_app_image: str,  # noqa: ARG001 — builds the image
    vcluster: dict,
) -> dict:
    driver, _ = session_scenario_driver
    deployment = await driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=component_overrides_edit_environment["environment_id"],
        name="drawer-comp",
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


async def _wait_for_workload_env(
    vcluster: dict,
    *,
    namespace: str,
    label_selector: str,
    predicate: Callable[[Any], bool],
    timeout: float,
) -> Any:
    """Poll workloads (Deployment or StatefulSet) matching ``label_selector``
    until ``predicate(workload)`` returns truthy.
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


def _container_env_names(workload: Any) -> set[str]:
    names: set[str] = set()
    for container in workload.spec.template.spec.containers or []:
        for entry in container.env or []:
            names.add(entry.name)
    return names


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.ci
@pytest.mark.ui_only(
    reason=(
        "Drives the unified drawer's Component Overrides section through "
        "the UI. The collapsible per-component blocks, the change pill, "
        "and the per-component diff entry are UI-only affordances; the "
        "API-side mutation is exercised by existing per-component env-"
        "var tests."
    ),
)
async def test_drawer_component_overrides_edit(
    component_overrides_edit_environment: dict,
    component_overrides_edit_deployment: dict,
    session_ui_page: "Page",
    vcluster: dict,
) -> None:
    page = session_ui_page
    environment_id = component_overrides_edit_environment["environment_id"]
    deployment_id = component_overrides_edit_deployment["deployment_id"]
    namespace = component_overrides_edit_deployment["namespace"]

    target_component = "server"
    untouched_component = "database"
    env_var_name = f"COMP_E2E_FLAG_{uuid.uuid4().hex[:6].upper()}"
    env_var_value = "true"

    detail = DeploymentDetailPage(page)
    await detail.goto(environment_id=environment_id, deployment_id=deployment_id)
    await detail.wait_for_status(expected="running", timeout=180.0)

    # Capture the "before" env-var name set on the untouched component so we
    # can assert it stays identical after the drawer apply round-trip.
    before_untouched_env = _container_env_names(
        await _wait_for_workload_env(
            vcluster,
            namespace=namespace,
            label_selector="app.kubernetes.io/name=postgresql",
            predicate=lambda _: True,
            timeout=RECONCILE_TIMEOUT_SECONDS,
        )
    )

    await page.get_by_role("button", name="Settings", exact=True).click()
    await expect(page.locator("[data-testid=settings-tab]")).to_be_visible()
    await page.locator("[data-testid=settings-update-button]").click()
    drawer = page.locator("[role=dialog][aria-labelledby=config-edit-drawer-title]")
    await expect(drawer).to_be_visible()

    # Jump to the Component Overrides section via the nav rail.
    await page.locator("[data-testid=section-nav-componentOverrides]").click()

    # Both components should be rendered as collapsible blocks.
    target_trigger = page.locator(
        f"[data-testid=component-override-trigger-{target_component}]"
    )
    untouched_trigger = page.locator(
        f"[data-testid=component-override-trigger-{untouched_component}]"
    )
    await expect(target_trigger).to_be_visible()
    await expect(untouched_trigger).to_be_visible()

    # Expand the targeted component and add an override block + env var.
    await target_trigger.click()
    await page.locator(
        f"[data-testid=component-override-add-{target_component}]"
    ).click()
    await page.locator(f"[data-testid=comp-env-add-{target_component}]").click()
    await page.locator(f"[data-testid=comp-env-name-{target_component}-0]").fill(
        env_var_name
    )
    value_input = page.locator(f"[data-testid=comp-env-value-{target_component}-0]")
    await value_input.fill(env_var_value)
    await value_input.press("Tab")

    # The "override" pill should now appear on the target component header.
    await expect(
        page.locator(f"[data-testid=component-override-pill-{target_component}]")
    ).to_be_visible()

    # The untouched component must NOT have an override pill yet.
    await expect(
        page.locator(f"[data-testid=component-override-pill-{untouched_component}]")
    ).to_have_count(0)

    review_button = page.locator("[data-testid=drawer-review-apply-button]")
    await expect(review_button).to_be_enabled()
    await review_button.click()

    diff_dialog = page.locator("[data-testid=config-diff-dialog]")
    await expect(diff_dialog).to_be_visible()

    # The diff entry is attributed to the componentOverrides section and
    # mentions the targeted component name in its row label.
    comp_section = diff_dialog.locator("[data-testid=diff-section-componentOverrides]")
    await expect(comp_section).to_be_visible()
    await expect(comp_section).to_contain_text(target_component)

    await page.locator("[data-testid=diff-dialog-apply-button]").click()
    await expect(diff_dialog).to_be_hidden(timeout=60_000)

    # Assert: targeted component's workload picks up the env var.
    def _server_has_new_env(workload: Any) -> bool:
        for container in workload.spec.template.spec.containers or []:
            for entry in container.env or []:
                if entry.name == env_var_name and entry.value == env_var_value:
                    return True
        return False

    await _wait_for_workload_env(
        vcluster,
        namespace=namespace,
        label_selector="app.kubernetes.io/name=simple-app",
        predicate=_server_has_new_env,
        timeout=RECONCILE_TIMEOUT_SECONDS,
    )

    # Assert: untouched component's env-var set is identical to its "before"
    # snapshot — no spillover from the targeted override.
    after_untouched = await _wait_for_workload_env(
        vcluster,
        namespace=namespace,
        label_selector="app.kubernetes.io/name=postgresql",
        predicate=lambda _: True,
        timeout=RECONCILE_TIMEOUT_SECONDS,
    )
    after_untouched_env = _container_env_names(after_untouched)
    assert after_untouched_env == before_untouched_env, (
        f"Untouched component {untouched_component!r} env var set changed: "
        f"before={sorted(before_untouched_env)!r}, "
        f"after={sorted(after_untouched_env)!r}"
    )
    assert env_var_name not in after_untouched_env, (
        f"Override env var {env_var_name!r} leaked into the untouched "
        f"component {untouched_component!r}"
    )
