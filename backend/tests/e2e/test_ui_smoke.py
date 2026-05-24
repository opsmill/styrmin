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

    # And the rendered header value should match — and must not be a UUID.
    header_text = await page.read_header_driver_text()
    assert header_text == "simple-app", (
        f"deployment header should show driver name 'simple-app', got {header_text!r}"
    )
    assert not UUID_RE.match(header_text), (
        f"deployment header is rendering a UUID instead of a driver name: {header_text!r}"
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
    # new orchestrator rendered (vs the legacy single-column layout).
    detail_root = page.locator("[data-testid=driver-detail]")
    await expect(detail_root).to_be_visible()
    await expect(detail_root).to_have_attribute("data-driver-id", driver_id)

    # 3. Left rail — at least one row present, the first is selected by
    # default (newest-by-`createdOn` per FR-001).
    rail = page.locator("[data-testid=driver-version-list]")
    await expect(rail).to_be_visible()
    rows = page.locator("[data-testid=driver-version-row]")
    row_count = await rows.count()
    assert row_count >= 1, (
        f"left rail should render at least one version row, got {row_count}"
    )
    first_row = rows.first
    await expect(first_row).to_have_attribute("data-selected", "true")
    await expect(first_row).to_have_attribute("aria-pressed", "true")

    # 4. Right pane — version detail is visible with the Overview tab active
    # by default (FR-007).
    version_detail = page.locator("[data-testid=driver-version-detail]")
    await expect(version_detail).to_be_visible()
    await expect(
        page.locator("[data-testid=driver-overview-tiles]"),
    ).to_be_visible()

    # 5. Switch to Parameters tab — assert the panel renders (table or empty
    # state). The crucial behavioural contract is that the tab is wired to a
    # panel and the previous (Overview) panel is unmounted.
    await page.get_by_role("button", name="Parameters", exact=True).click()
    await expect(
        page.locator("[data-testid=driver-overview-tiles]"),
    ).to_have_count(0)

    # 6. Switch to Components tab and assert structured rendering — at least
    # one component row, and ZERO `<pre>` elements anywhere on the page (the
    # spec's headline assertion: no JSON dumps).
    await page.get_by_role("button", name="Components", exact=True).click()
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

    # 7. Switch to Source tab — git-sourced driver should expose the
    # repository URL via the git source layout.
    await page.get_by_role("button", name="Source", exact=True).click()
    git_source = page.locator("[data-testid=driver-source-git]")
    await expect(git_source).to_be_visible()
    repository = page.locator("[data-testid=driver-source-repository]")
    repo_text = await repository.text_content()
    assert repo_text and repo_text.strip(), (
        f"Source tab should expose a non-empty repository URL; got {repo_text!r}"
    )

    # 8. Click back to the first (selected) row — selection should be a no-op
    # and the page should remain on the Source tab, exercising the
    # "tab persists across version switches" contract (FR-007).
    await first_row.click()
    await expect(git_source).to_be_visible()
