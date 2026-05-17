"""E2E coverage for editing Service Overrides through the unified
configuration drawer (011 / US2, T054).

Adds a service-name override mapping ``simple-app`` → ``my-svc`` via the
drawer, applies the change, and asserts the renamed Service object
appears in the deployment namespace.

Note: ``simple-app`` is the driver-declared service name for the
simple-app driver (``services[0].name`` in ``driver.styrmin.yml``).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, AsyncGenerator

import kr8s
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Service as AsyncService
from playwright.async_api import expect
from styrmin_sdk import StyrminClient

from tests.e2e.drivers import ScenarioDriver
from tests.e2e.pages.deployment_detail import DeploymentDetailPage

if TYPE_CHECKING:
    from playwright.async_api import Page

RECONCILE_TIMEOUT_SECONDS = 480.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def svc_overrides_edit_environment(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> AsyncGenerator[dict, None]:
    driver, client = session_scenario_driver
    cluster_id = styrmin_resources["cluster_id"]
    env = await driver.create_environment(
        name=f"drawer-svc-{uuid.uuid4().hex[:8]}",
        cluster_id=cluster_id,
        config={},
    )
    yield {"environment_id": str(env.id), "client": client}


@pytest.fixture(scope="module")
async def svc_overrides_edit_deployment(
    svc_overrides_edit_environment: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    simple_app_image: str,  # noqa: ARG001 — builds the image
    vcluster: dict,
) -> dict:
    driver, _ = session_scenario_driver
    deployment = await driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=svc_overrides_edit_environment["environment_id"],
        name="drawer-svc",
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


async def _wait_for_service_named(
    *, namespace: str, expected_name: str, kubeconfig_path: str, timeout: float
) -> AsyncService:
    """Poll until a Kubernetes Service named ``expected_name`` appears in
    ``namespace``. Returns the matching object.

    The override rename causes the chart to render a Service with the new
    name; the renaming is observable here as the new Service resource
    becoming visible.
    """
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    deadline = time.time() + timeout
    seen: list[str] = []
    while time.time() < deadline:
        services: list[AsyncService] = [
            svc
            async for svc in AsyncService.list(namespace=namespace, api=kr8s_api)
            if isinstance(svc, AsyncService)
        ]
        seen = [svc.name for svc in services]
        for svc in services:
            if svc.name == expected_name:
                return svc
        await asyncio.sleep(3.0)
    raise AssertionError(
        f"Service {expected_name!r} did not appear in namespace {namespace} "
        f"within {timeout}s; last seen={seen!r}"
    )


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.ci
@pytest.mark.ui_only(
    reason=(
        "Drives the unified drawer's Service Overrides section. The "
        "underlying mutation is exercised by the API-side service-"
        "discovery test; we add the UI-side coverage here."
    ),
)
async def test_drawer_service_overrides_edit(
    svc_overrides_edit_environment: dict,
    svc_overrides_edit_deployment: dict,
    session_ui_page: "Page",
) -> None:
    page = session_ui_page
    environment_id = svc_overrides_edit_environment["environment_id"]
    deployment_id = svc_overrides_edit_deployment["deployment_id"]
    namespace = svc_overrides_edit_deployment["namespace"]
    kubeconfig_path = svc_overrides_edit_deployment["kubeconfig_path"]

    driver_service_name = "simple-app"  # declared by simple-app's driver manifest
    override_name = f"my-svc-{uuid.uuid4().hex[:6]}"

    detail = DeploymentDetailPage(page)
    await detail.goto(environment_id=environment_id, deployment_id=deployment_id)
    await detail.wait_for_status(expected="running", timeout=180.0)

    await page.get_by_role("button", name="Settings", exact=True).click()
    await expect(page.locator("[data-testid=settings-tab]")).to_be_visible()
    await page.locator("[data-testid=settings-update-button]").click()
    drawer = page.locator("[role=dialog][aria-labelledby=config-edit-drawer-title]")
    await expect(drawer).to_be_visible()

    await page.locator("[data-testid=section-nav-serviceOverrides]").click()

    await page.locator("[data-testid=add-service-override]").click()
    driver_input = page.locator("[data-testid=svc-driver-0]")
    override_input = page.locator("[data-testid=svc-override-0]")
    await expect(driver_input).to_be_visible()
    await driver_input.fill(driver_service_name)
    await override_input.fill(override_name)
    await override_input.press("Tab")

    review_button = page.locator("[data-testid=drawer-review-apply-button]")
    await expect(review_button).to_be_enabled()
    await review_button.click()

    diff_dialog = page.locator("[data-testid=config-diff-dialog]")
    await expect(diff_dialog).to_be_visible()

    # Diff rows render the human-readable ``label`` — the override entry
    # appears as ``Service "<name>" override``.
    svc_section = diff_dialog.locator("[data-testid=diff-section-serviceOverrides]")
    await expect(svc_section).to_be_visible()
    await expect(svc_section).to_contain_text(f'Service "{driver_service_name}"')

    await page.locator("[data-testid=diff-dialog-apply-button]").click()
    await expect(diff_dialog).to_be_hidden(timeout=60_000)

    await _wait_for_service_named(
        namespace=namespace,
        expected_name=override_name,
        kubeconfig_path=kubeconfig_path,
        timeout=RECONCILE_TIMEOUT_SECONDS,
    )
