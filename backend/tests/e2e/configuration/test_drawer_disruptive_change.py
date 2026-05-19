"""E2E coverage for the "disruptive change" treatment in the unified
configuration diff dialog (011 / US3, T063).

Seeds a deployment with an existing toleration whose effect is
``PreferNoSchedule``, opens the configuration drawer, flips the effect
to ``NoExecute``, and asserts that the diff dialog renders:

1. The amber "Disruptive" badge in the header
   (``data-testid="diff-dialog-disruptive-banner"``).
2. The canonical high-severity consequence text from
   ``impact-rules.ts``: "Existing pods on tainted nodes will be drained
   immediately".
3. **No type-to-confirm input** — the Apply button is the only confirm
   surface (FR-022).

Apply & redeploy is exercised against the live backend to prove the
flow still works through the amber treatment.

``@pytest.mark.ui_only`` per AGENTS.md / research R-010: the SDK has no
"open drawer / read banner" surface, so a dual-entrypoint API variant
would just re-run the SDK mutation path the chunk 2 propagation tests
already cover.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any, AsyncGenerator

import pytest
from playwright.async_api import expect
from styrmin_sdk import StyrminClient
from styrmin_sdk.graphql._generated.input_types import (
    SchedulingInput,
    TolerationInput,
    UpdateDeploymentInput,
)

from tests.e2e.drivers import ScenarioDriver
from tests.e2e.pages.deployment_detail import DeploymentDetailPage

if TYPE_CHECKING:
    from playwright.async_api import Page

RECONCILE_TIMEOUT_SECONDS = 480.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def disruptive_environment(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> AsyncGenerator[dict, None]:
    driver, client = session_scenario_driver
    cluster_id = styrmin_resources["cluster_id"]
    env = await driver.create_environment(
        name=f"drawer-disruptive-{uuid.uuid4().hex[:8]}",
        cluster_id=cluster_id,
        config={},
    )
    yield {"environment_id": str(env.id), "client": client, "driver": driver}


@pytest.fixture(scope="module")
async def disruptive_deployment(
    disruptive_environment: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    simple_app_image: str,  # noqa: ARG001 — builds the image
    vcluster: dict,
) -> dict:
    driver, client = session_scenario_driver
    deployment = await driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=disruptive_environment["environment_id"],
        name="drawer-disruptive",
    )
    deployment = await driver.wait_for_deployment_running(
        deployment_id=deployment.id, timeout=RECONCILE_TIMEOUT_SECONDS
    )
    # Seed the baseline toleration directly via the SDK rather than going
    # through ``driver.update_deployment``: the UI scenario driver's
    # update path drives the legacy Scheduling header button, which was
    # removed in feature 011's drawer cleanup. The SDK path is the
    # mutation path the drawer ultimately uses anyway.
    await client.deployments.update(
        str(deployment.id),
        input=UpdateDeploymentInput(
            scheduling=SchedulingInput(
                tolerations=[
                    TolerationInput(
                        key="dedicated",
                        operator="EQUAL",
                        value="batch",
                        effect="PREFER_NO_SCHEDULE",
                    )
                ],
            ),
        ),
    )
    # Wait for the seed update to converge so the drawer reads the new
    # baseline rather than the empty pre-seed config.
    await driver.wait_for_deployment_running(
        deployment_id=str(deployment.id), timeout=RECONCILE_TIMEOUT_SECONDS
    )
    return {
        "deployment_id": str(deployment.id),
        "namespace": f"styrmin-{deployment.id}",
        "kubeconfig_path": vcluster["kubeconfig_path"],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _wait_for_persisted_toleration_effect(
    client: StyrminClient,
    deployment_id: str,
    expected: str,
    timeout: float,
) -> None:
    """Poll until ``config.scheduling.tolerations[0].effect`` matches
    ``expected``. The drawer's Apply commits the mutation synchronously;
    the persisted config flips as soon as the mutation returns."""
    deadline = time.time() + timeout
    last: Any = None
    while time.time() < deadline:
        dep = await client.deployments.get(deployment_id)
        cfg = getattr(dep, "config", None) or {}
        if isinstance(cfg, dict):
            sched = cfg.get("scheduling") or {}
            tolerations = sched.get("tolerations") or []
            if tolerations and isinstance(tolerations[0], dict):
                last = tolerations[0].get("effect")
                if last == expected:
                    return
        import asyncio

        await asyncio.sleep(2.0)
    raise AssertionError(
        f"deployment {deployment_id} did not persist "
        f"scheduling.tolerations[0].effect={expected!r} within {timeout}s; "
        f"last observed value was {last!r}"
    )


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.ci
@pytest.mark.ui_only(
    reason=(
        "Asserts on the diff dialog's amber 'Disruptive' header banner — "
        "a pure UI treatment with no SDK equivalent. The Apply mutation "
        "path is already covered by the chunk-2 propagation tests and "
        "the scheduling-edit E2E."
    ),
)
async def test_drawer_disruptive_toleration_effect_change(
    disruptive_environment: dict,
    disruptive_deployment: dict,
    session_ui_page: "Page",
) -> None:
    page = session_ui_page
    client: StyrminClient = disruptive_environment["client"]
    environment_id = disruptive_environment["environment_id"]
    deployment_id = disruptive_deployment["deployment_id"]

    detail = DeploymentDetailPage(page)
    await detail.goto(environment_id=environment_id, deployment_id=deployment_id)
    await detail.wait_for_status(expected="running", timeout=180.0)

    # Open the Configuration tab and drawer.
    await page.get_by_role("button", name="Settings", exact=True).click()
    await expect(page.locator("[data-testid=settings-tab]")).to_be_visible()
    await page.locator("[data-testid=settings-update-button]").click()
    drawer = page.locator("[role=dialog][aria-labelledby=config-edit-drawer-title]")
    await expect(drawer).to_be_visible()

    # Navigate to the Scheduling section.
    await page.locator("[data-testid=section-nav-scheduling]").click()

    # Locate the existing toleration row (seeded with effect=PreferNoSchedule)
    # and flip its Effect select to NoExecute.
    toleration_row = drawer.locator("[data-testid=toleration-row]").first
    await expect(toleration_row).to_be_visible()

    # The Base UI Select trigger is keyed by its <Label htmlFor> — use
    # the accessible name "Effect" within the row.
    effect_trigger = toleration_row.get_by_label("Effect")
    await effect_trigger.click()
    # Options render in a portal at page scope.
    await page.get_by_role("option", name="NO_EXECUTE", exact=True).click()

    # Click Review & apply.
    review_button = page.locator("[data-testid=drawer-review-apply-button]")
    await expect(review_button).to_be_enabled()
    await review_button.click()

    diff_dialog = page.locator("[data-testid=config-diff-dialog]")
    await expect(diff_dialog).to_be_visible()

    # T063 assertion 1: amber disruptive banner in the dialog header.
    disruptive_banner = diff_dialog.locator(
        "[data-testid=diff-dialog-disruptive-banner]"
    )
    await expect(disruptive_banner).to_be_visible()
    await expect(disruptive_banner).to_contain_text("Disruptive")

    # T063 assertion 2: impact list mentions the canonical high-severity
    # consequence text. Substring match keeps the test resilient to
    # minor wording tweaks ahead of the chunk-2 rule audit.
    impact_section = diff_dialog.locator("[data-testid=diff-dialog-impact-section]")
    await expect(impact_section).to_be_visible()
    await expect(impact_section).to_contain_text("drained immediately")

    # T063 assertion 3: no type-to-confirm input (FR-022). The dialog
    # has no <input> element apart from the Base UI close button — the
    # Apply button is the only confirm surface.
    type_to_confirm = diff_dialog.locator(
        "input[placeholder*='confirm' i], "
        "input[aria-label*='confirm' i], "
        "input[data-testid*='confirm']"
    )
    assert await type_to_confirm.count() == 0, (
        "Diff dialog must not surface a type-to-confirm input (FR-022); "
        f"found {await type_to_confirm.count()} candidate input(s)."
    )

    # Apply & redeploy works through the amber treatment.
    apply_button = page.locator("[data-testid=diff-dialog-apply-button]")
    await expect(apply_button).to_be_enabled()
    await apply_button.click()
    await expect(diff_dialog).to_be_hidden(timeout=60_000)

    # Persisted state reflects the new effect.
    await _wait_for_persisted_toleration_effect(
        client,
        deployment_id,
        expected="NoExecute",
        timeout=RECONCILE_TIMEOUT_SECONDS,
    )
