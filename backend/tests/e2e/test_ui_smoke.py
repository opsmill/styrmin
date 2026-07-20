"""UI smoke suite — small, read-mostly UI assertions sharing one deployment.

Each test here was previously its own file (test_deployment_detail_header.py,
test_deploy_form_driver_label.py, test_deployment_pods_tab.py,
test_driver_detail.py). Merging cuts per-test Playwright setup overhead and
keeps the read-only shard tight.

Add new UI-smoke assertions here when they:
- Are purely UI rendering / click-flow assertions (no API equivalent).
- Read the session-shared deployment without mutating it.
- Run in under ~10 seconds.

Heavier UI flows (auth, multi-step forms) keep their own files.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from playwright.async_api import expect

from tests.e2e.pages.deploy_form import DeployFormPage
from tests.e2e.pages.deployment_detail import DeploymentDetailPage
from tests.e2e.pages.pods_tab import PodsTabPage

if TYPE_CHECKING:
    from playwright.async_api import Page

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Header driver text is rendered as "<driver-name> v<version>@<short-hash>"
# per spec 013 (provenance fingerprint). This regex matches the suffix.
DRIVER_VERSION_SUFFIX_RE = re.compile(r"\sv[^\s]+@[0-9a-f]{7}$")

pytestmark = [
    pytest.mark.ci,
    pytest.mark.ui_only(
        reason="UI smoke assertions — rendered DOM only; no SDK equivalent.",
    ),
    pytest.mark.shard_general,
]


# ---- from test_deployment_detail_header.py ----
async def test_deployment_header_shows_driver_name(
    deployed_simple_app: dict,
    session_ui_page: "Page",
    scenario_environment_id: str,
) -> None:
    page = DeploymentDetailPage(session_ui_page)
    await page.goto(
        environment_id=scenario_environment_id,
        deployment_id=deployed_simple_app["deployment_id"],
    )

    # The page exposes the resolved driver name as a data attribute so the
    # check doesn't depend on header layout details.
    driver_name = await page.read_driver_name()
    assert driver_name == "simple-app", (
        f"data-driver-name should be 'simple-app', got {driver_name!r}"
    )

    # And the rendered header value should start with the driver name and
    # include the spec-013 provenance fingerprint suffix
    # ``v<version>@<short-hash>``. The header MUST NOT fall back to a UUID.
    header_text = await page.read_header_driver_text()
    assert header_text.startswith("simple-app"), (
        f"deployment header should start with driver name 'simple-app', "
        f"got {header_text!r}"
    )
    assert not UUID_RE.match(header_text), (
        f"deployment header is rendering a UUID instead of a driver name: {header_text!r}"
    )
    assert DRIVER_VERSION_SUFFIX_RE.search(header_text), (
        f"deployment header should include a 'v<version>@<short-hash>' "
        f"provenance suffix per spec 013, got {header_text!r}"
    )


# ---- from test_deploy_form_driver_label.py ----
async def test_deploy_form_shows_driver_label_after_selection(
    session_ui_page: "Page",
    scenario_environment_id: str,
) -> None:
    driver_name = "simple-app"
    page = DeployFormPage(session_ui_page)
    await page.goto(environment_id=scenario_environment_id)

    # Open and pick the first simple-app version without submitting the form.
    trigger = session_ui_page.locator("[data-testid=driver-version-select]")
    await trigger.click()
    option = (
        session_ui_page.get_by_role("option").filter(has_text=f"{driver_name} v").first
    )
    await option.click()

    label = await page.read_selected_driver_label()

    assert not UUID_RE.match(label), (
        f"driver-version trigger is rendering a UUID instead of a driver name: {label!r}"
    )
    assert label.startswith(driver_name), (
        f"trigger should start with {driver_name!r}, got {label!r}"
    )


# ---- from test_deployment_pods_tab.py ----
async def test_pods_tab_copy_logs_command(
    deployed_simple_app: dict,
    session_ui_page: "Page",
    scenario_environment_id: str,
) -> None:
    deployment_id = deployed_simple_app["deployment_id"]
    namespace = deployed_simple_app["namespace"]

    detail_page = DeploymentDetailPage(session_ui_page)
    pods_tab = PodsTabPage(session_ui_page)

    # 1. Browser clipboard reads require an explicit grant in Chromium. The
    # Copy button still writes without it, but the assertion below cannot
    # read back without permission.
    await pods_tab.grant_clipboard_permissions()

    # 2. Navigate to the deployment detail page and confirm the deployment
    # is RUNNING before switching tabs — saves on flaky waits inside the
    # tab and matches the PRD's preconditions.
    await detail_page.goto(
        environment_id=scenario_environment_id,
        deployment_id=deployment_id,
    )
    await detail_page.wait_for_status(expected="running", timeout=120.0)

    # 3. Open the Pods tab and wait for at least one RUNNING pod row.
    await pods_tab.open()
    pod_name = await pods_tab.wait_for_at_least_one_running_pod(timeout=120.0)

    # 4. Expand the row and open the Commands collapsible.
    await pods_tab.expand_pod(pod_name)
    await pods_tab.open_commands_section()

    # 5. Copy the logs command and verify the exact string lands on the
    # clipboard. The format is owned by buildKubectlCommand; this only
    # checks that the right namespace and pod name are substituted in.
    await pods_tab.click_copy_logs()
    clipboard_text = await pods_tab.read_clipboard()
    expected = f"kubectl logs --namespace {namespace} {pod_name} --all-containers"
    assert clipboard_text == expected, (
        f"clipboard should contain the namespace-and-pod-name-substituted "
        f"logs command. expected={expected!r}, got={clipboard_text!r}"
    )


# ---- from test_driver_detail.py ----
async def test_driver_detail_inspects_versions_via_tabs(
    styrmin_resources: dict,
    session_ui_page: "Page",
) -> None:
    driver_id = styrmin_resources["driver_id"]
    page = session_ui_page

    # 1. Navigate to the driver detail page.
    await page.goto(f"/drivers/{driver_id}")

    # 2. Page root present with the expected data attributes — confirms the
    # redesigned header + tabs layout rendered, addressing a single version.
    detail_root = page.locator("[data-testid=driver-detail]")
    await expect(detail_root).to_be_visible()
    await expect(detail_root).to_have_attribute("data-driver-id", driver_id)
    version_id = await detail_root.get_attribute("data-version-id")
    assert version_id, "detail root should carry the selected data-version-id"

    # 3. Overview tab is active by default — the Details panel is visible.
    await expect(page.locator("[data-testid=driver-overview]")).to_be_visible()

    # 4. Switch to Parameters — the panel renders (table or empty state) and
    # the Overview panel is unmounted (tabs are wired to distinct panels).
    await page.get_by_role("button", name="Parameters").click()
    await expect(page.locator("[data-testid=driver-overview]")).to_have_count(0)

    # 5. Switch to Components — at least one structured component row and ZERO
    # `<pre>` elements anywhere (headline assertion: no JSON dumps).
    await page.get_by_role("button", name="Components").click()
    structured_components = page.locator("[data-testid=driver-component-row]")
    component_count = await structured_components.count()
    assert component_count >= 1, (
        "Components tab should render at least one structured component row "
        f"for simple-app (server + database), got {component_count}"
    )
    pre_count = await page.locator("pre").count()
    assert pre_count == 0, (
        f"Components tab must render zero <pre> JSON blocks; found {pre_count}"
    )
