"""E2E test for the deployment-deletion UI flow (spec 008).

Drives the full UI surface via Playwright: Delete button → type-to-confirm
dialog → post-confirm navigation → ``Deleting…`` badge → row vanishes from
default list → ``Show deleted`` toggle reveals greyed-out row → tombstone
detail page banner + disabled action buttons.

The test is ``ui_only`` because every step exercises UI-specific behaviour
that has no SDK equivalent — the API path is covered separately by
``test_delete_deployment_api.py``.

Covers user stories US1, US2, US3, US4, US12, US13, US15 from the PRD.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING

import pytest
from playwright.async_api import expect

from tests.e2e.drivers import ScenarioDriver
from tests.e2e.pages.deployment_detail import DeploymentDetailPage
from tests.e2e.pages.environments import EnvironmentDetailPage

if TYPE_CHECKING:
    from playwright.async_api import Page


@pytest.mark.ci
@pytest.mark.ui_only(
    reason="Drives the type-to-confirm dialog, list-row badge, Show deleted "
    "toggle, and tombstoned-detail-page banner — none of these have an SDK "
    "equivalent. The API surface is covered by test_delete_deployment_api.py."
)
async def test_delete_deployment_ui(
    scenario_driver: ScenarioDriver,
    scenario_environment_id: str,
    styrmin_resources: dict,
    simple_app_image: str,  # noqa: ARG001 — ensures image is built
    session_ui_page: Page,
) -> None:
    """End-to-end deletion via the UI: dialog gating → list state → tombstoned page."""
    client = styrmin_resources["client"]

    # 1. Deploy a fresh simple-app into the shared scenario env. Use a
    # unique service-name override to coexist with the session-scoped
    # ``deployed_simple_app`` deployment.
    override = f"ui-del-{uuid.uuid4().hex[:6]}"
    deployment = await scenario_driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=scenario_environment_id,
        service_name_overrides=[
            {"driverServiceName": "simple-app", "overrideName": override}
        ],
    )
    deployment = await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment.id, timeout=300.0
    )
    deployment_id = deployment.id
    # DeploymentRef doesn't expose `name`; the type-to-confirm dialog needs
    # the exact deployment name, so fetch it via the SDK directly.
    sdk_dep = await client.deployments.get(deployment_id)
    deployment_name = sdk_dep.name

    detail_page = DeploymentDetailPage(session_ui_page)
    list_page = EnvironmentDetailPage(session_ui_page)

    # 2. Open the deployment detail page and verify the Delete button is
    # present and enabled (US3 — Delete sits beside Upgrade/Redeploy).
    await detail_page.goto(
        environment_id=scenario_environment_id, deployment_id=deployment_id
    )
    await detail_page.wait_for_status(expected="running", timeout=60.0)

    # 3. Click Delete → dialog opens (US1).
    await detail_page.open_delete_dialog()

    # 4. Type-to-confirm gating (US2).
    # 4a. Confirm button starts disabled (empty input).
    assert await detail_page.delete_confirm_button_is_disabled(), (
        "Confirm button must be disabled with empty input"
    )

    # 4b. Wrong name keeps it disabled.
    await detail_page.fill_delete_confirm("not-the-name")
    assert await detail_page.delete_confirm_button_is_disabled(), (
        "Confirm button must be disabled when input != deployment name"
    )

    # 4c. Case mismatch keeps it disabled (case-sensitive match).
    await detail_page.fill_delete_confirm(deployment_name.upper())
    assert await detail_page.delete_confirm_button_is_disabled(), (
        "Confirm button must be disabled on case mismatch"
    )

    # 4d. Exact match enables it.
    await detail_page.fill_delete_confirm(deployment_name)
    assert not await detail_page.delete_confirm_button_is_disabled(), (
        "Confirm button must be enabled when input == deployment name (exact)"
    )

    # 5. Confirm → dialog closes; navigate to env list. The frontend
    # invalidates the GetEnvironment query so the row picks up the new
    # status on the next refetch.
    await detail_page.confirm_delete()

    # The redirect target is /environments/{environmentId}; landing on it
    # may take a tick. Once there, the row should still be visible (not
    # hidden yet) with the Deleting… badge (US15 / FR-028).
    await list_page.goto(environment_id=scenario_environment_id)

    # 6. Row remains visible with the Deleting… badge while teardown is
    # in progress (US4, US15, FR-028). Poll until the badge appears
    # because the urql cache may briefly return the pre-mutation state.
    deadline = time.time() + 120.0
    saw_deleting_badge = False
    while time.time() < deadline:
        if await list_page.row_has_deleting_badge(deployment_id=deployment_id):
            saw_deleting_badge = True
            break
        # Auto-refetch is on a 10s tick; nudge by re-navigating to force a
        # refetch sooner than that.
        await list_page.goto(environment_id=scenario_environment_id)
        await asyncio.sleep(2.0)
    assert saw_deleting_badge, "Row should show the 'Deleting…' badge during teardown"

    # 7. Once cluster teardown completes, the row vanishes from the
    # default list view (US5, FR-029). The agent's status reporter
    # synthesises the terminal Deleted state so this is bounded by the
    # namespace-finaliser window plus one reporter tick.
    await list_page.wait_for_row_to_vanish(deployment_id=deployment_id, timeout=300.0)

    # 8. Toggle Show deleted (US6, FR-030) — row reappears, greyed,
    # with relative-time deletion timestamp (FR-031).
    await list_page.toggle_show_deleted()
    await list_page.wait_for_row_to_appear(deployment_id=deployment_id, timeout=30.0)
    final_status = await list_page.read_row_status(deployment_id=deployment_id)
    assert final_status == "deleted", (
        f"Tombstoned row should report status 'deleted', got {final_status!r}"
    )

    # 9. Click into the tombstoned detail page (US7, FR-032).
    await detail_page.goto(
        environment_id=scenario_environment_id, deployment_id=deployment_id
    )

    # 10. The 'Deleted at <timestamp>' banner is rendered (US13,
    # FR-032). Polls for the banner — goto() doesn't wait for the
    # GraphQL query to settle, so the assertion would otherwise race
    # the data fetch against the empty DOM.
    await detail_page.wait_for_deleted_banner(timeout=30.0)

    # 11. Every header lifecycle action button is disabled (US12,
    # FR-033). Note: the per-backup Restore/Delete buttons inside the
    # Backups tab are also gated on `deploymentTerminal`, but they're
    # only present once the tab is opened — we cover them by attribute
    # check rather than DOM walk to avoid tab-state coupling.
    await detail_page.assert_action_buttons_disabled()

    # Sanity: the Delete button itself disappeared / is disabled (the
    # destructive entry point cannot be re-triggered against a
    # tombstoned deployment).
    delete_btn = session_ui_page.locator("[data-testid=delete-deployment-button]")
    if await delete_btn.count() > 0:
        assert await delete_btn.is_disabled(), (
            "Header Delete button must remain disabled on tombstoned deployment"
        )

    # 12. Final cross-check: the row's relative-time element is rendered
    # (FR-031). We don't pin the exact text — the format is a function
    # of wall-clock — but the element's mere presence proves the
    # frontend swapped the components-count column for a deletion
    # timestamp on tombstoned rows.
    await list_page.goto(environment_id=scenario_environment_id)
    await list_page.toggle_show_deleted()
    await list_page.wait_for_row_to_appear(deployment_id=deployment_id, timeout=30.0)
    relative_ts = session_ui_page.locator(
        f"[data-testid=deployment-row][data-deployment-id='{deployment_id}'] "
        "[data-testid=deleted-at-relative]"
    )
    await expect(relative_ts).to_be_visible()
