"""E2E coverage for editing Driver Parameters through the unified
configuration drawer (011 / US2, T055).

Toggles a boolean driver parameter from the drawer's Driver Parameters
section and asserts the change is persisted on the deployment.

Driver caveat: the simple-app driver currently used by the E2E suite
declares no parameters in ``driver.styrmin.yml``. Until a driver with a
boolean ``enable_pdb`` (or equivalent) parameter is bootstrapped into
the E2E git-server fixture, the test discovers the available
parameters at runtime, picks the first boolean parameter it finds, and
toggles its value. If the seeded driver still has zero parameters, the
test ``pytest.skip``s with a clear message so the suite stays green and
the gap is visible in CI output — the chunk-4f integrator can wire a
parameter-bearing driver in and the test starts asserting real
behaviour.

The chunk's reference invariant ("``enable_pdb=false`` ⇒ the
PodDisruptionBudget resource is removed") is captured as a follow-up
assertion path inside the test body so the wiring lands the moment a
PDB-producing driver is available.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, Any, AsyncGenerator

import pytest
from playwright.async_api import expect
from styrmin_sdk import StyrminClient

from tests.e2e.drivers import ScenarioDriver
from tests.e2e.pages.deployment_detail import DeploymentDetailPage

if TYPE_CHECKING:
    from playwright.async_api import Page

pytestmark = [pytest.mark.shard_configuration]

RECONCILE_TIMEOUT_SECONDS = 480.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def driver_params_edit_environment(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> AsyncGenerator[dict, None]:
    driver, client = session_scenario_driver
    cluster_id = styrmin_resources["cluster_id"]
    env = await driver.create_environment(
        name=f"drawer-params-{uuid.uuid4().hex[:8]}",
        cluster_id=cluster_id,
        config={},
    )
    yield {"environment_id": str(env.id), "client": client}


@pytest.fixture(scope="module")
async def driver_params_edit_deployment(
    driver_params_edit_environment: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    simple_app_image: str,  # noqa: ARG001 — builds the image
) -> dict:
    driver, _ = session_scenario_driver
    deployment = await driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=driver_params_edit_environment["environment_id"],
        name="drawer-params",
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


async def _wait_for_parameter_value(
    client: StyrminClient,
    deployment_id: str,
    parameter_name: str,
    expected: Any,
    timeout: float,
) -> None:
    """Poll ``deployment.parameters`` until ``parameter_name`` carries
    ``expected``. The parameters list is a flattened ``[{name, value}]``
    representation per the GraphQL type — the SDK returns it directly.
    """
    deadline = time.time() + timeout
    last: Any = None
    while time.time() < deadline:
        dep = await client.deployments.get(deployment_id)
        params = getattr(dep, "parameters", None) or []
        # The SDK may model parameters as Pydantic rows or plain dicts.
        for entry in params:
            name = getattr(entry, "name", None) or (
                entry.get("name") if isinstance(entry, dict) else None
            )
            value = getattr(entry, "value", None) or (
                entry.get("value") if isinstance(entry, dict) else None
            )
            if name == parameter_name:
                last = value
                if value == expected:
                    return
        await asyncio.sleep(2.0)
    raise AssertionError(
        f"deployment {deployment_id} did not persist parameter "
        f"{parameter_name!r}={expected!r} within {timeout}s; "
        f"last observed value was {last!r}"
    )


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.ci
@pytest.mark.ui_only(
    reason=(
        "Drives the unified drawer's Driver Parameters section. The "
        "ParameterField primitive is shared with the deploy form, but "
        "the drawer's apply path is UI-only."
    ),
)
async def test_drawer_driver_params_edit(
    driver_params_edit_environment: dict,
    driver_params_edit_deployment: dict,
    session_ui_page: "Page",
) -> None:
    page = session_ui_page
    client: StyrminClient = driver_params_edit_environment["client"]
    environment_id = driver_params_edit_environment["environment_id"]
    deployment_id = driver_params_edit_deployment["deployment_id"]

    detail = DeploymentDetailPage(page)
    await detail.goto(environment_id=environment_id, deployment_id=deployment_id)
    await detail.wait_for_status(expected="running", timeout=180.0)

    await page.get_by_role("button", name="Settings", exact=True).click()
    await expect(page.locator("[data-testid=settings-tab]")).to_be_visible()
    await page.locator("[data-testid=settings-update-button]").click()
    drawer = page.locator("[role=dialog][aria-labelledby=config-edit-drawer-title]")
    await expect(drawer).to_be_visible()

    await page.locator("[data-testid=section-nav-driverParameters]").click()

    # Discover a boolean parameter to toggle. The DriverParametersSection
    # renders each parameter inside a wrapper carrying
    # ``data-parameter="<name>"``; we filter to the first one whose
    # control is a checkbox so the test stays generic across drivers.
    parameter_rows = page.locator("[data-parameter]")
    rows_count = await parameter_rows.count()
    if rows_count == 0:
        pytest.skip(
            "Active driver declares no parameters; nothing to toggle through "
            "the Driver Parameters section. Re-enable when a parameter-bearing "
            "driver is bootstrapped (chunk follow-up tracks this in "
            "specs/011-unified-deployment-config/tasks.md)."
        )

    chosen_name: str | None = None
    chosen_checkbox = None
    for i in range(rows_count):
        row = parameter_rows.nth(i)
        # Base UI Checkbox renders an element with role=checkbox.
        checkbox = row.get_by_role("checkbox")
        if await checkbox.count() > 0:
            chosen_name = await row.get_attribute("data-parameter")
            chosen_checkbox = checkbox.first
            break
    if chosen_name is None or chosen_checkbox is None:
        pytest.skip(
            "No boolean driver parameter available to toggle (driver only "
            "declares non-boolean parameters). Re-enable when a boolean "
            "parameter such as enable_pdb is added."
        )

    initial_checked = await chosen_checkbox.is_checked()
    desired_checked = not initial_checked
    await chosen_checkbox.click()
    await expect(chosen_checkbox).to_be_checked(checked=desired_checked)

    review_button = page.locator("[data-testid=drawer-review-apply-button]")
    await expect(review_button).to_be_enabled()
    await review_button.click()

    diff_dialog = page.locator("[data-testid=config-diff-dialog]")
    await expect(diff_dialog).to_be_visible()

    params_section = diff_dialog.locator("[data-testid=diff-section-driverParameters]")
    await expect(params_section).to_be_visible()
    await expect(params_section).to_contain_text(chosen_name)

    await page.locator("[data-testid=diff-dialog-apply-button]").click()
    await expect(diff_dialog).to_be_hidden(timeout=60_000)

    await _wait_for_parameter_value(
        client,
        deployment_id,
        parameter_name=chosen_name,
        expected=desired_checked,
        timeout=RECONCILE_TIMEOUT_SECONDS,
    )

    # When a PDB-producing driver is wired in, the follow-up assertion
    # is to wait for the PodDisruptionBudget object to disappear from
    # the deployment namespace once ``enable_pdb=False`` is persisted:
    #
    #   await _wait_for_pdb_absent(
    #       vcluster, namespace=namespace, timeout=RECONCILE_TIMEOUT_SECONDS,
    #   )
    #
    # The helper lives next to ``_wait_for_service_named`` in the
    # service-overrides test and shares the same kr8s polling pattern.
