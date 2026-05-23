"""E2E coverage for multi-section edits in the unified configuration
drawer (011 / US2, T056).

Two scenarios:

1. **Multi-section roll-up** — change Scheduling (CPU request) AND Env
   Vars in one drawer trip; the diff dialog lists both sections under
   their respective groups, the impact list mentions the consequences
   for each, and both changes land in the persisted config after Apply.

2. **Concurrent-edit conflict** — open the drawer, mutate the deployment
   out-of-band via the SDK (simulating a second operator), then click
   Review & apply. The dialog must surface the conflict / reload panel
   instead of silently overwriting the out-of-band change. Clicking
   Reload preserves the operator's pending edits on top of the new
   baseline (drawer re-baselines without losing form state).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, Any, AsyncGenerator

import pytest
from playwright.async_api import expect
from styrmin_sdk import StyrminClient
from styrmin_sdk.models import EnvVarInput, UpdateDeploymentInput

from tests.e2e.drivers import ScenarioDriver
from tests.e2e.pages.deployment_detail import DeploymentDetailPage

if TYPE_CHECKING:
    from playwright.async_api import Page

pytestmark = [pytest.mark.shard_mutation_small]

RECONCILE_TIMEOUT_SECONDS = 480.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def multi_section_environment(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> AsyncGenerator[dict, None]:
    driver, client = session_scenario_driver
    cluster_id = styrmin_resources["cluster_id"]
    env = await driver.create_environment(
        name=f"drawer-multi-{uuid.uuid4().hex[:8]}",
        cluster_id=cluster_id,
        config={},
    )
    yield {"environment_id": str(env.id), "client": client}


@pytest.fixture(scope="module")
async def multi_section_deployment(
    multi_section_environment: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    simple_app_image: str,  # noqa: ARG001 — builds the image
) -> dict:
    driver, _ = session_scenario_driver
    deployment = await driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=multi_section_environment["environment_id"],
        name="drawer-multi",
    )
    deployment = await driver.wait_for_deployment_running(
        deployment_id=deployment.id, timeout=RECONCILE_TIMEOUT_SECONDS
    )
    return {
        "deployment_id": str(deployment.id),
        "namespace": f"styrmin-{deployment.id}",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _wait_for_config(
    client: StyrminClient,
    deployment_id: str,
    predicate,
    description: str,
    timeout: float,
) -> Any:
    """Poll the deployment's persisted config until ``predicate`` is true."""
    deadline = time.time() + timeout
    last: Any = None
    while time.time() < deadline:
        dep = await client.deployments.get(deployment_id)
        cfg = getattr(dep, "config", None) or {}
        last = cfg
        try:
            if predicate(cfg):
                return cfg
        except Exception:
            pass
        await asyncio.sleep(2.0)
    raise AssertionError(
        f"deployment {deployment_id} did not satisfy {description} within "
        f"{timeout}s; last observed config={last!r}"
    )


def _has_cpu_request(cfg: dict, expected: str) -> bool:
    if not isinstance(cfg, dict):
        return False
    requests = ((cfg.get("scheduling") or {}).get("resources") or {}).get(
        "requests"
    ) or {}
    return requests.get("cpu") == expected


def _has_env_var(cfg: dict, name: str, value: str) -> bool:
    if not isinstance(cfg, dict):
        return False
    raw = cfg.get("env_vars")
    if isinstance(raw, dict):
        return raw.get(name) == value
    if isinstance(raw, list):
        return any(
            (e.get("name") == name and e.get("value") == value)
            for e in raw
            if isinstance(e, dict)
        )
    return False


# ---------------------------------------------------------------------------
# Test — multi-section roll-up
# ---------------------------------------------------------------------------


@pytest.mark.ci
@pytest.mark.ui_only(
    reason=(
        "Exercises the drawer's section-spanning roll-up. The diff "
        "dialog's per-section grouping and combined impact list have no "
        "SDK equivalent."
    ),
)
async def test_drawer_multi_section_edit(
    multi_section_environment: dict,
    multi_section_deployment: dict,
    session_ui_page: "Page",
) -> None:
    page = session_ui_page
    client: StyrminClient = multi_section_environment["client"]
    environment_id = multi_section_environment["environment_id"]
    deployment_id = multi_section_deployment["deployment_id"]

    new_cpu = "175m"
    new_env_name = "MULTI_SECTION_FLAG"
    new_env_value = f"v-{uuid.uuid4().hex[:6]}"

    detail = DeploymentDetailPage(page)
    await detail.goto(environment_id=environment_id, deployment_id=deployment_id)
    await detail.wait_for_status(expected="running", timeout=180.0)

    await page.get_by_role("button", name="Settings", exact=True).click()
    await expect(page.locator("[data-testid=settings-tab]")).to_be_visible()
    await page.locator("[data-testid=settings-update-button]").click()
    drawer = page.locator("[role=dialog][aria-labelledby=config-edit-drawer-title]")
    await expect(drawer).to_be_visible()

    # Scheduling — change CPU request.
    await page.locator("[data-testid=section-nav-scheduling]").click()
    cpu_input = page.locator("[data-testid=sched-res-requests-cpu]")
    await expect(cpu_input).to_be_visible()
    await cpu_input.fill(new_cpu)
    await cpu_input.press("Tab")

    # Env Vars — add a new row.
    await page.locator("[data-testid=section-nav-envVars]").click()
    await page.locator("[data-testid=add-env-var]").click()
    await page.locator("[data-testid=envvar-name-0]").fill(new_env_name)
    await page.locator("[data-testid=envvar-value-0]").fill(new_env_value)
    await page.locator("[data-testid=envvar-value-0]").press("Tab")

    review_button = page.locator("[data-testid=drawer-review-apply-button]")
    await expect(review_button).to_be_enabled()
    await review_button.click()

    diff_dialog = page.locator("[data-testid=config-diff-dialog]")
    await expect(diff_dialog).to_be_visible()

    # Both per-section diff groups must render with their respective changes.
    scheduling_section = diff_dialog.locator("[data-testid=diff-section-scheduling]")
    env_section = diff_dialog.locator("[data-testid=diff-section-envVars]")
    await expect(scheduling_section).to_be_visible()
    await expect(env_section).to_be_visible()
    # Diff rows render the human-readable ``label`` (path goes into the
    # title attribute, not visible textContent).
    await expect(scheduling_section).to_contain_text("Request cpu")
    await expect(env_section).to_contain_text(new_env_name)

    # Impact list must mention BOTH consequences.
    impact_section = diff_dialog.locator("[data-testid=diff-dialog-impact-section]")
    await expect(impact_section).to_be_visible()
    await expect(impact_section).to_contain_text(
        "Pods will be recreated with new resource limits"
    )
    await expect(impact_section).to_contain_text(
        "Pods will be recreated to pick up new environment"
    )

    await page.locator("[data-testid=diff-dialog-apply-button]").click()
    await expect(diff_dialog).to_be_hidden(timeout=60_000)

    # Both edits must be persisted in the resulting config.
    await _wait_for_config(
        client,
        deployment_id,
        predicate=lambda cfg: (
            _has_cpu_request(cfg, new_cpu)
            and _has_env_var(cfg, new_env_name, new_env_value)
        ),
        description=(
            f"scheduling.resources.requests.cpu={new_cpu!r} AND env_vars["
            f"{new_env_name!r}]={new_env_value!r}"
        ),
        timeout=RECONCILE_TIMEOUT_SECONDS,
    )


# ---------------------------------------------------------------------------
# Test — concurrent-edit conflict
# ---------------------------------------------------------------------------


@pytest.mark.ci
@pytest.mark.ui_only(
    reason=(
        "Exercises FR-029 concurrent-edit reload UX. The conflict panel "
        "and rebaseline flow are UI-only; the SDK has no analogue."
    ),
)
async def test_drawer_concurrent_edit_surfaces_conflict_panel(
    multi_section_environment: dict,
    multi_section_deployment: dict,
    session_ui_page: "Page",
) -> None:
    page = session_ui_page
    client: StyrminClient = multi_section_environment["client"]
    environment_id = multi_section_environment["environment_id"]
    deployment_id = multi_section_deployment["deployment_id"]

    # Per-test unique value so re-runs against a session-scoped resource
    # graph don't collide with prior runs.
    pending_cpu = "125m"
    conflict_env_name = "CONFLICT_E2E"
    conflict_env_value = f"x-{uuid.uuid4().hex[:6]}"

    detail = DeploymentDetailPage(page)
    await detail.goto(environment_id=environment_id, deployment_id=deployment_id)
    await detail.wait_for_status(expected="running", timeout=180.0)

    # 1) Open drawer; make a pending edit in Scheduling.
    await page.get_by_role("button", name="Settings", exact=True).click()
    await expect(page.locator("[data-testid=settings-tab]")).to_be_visible()
    await page.locator("[data-testid=settings-update-button]").click()
    drawer = page.locator("[role=dialog][aria-labelledby=config-edit-drawer-title]")
    await expect(drawer).to_be_visible()

    await page.locator("[data-testid=section-nav-scheduling]").click()
    cpu_input = page.locator("[data-testid=sched-res-requests-cpu]")
    await expect(cpu_input).to_be_visible()
    await cpu_input.fill(pending_cpu)
    await cpu_input.press("Tab")

    # 2) Mutate the deployment out-of-band via the SDK. This simulates a
    #    second operator (or an automation) committing a change between
    #    drawer-open and Apply — the drawer's baseline fingerprint should
    #    move and the diff dialog should surface the conflict panel.
    await client.deployments.update(
        deployment_id,
        input=UpdateDeploymentInput(
            envVars=[EnvVarInput(name=conflict_env_name, value=conflict_env_value)],
        ),
    )

    # 3) Click Review & apply, then click the dialog's Apply button —
    #    the fingerprint re-fetch fires inside the Apply handler (Strategy B,
    #    ConfigDiffDialog.tsx::handleApply), not on dialog open. Without
    #    clicking Apply the dialog would just show the diff with no
    #    conflict-detection signal.
    review_button = page.locator("[data-testid=drawer-review-apply-button]")
    await expect(review_button).to_be_enabled()
    await review_button.click()

    diff_dialog = page.locator("[data-testid=config-diff-dialog]")
    await expect(diff_dialog).to_be_visible()

    apply_button = page.locator("[data-testid=diff-dialog-apply-button]")
    await expect(apply_button).to_be_enabled()
    await apply_button.click()

    # Conflict panel must surface, NOT the regular diff/apply flow.
    conflict_panel = diff_dialog.locator("[data-testid=diff-dialog-conflict-panel]")
    await expect(conflict_panel).to_be_visible()
    await expect(conflict_panel).to_contain_text("modified while you were editing")

    # 4) Reload: the drawer rebaselines against the new persisted state.
    #    Pending edit (cpu = pending_cpu) is preserved on top.
    await page.locator("[data-testid=diff-dialog-reload-button]").click()
    await expect(diff_dialog).to_be_hidden()
    # Drawer stays open (no forceClose); the cpu input still carries our
    # pending value while the now-loaded baseline includes the
    # out-of-band env var.
    await expect(drawer).to_be_visible()
    await expect(cpu_input).to_have_value(pending_cpu)

    # 5) Submit again — fingerprint matches because we rebaselined.
    await review_button.click()
    await expect(diff_dialog).to_be_visible()
    scheduling_section = diff_dialog.locator("[data-testid=diff-section-scheduling]")
    await expect(scheduling_section).to_be_visible()
    await page.locator("[data-testid=diff-dialog-apply-button]").click()
    await expect(diff_dialog).to_be_hidden(timeout=60_000)

    # Final state: both the out-of-band env var AND the operator's CPU
    # change are persisted. Neither silently overwrote the other.
    await _wait_for_config(
        client,
        deployment_id,
        predicate=lambda cfg: (
            _has_cpu_request(cfg, pending_cpu)
            and _has_env_var(cfg, conflict_env_name, conflict_env_value)
        ),
        description=(
            f"scheduling.resources.requests.cpu={pending_cpu!r} AND env_vars["
            f"{conflict_env_name!r}]={conflict_env_value!r}"
        ),
        timeout=RECONCILE_TIMEOUT_SECONDS,
    )
