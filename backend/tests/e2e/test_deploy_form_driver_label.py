"""E2E tests for the deployment creation form driver label (issue #127).

Verifies that after selecting a driver version in the deploy form the trigger
displays the human-readable ``{driverName} v{version}`` label rather than the
raw ``applicationDriverVersionId`` UUID.  The test is UI-only — the fix is
entirely in what the trigger renders.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from tests.e2e.pages.deploy_form import DeployFormPage

if TYPE_CHECKING:
    from playwright.async_api import Page

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@pytest.mark.ci
@pytest.mark.ui_only(reason="Bug fix is purely about what the UI renders")
async def test_deploy_form_shows_driver_label_after_selection(
    session_ui_page: Page,
    scenario_environment_id: str,
) -> None:
    driver_name = "simple-app"
    page = DeployFormPage(session_ui_page)
    await page.goto(environment_id=scenario_environment_id)

    # Open and pick the first simple-app version without submitting the form.
    trigger = session_ui_page.locator("[data-testid=driver-version-select]")
    await trigger.click()
    option = session_ui_page.get_by_role("option").filter(
        has_text=f"{driver_name} v"
    ).first
    await option.click()

    label = await page.read_selected_driver_label()

    assert not UUID_RE.match(label), (
        f"driver-version trigger is rendering a UUID instead of a driver name: {label!r}"
    )
    assert label.startswith(driver_name), (
        f"trigger should start with {driver_name!r}, got {label!r}"
    )
