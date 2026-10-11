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

from tests.e2e.conftest import SIMPLE_APP_DOCS_URL, SIMPLE_APP_LOGO_URL
from tests.e2e.pages.cluster_detail import ClusterDetailPage
from tests.e2e.pages.deploy_form import DeployFormPage
from tests.e2e.pages.deployment_detail import DeploymentDetailPage
from tests.e2e.pages.drivers_list import DriversListPage
from tests.e2e.pages.pods_tab import PodsTabPage

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page, Route

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


# ---- spec 020: driver logo, description and links ----
# `spec.info.description` of driver/examples/simple-app/driver.styrmin.yml.
SIMPLE_APP_DESCRIPTION = "Simple 3-tier FastAPI application with PostgreSQL"
# Explicit width/height so the decoded image has a non-zero naturalWidth.
SIMPLE_APP_LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
    'viewBox="0 0 24 24"><rect width="24" height="24" fill="#2563eb"/></svg>'
)


async def _serve_simple_app_logo(route: "Route") -> None:
    await route.fulfill(
        status=200, content_type="image/svg+xml", body=SIMPLE_APP_LOGO_SVG
    )


async def _expect_simple_app_logo_loaded(logo: "Locator") -> None:
    img = logo.locator("img")
    await expect(img).to_have_attribute("src", SIMPLE_APP_LOGO_URL)
    # The frame shows the package icon until the image has loaded, and the
    # fallback icon (without the <img>) if the load fails.
    await expect(logo).to_have_attribute("data-logo-state", "image")
    await logo.page.wait_for_function(
        "img => img.complete && img.naturalWidth > 0",
        arg=await img.element_handle(),
    )


async def test_driver_logo_description_and_links_render(
    styrmin_resources: dict,
    session_ui_page: "Page",
) -> None:
    """The session simple-app driver's `spec.info` renders on the driver pages.

    The `git_server` fixture sets the logo and link on a reserved `.invalid`
    host, so the logo loads only through the route below and never by accident.
    """
    driver_id = styrmin_resources["driver_id"]
    page = session_ui_page
    try:
        await page.route(SIMPLE_APP_LOGO_URL, _serve_simple_app_logo)

        # 1. List page: the group header shows the latest version's logo and
        # its description. List logos load lazily, so scroll the group into
        # view as a user would.
        drivers_list = DriversListPage(page)
        await drivers_list.goto()
        group_logo = drivers_list.driver_group_logo("simple-app")
        await group_logo.scroll_into_view_if_needed()
        await _expect_simple_app_logo_loaded(group_logo)
        list_description = page.locator(
            '[data-testid=driver-group][data-driver-name="simple-app"] '
            "[data-testid=driver-description]"
        )
        await expect(list_description).to_have_text(SIMPLE_APP_DESCRIPTION)

        # 2. Detail page: the header logo of the selected version, loaded
        # without scrolling, and the description.
        await page.goto(f"/drivers/{driver_id}")
        await expect(page.locator("[data-testid=driver-detail]")).to_be_visible()
        header_logo = page.locator("[data-testid=driver-logo]")
        await expect(header_logo.locator("img")).to_have_attribute("loading", "eager")
        await _expect_simple_app_logo_loaded(header_logo)
        await expect(page.locator("[data-testid=driver-description]")).to_contain_text(
            SIMPLE_APP_DESCRIPTION
        )

        # 3. Overview tab (default): the link opens in a new tab without
        # giving the target page access to Styrmin's window.
        await expect(page.locator("[data-testid=driver-overview]")).to_be_visible()
        link = page.locator("[data-testid=driver-links]").get_by_role(
            "link", name="Documentation"
        )
        await expect(link).to_have_attribute(
            "href", re.compile(rf"^{re.escape(SIMPLE_APP_DOCS_URL)}")
        )
        await expect(link).to_have_attribute("target", "_blank")
        await expect(link).to_have_attribute("rel", re.compile(r"\bnoopener\b"))
        await expect(link).to_have_accessible_name("Documentation (opens in a new tab)")
        await expect(
            page.locator("[data-testid=driver-links] [data-testid=driver-link-host]")
        ).to_have_text("styrmin-e2e.invalid")
    finally:
        # The page is shared by the whole session: never leave the route on it.
        await page.unroute(SIMPLE_APP_LOGO_URL, _serve_simple_app_logo)


# ---- issue #332: browser tab title ----
async def test_browser_tab_title_names_page_and_product(
    deployed_simple_app: dict,
    session_ui_page: "Page",
    scenario_environment_id: str,
) -> None:
    """The tab title names the product, and the page, on every route.

    Regression guard for #332, where the Vite scaffold default ``frontend``
    was left in the HTML shell and no route ever replaced it.
    """
    page = session_ui_page

    # 1. A static page names itself. `to_have_title` retries: the title is set
    # from a useEffect, which flushes after the render commit, so a one-shot
    # page.title() read can land before it and still see the shell title.
    await page.goto("/drivers")
    await expect(page).to_have_title("Drivers · Styrmin")

    # 2. A detail page names the object it is showing. Compare against the
    # deployment name the page itself rendered (its only <h1>) rather than
    # merely ruling out the loading fallback — a title hard-coded to some other
    # constant would pass that weaker check while the dynamic title regressed.
    detail_page = DeploymentDetailPage(page)
    await detail_page.goto(
        environment_id=scenario_environment_id,
        deployment_id=deployed_simple_app["deployment_id"],
    )
    await detail_page.wait_for_status(expected="running", timeout=120.0)

    heading = page.get_by_role("heading", level=1)
    await expect(heading).to_be_visible()
    deployment_name = (await heading.inner_text()).strip()
    assert deployment_name, "deployment detail page rendered an empty <h1>"

    await expect(page).to_have_title(f"{deployment_name} · Styrmin")


# ---- cluster detail page shows every cluster setting ----
async def test_cluster_detail_shows_full_configuration(
    styrmin_resources: dict,
    session_ui_page: "Page",
) -> None:
    """The session cluster's settings, including its dedicated ingress, render.

    Values come from the ``styrmin_resources`` cluster config. The page
    previously dropped the dedicated ingress service settings, the external
    URL and DNS settings, and the derived capabilities.
    """
    page = ClusterDetailPage(session_ui_page)
    await page.goto(cluster_id=styrmin_resources["cluster_id"])

    ingress = await page.read_section("Dedicated ingress")
    assert "traefik" in ingress, ingress
    assert "LoadBalancer" in ingress, ingress

    networking = await page.read_section("Networking")
    for expected in ("styrmin.com", "8080", "NodeExternalIP"):
        assert expected in networking, networking

    storage = await page.read_section("Storage")
    assert "csi-hostpath-sc" in storage, storage

    capabilities = await page.read_section("Capabilities")
    assert "csi-hostpath-sc" in capabilities, capabilities
    assert "styrmin.com" in capabilities, capabilities
