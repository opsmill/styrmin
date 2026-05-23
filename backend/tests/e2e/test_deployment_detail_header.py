"""E2E tests for the deployment detail header (issue #118).

Verifies the deployment detail page surfaces the human-readable driver
name in its header rather than the underlying
``applicationDriverVersionId`` UUID. The test is UI-only — there is no
equivalent API surface to exercise here.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from tests.e2e.pages.deployment_detail import DeploymentDetailPage

if TYPE_CHECKING:
    from playwright.async_api import Page

pytestmark = [
    pytest.mark.shard_mutation_small,
]

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@pytest.mark.ci
@pytest.mark.ui_only(reason="Bug fix is purely about what the UI renders")
async def test_deployment_header_shows_driver_name(
    deployed_simple_app: dict,
    session_ui_page: Page,
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
