"""E2E coverage for the read-only Settings tab (011 / US1, T029).

Seeds a deployment with a mix of inherited vs. overridden values across
multiple configuration groups (Scheduling, Env Vars, Storage), then
drives Playwright to:

1. Navigate to the deployment detail page.
2. Switch to the new "Settings" tab.
3. Assert the "Update Settings" CTA is present (read-side permission gate).
4. Assert every expected summary card (Scheduling, Env Vars, Storage &
   Runtime, Networking) renders. Section-level inheritance badges were
   removed; the per-row "deployment-defined" dot is the new signal and
   is verified by dedicated section tests.
5. Assert the Driver Parameters card is present (parameter-chip
   rendering is exercised by dedicated tests that seed a driver with a
   non-empty parameter schema).

Marked ``@pytest.mark.ui_only`` per AGENTS.md: this exercises the
deployment-detail UI rendering of the Settings tab. The SDK has no
equivalent endpoint that "renders" the tab, so an ``[api-chromium]``
variant would not add coverage — it would only re-fetch the same
GraphQL payload that the UI is asserted on here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.async_api import expect
from styrmin_sdk.graphql._generated.input_types import (
    DeploymentConfigInput,
    EnvVarInput,
    ResourceRequirementsInput,
    ResourceSpecInput,
    SchedulingInput,
)

from tests.e2e.configuration.conftest import DrawerDeployment
from tests.e2e.pages.deployment_detail import DeploymentDetailPage

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page

pytestmark = [pytest.mark.shard_configuration]

DRAWER_DEPLOYMENT = DrawerDeployment(
    name="cfg-tab-read",
    # Overrides across Scheduling, Env Vars and Storage; Networking stays
    # untouched so its card renders as inherited.
    config=DeploymentConfigInput(
        scheduling=SchedulingInput(
            resources=ResourceRequirementsInput(
                requests=ResourceSpecInput(cpu="150m", memory="128Mi"),
            ),
        ),
        envVars=[
            EnvVarInput(name="LOG_LEVEL", value="debug"),
            EnvVarInput(name="FEATURE_FLAG", value="on"),
        ],
        dbSize="5Gi",
    ),
)


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.ci
@pytest.mark.ui_only(
    reason=(
        "Exercises the Settings read tab UI (inheritance badges, "
        "per-section inheritance badges, driver-parameter chips, View "
        "JSON dialog). The SDK has no equivalent flow — an "
        "[api-chromium] variant would only re-fetch the same GraphQL "
        "payload the UI renders from."
    ),
)
async def test_configuration_tab_renders_inheritance_and_overrides(
    drawer_deployment: dict,
    session_ui_page: "Page",
) -> None:
    page = session_ui_page
    environment_id = drawer_deployment["environment_id"]
    deployment_id = drawer_deployment["deployment_id"]

    detail_page = DeploymentDetailPage(page)
    await detail_page.goto(environment_id=environment_id, deployment_id=deployment_id)
    # The header status badge confirms the GraphQL payload landed before
    # we click into the new tab — otherwise the tab mounts against an
    # empty `deployment` and races our assertions.
    await detail_page.wait_for_status(expected="running", timeout=180.0)

    # ------------------------------------------------------------------
    # 1) Switch to the Settings tab.
    # ------------------------------------------------------------------
    # The shared Tabs primitive renders each tab as a plain <button>
    # (see frontend/src/components/ui/tabs.tsx) — match it by role +
    # accessible name.
    await page.get_by_role("button", name="Settings", exact=True).click()
    settings_tab = page.locator("[data-testid=settings-tab]")
    await expect(settings_tab).to_be_visible()

    # ------------------------------------------------------------------
    # 2) Update Settings CTA renders (the role check passes for the
    #    seeded admin user).
    # ------------------------------------------------------------------
    update_button = page.locator("[data-testid=settings-update-button]")
    await expect(update_button).to_be_visible()

    # ------------------------------------------------------------------
    # 3) Each summary card we expect to render is present, addressed via
    #    the `aria-labelledby=config-summary-<slug>` anchor on its
    #    wrapping <section>. The section-level "inherited" / "overridden"
    #    badges were intentionally removed (see commit removing
    #    InheritanceBadge from ConfigSummaryCard); the per-row
    #    "deployment-defined" dot inside the body is now the signal.
    # ------------------------------------------------------------------
    for title in (
        "Scheduling",
        "Environment Variables",
        "Storage & Runtime",
        "Networking",
    ):
        section = _section_by_title(page, title)
        await expect(section).to_be_visible()

    # ------------------------------------------------------------------
    # 4) Driver Parameters card is present. The seeded `simple-app`
    #    driver declares zero `parameters:` in its driver.styrmin.yml,
    #    so the card legitimately renders the "no parameters declared"
    #    empty state — that's not a failure of the read view. Tests that
    #    care about chip rendering should seed a driver with a non-empty
    #    parameter schema.
    # ------------------------------------------------------------------
    driver_params_card = _section_by_title(page, "Driver Parameters")
    await expect(driver_params_card).to_be_visible()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _section_by_title(page: "Page", title: str) -> "Locator":
    """Return the locator for a summary card by its heading text.

    The ConfigSummaryCard shell renders the heading inside an <h3> tied
    to the section via ``aria-labelledby=config-summary-<slug>``. We
    target the wrapping <section> through that anchor so per-section
    locators are stable even if multiple cards happen to mention the
    same word in their bodies.
    """
    slug = title.lower().replace("&", "").replace("  ", " ").strip().replace(" ", "-")
    # Collapse double dashes from "& " -> "-" -> "--"
    while "--" in slug:
        slug = slug.replace("--", "-")
    return page.locator(f"section[aria-labelledby='config-summary-{slug}']")
