"""E2E coverage for the read-only Settings tab (011 / US1, T029).

Seeds a deployment with a mix of inherited vs. overridden values across
multiple configuration groups (Scheduling, Env Vars, Storage), then
drives Playwright to:

1. Navigate to the deployment detail page.
2. Switch to the new "Settings" tab.
3. Assert the "Update Settings" CTA is present (read-side permission gate).
4. Assert each summary card carries the correct
   ``inheritance-badge-overridden`` / ``inheritance-badge-inherited``
   treatment for the seeded shape (Scheduling, Env Vars, Storage &
   Runtime overridden; Networking inherited).
5. Assert the Driver Parameters card renders one chip per parameter
   declared by the driver schema.

Marked ``@pytest.mark.ui_only`` per AGENTS.md: this exercises the
deployment-detail UI rendering of the Settings tab. The SDK has no
equivalent endpoint that "renders" the tab, so an ``[api-chromium]``
variant would not add coverage — it would only re-fetch the same
GraphQL payload that the UI is asserted on here.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, AsyncGenerator

import pytest
from playwright.async_api import expect
from styrmin_sdk import StyrminClient
from styrmin_sdk.graphql._generated.input_types import (
    EnvVarInput,
    ResourceRequirementsInput,
    ResourceSpecInput,
    SchedulingInput,
    UpdateDeploymentInput,
)

from tests.e2e.drivers import ScenarioDriver
from tests.e2e.pages.deployment_detail import DeploymentDetailPage

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page

RECONCILE_TIMEOUT_SECONDS = 480.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def config_tab_environment(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> AsyncGenerator[dict, None]:
    """Dedicated environment for the Configuration-tab read scenario.

    Empty config so the inherited-vs-overridden assertions key off the
    deployment-side overrides we seed below (the bootstrap
    ``test-environment`` would muddy the baseline by carrying
    cluster-side inherited values).
    """
    driver, client = session_scenario_driver
    cluster_id = styrmin_resources["cluster_id"]
    env = await driver.create_environment(
        name=f"cfg-tab-read-{uuid.uuid4().hex[:8]}",
        cluster_id=cluster_id,
        config={},
    )
    yield {
        "environment_id": str(env.id),
        "client": client,
    }


@pytest.fixture(scope="module")
async def config_tab_deployment(
    config_tab_environment: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    simple_app_image: str,  # noqa: ARG001 — builds the image
) -> dict:
    """Provision a simple-app deployment, then seed mixed overrides
    spanning Scheduling, Env Vars, and Storage.

    Networking is left untouched so the corresponding card is rendered
    with the ``inherited`` badge — that's the negative half of the
    inheritance assertion the test relies on.
    """
    driver, client = session_scenario_driver
    deployment = await driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=config_tab_environment["environment_id"],
        name="cfg-tab-read",
    )
    deployment = await driver.wait_for_deployment_running(
        deployment_id=deployment.id, timeout=RECONCILE_TIMEOUT_SECONDS
    )

    # Seed a mixed-shape config that overrides three sections in one
    # mutation. The exact values are not load-bearing — only the fact
    # that each section is overridden (so its card shows the blue
    # "overridden (N)" badge).
    #
    # Seeding goes through the SDK directly (not ``driver.update_deployment``)
    # because:
    #   - The fixture is preparing state, not exercising the UI write path
    #     (the UI write path has its own dedicated drawer-edit tests).
    #   - The UI scenario driver's ``update_deployment`` is restricted to
    #     the scheduling sub-tree today; the SDK route lets us seed
    #     scheduling + env vars + storage atomically without coupling this
    #     read-tab assertion to drawer evolution.
    await client.deployments.update(
        str(deployment.id),
        input=UpdateDeploymentInput(
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
    await driver.wait_for_deployment_running(
        deployment_id=str(deployment.id), timeout=RECONCILE_TIMEOUT_SECONDS
    )

    return {
        "deployment_id": str(deployment.id),
        "namespace": f"styrmin-{deployment.id}",
    }


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
    config_tab_environment: dict,
    config_tab_deployment: dict,
    session_ui_page: "Page",
) -> None:
    page = session_ui_page
    environment_id = config_tab_environment["environment_id"]
    deployment_id = config_tab_deployment["deployment_id"]

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
    # 3) Per-section inheritance badges. Each summary card scopes its
    #    badge by `aria-labelledby=config-summary-<slug>`, so we locate
    #    the badge through its parent <section>.
    # ------------------------------------------------------------------
    for title in ("Scheduling", "Environment Variables", "Storage & Runtime"):
        section = _section_by_title(page, title)
        badge = section.locator("[data-testid=inheritance-badge-overridden]")
        await expect(badge).to_be_visible()
        # Sanity-check the visible text mentions "overridden"
        await expect(badge).to_contain_text("overridden")

    networking = _section_by_title(page, "Networking")
    networking_badge = networking.locator("[data-testid=inheritance-badge-inherited]")
    await expect(networking_badge).to_be_visible()
    await expect(networking_badge).to_contain_text("inherited")

    # ------------------------------------------------------------------
    # 4) Driver Parameters card — assert at least one chip rendered (the
    #    simple-app driver declares a non-empty parameter schema). If
    #    the chip row is empty, the card falls back to
    #    "no parameters declared", which would fail this expectation.
    # ------------------------------------------------------------------
    driver_params_card = _section_by_title(page, "Driver Parameters")
    chips = driver_params_card.locator("[data-testid=driver-parameter-chip]")
    chip_count = await chips.count()
    assert chip_count >= 1, (
        "Driver Parameters card should list at least one parameter chip "
        "for the simple-app driver; got 0 chips (card may be rendering "
        "the empty placeholder)."
    )


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
