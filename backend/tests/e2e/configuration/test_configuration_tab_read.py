"""E2E coverage for the read-only Configuration tab (011 / US1, T029).

Seeds a deployment with a mix of inherited vs. overridden values across
multiple configuration groups (Scheduling, Env Vars, Storage), then
drives Playwright to:

1. Navigate to the deployment detail page.
2. Switch to the new "Configuration" tab.
3. Assert the dark hero bar reports plausible
   ``N fields configured · M inherited · K overridden`` counts.
4. Assert each summary card carries the correct
   ``inheritance-badge-overridden`` / ``inheritance-badge-inherited``
   treatment for the seeded shape (Scheduling, Env Vars, Storage &
   Runtime overridden; Networking inherited).
5. Assert the Driver Parameters card renders one chip per parameter
   declared by the driver schema.
6. Open the "View JSON" dialog and assert it shows the persisted
   ``deployment.config`` blob.

Marked ``@pytest.mark.ui_only`` per AGENTS.md: this exercises the
deployment-detail UI rendering of the Configuration tab. The SDK has no
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
    driver, _ = session_scenario_driver
    deployment = await driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=config_tab_environment["environment_id"],
        name="cfg-tab-read",
    )
    deployment = await driver.wait_for_deployment_running(
        deployment_id=deployment.id, timeout=RECONCILE_TIMEOUT_SECONDS
    )

    # Apply a mixed-shape config that overrides three sections in one
    # mutation. The exact values are not load-bearing — only the fact
    # that each section is overridden (so its card shows the blue
    # "overridden (N)" badge).
    await driver.update_deployment(
        deployment_id=str(deployment.id),
        config={
            "scheduling": {
                "resources": {
                    "requests": {"cpu": "150m", "memory": "128Mi"},
                },
            },
            "env_vars": {
                "LOG_LEVEL": "debug",
                "FEATURE_FLAG": "on",
            },
            "db_size": "5Gi",
        },
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
        "Exercises the Configuration read tab UI (hero counts, "
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
    # 1) Switch to the Configuration tab.
    # ------------------------------------------------------------------
    # The shared Tabs primitive renders each tab as a plain <button>
    # (see frontend/src/components/ui/tabs.tsx) — match it by role +
    # accessible name.
    await page.get_by_role("button", name="Configuration", exact=True).click()
    config_tab = page.locator("[data-testid=configuration-tab]")
    await expect(config_tab).to_be_visible()

    # ------------------------------------------------------------------
    # 2) Hero bar — assert the three count spans render with non-empty,
    #    plausible content. We don't pin exact integers because the
    #    `configured`/`inherited` counts are derived from the schema
    #    walker and would couple this test to internal counting logic;
    #    the load-bearing invariants are:
    #      - configured >= overridden (overrides are a subset)
    #      - inherited == configured - overridden
    #      - overridden >= 3 (we seeded scheduling + env_vars + db_size)
    # ------------------------------------------------------------------
    hero = page.locator("[data-testid=config-hero]")
    await expect(hero).to_be_visible()

    configured = await _read_count(page, "[data-testid=hero-configured-count]")
    inherited = await _read_count(page, "[data-testid=hero-inherited-count]")
    overridden = await _read_count(page, "[data-testid=hero-overridden-count]")

    assert overridden >= 3, (
        f"hero should report at least 3 overridden fields after seeding "
        f"scheduling + 2 env_vars + db_size; got overridden={overridden}"
    )
    assert configured >= overridden, (
        f"hero 'configured' count ({configured}) must be >= 'overridden' "
        f"count ({overridden}) — overridden is a subset of configured."
    )
    assert inherited == max(0, configured - overridden), (
        f"hero 'inherited' should equal configured - overridden; got "
        f"configured={configured}, inherited={inherited}, "
        f"overridden={overridden}"
    )

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

    # ------------------------------------------------------------------
    # 5) View JSON dialog opens and shows the persisted blob.
    # ------------------------------------------------------------------
    await page.locator("[data-testid=hero-view-json-button]").click()
    dialog = page.locator("[data-testid=view-json-dialog]")
    await expect(dialog).to_be_visible()
    content = dialog.locator("[data-testid=view-json-content]")
    await expect(content).to_be_visible()
    body = (await content.inner_text()).strip()
    assert body.startswith("{") and body.endswith("}"), (
        f"View JSON dialog should display a JSON object; got {body[:80]!r}..."
    )
    # The seeded LOG_LEVEL override must surface in the JSON view since
    # it is part of the persisted server-side config.
    assert "LOG_LEVEL" in body, (
        f"View JSON content should include the seeded LOG_LEVEL override; "
        f"got body={body[:200]!r}"
    )

    # Close the dialog so the page object stays in a clean state for
    # any follow-up scenarios that reuse the same session_ui_page.
    await page.locator("[data-testid=view-json-close-button]").click()
    await expect(dialog).to_be_hidden()


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


async def _read_count(page: "Page", selector: str) -> int:
    """Read the leading integer from a hero count span's text content.

    The hero spans embed the count followed by units — e.g.
    "5 fields configured" or "2 overridden on this deployment". The
    test asserts on the numeric prefix, ignoring the human-readable
    suffix (which changes shape across cards).
    """
    text = (await page.locator(selector).inner_text()).strip()
    head = text.split()[0]
    try:
        return int(head)
    except ValueError as exc:  # pragma: no cover — defensive
        raise AssertionError(
            f"expected leading integer in {selector!r} text; got {text!r}"
        ) from exc
