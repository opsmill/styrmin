"""E2E coverage for editing Storage & Runtime through the unified
configuration drawer (011 / US2, T052).

Changes ``db_size`` from the drawer's Storage & Runtime section, asserts
the impact text mentions a storage reconfigure, and asserts the
persisted ``deployment.config.db_size`` reflects the new value.

We deliberately do not assert a Kubernetes-side observation of the new
PVC capacity. Storage class behaviour around resize varies by cluster
backend, and SC-006 for this task is "persisted result + impact text"
not "online PVC expansion verified".
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import pytest
from playwright.async_api import expect
from styrmin_sdk import StyrminClient

from tests.e2e.configuration.conftest import DrawerDeployment
from tests.e2e.pages.deployment_detail import DeploymentDetailPage

if TYPE_CHECKING:
    from playwright.async_api import Page

pytestmark = [pytest.mark.shard_configuration]

RECONCILE_TIMEOUT_SECONDS = 480.0


DRAWER_DEPLOYMENT = DrawerDeployment(name="drawer-storage")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _wait_for_persisted_db_size(
    client: StyrminClient, deployment_id: str, expected: str, timeout: float
) -> None:
    deadline = time.time() + timeout
    last: Any = None
    while time.time() < deadline:
        dep = await client.deployments.get(deployment_id)
        cfg = getattr(dep, "config", None) or {}
        last = cfg.get("db_size") if isinstance(cfg, dict) else None
        if last == expected:
            return
        await asyncio.sleep(2.0)
    raise AssertionError(
        f"deployment {deployment_id} did not persist db_size={expected!r} "
        f"within {timeout}s; last observed value was {last!r}"
    )


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "``db_size`` is still read-only. d688d20 re-introduced the Storage & "
        "Runtime section in the edit drawer, so section-nav-storageRuntime now "
        "exists — but that section edits only ``backup_ttl``. ``db_size`` "
        "and ``standard_storage.storage_class`` were "
        "deliberately left read-only on the Settings tab, so there is no "
        "``storage-db-size`` control for this test to drive. Re-enable when "
        "``db_size`` becomes editable (a product decision, not a follow-up), or "
        "retarget the scenario at ``backup_ttl`` — note the impact assertion "
        "would change too: ``backup_ttl`` is a metadata-only change with no "
        "database resize."
    ),
)
@pytest.mark.ci
@pytest.mark.ui_only(
    reason=(
        "Drives the unified drawer's Storage & Runtime section. No SDK "
        "equivalent for 'open drawer / change db_size / Review & apply' — "
        "the API path is the same mutation already exercised elsewhere."
    ),
)
async def test_drawer_storage_runtime_edit(
    drawer_deployment: dict,
    session_ui_page: "Page",
) -> None:
    page = session_ui_page
    client: StyrminClient = drawer_deployment["client"]
    environment_id = drawer_deployment["environment_id"]
    deployment_id = drawer_deployment["deployment_id"]

    # ``dbSize`` is an enum (small / medium / large / xlarge) backed by a
    # shadcn Select trigger — not a free-text input. We pick ``large`` as
    # the target because the seeded deployment has no override (so any
    # value other than the inherited default is a real change), and
    # because ``large`` exercises a value the impact rule still treats
    # as a database resize.
    new_db_size = "large"

    detail = DeploymentDetailPage(page)
    await detail.goto(environment_id=environment_id, deployment_id=deployment_id)
    await detail.wait_for_status(expected="running", timeout=180.0)

    await page.get_by_role("button", name="Settings", exact=True).click()
    await expect(page.locator("[data-testid=settings-tab]")).to_be_visible()
    await page.locator("[data-testid=settings-update-button]").click()
    drawer = page.locator("[role=dialog][aria-labelledby=config-edit-drawer-title]")
    await expect(drawer).to_be_visible()

    await page.locator("[data-testid=section-nav-storageRuntime]").click()

    db_size_trigger = page.locator("[data-testid=storage-db-size]")
    await expect(db_size_trigger).to_be_visible()
    await db_size_trigger.click()
    # The Radix-backed Select renders options in a portal; match the
    # visible option by role + accessible name.
    await page.get_by_role("option", name=new_db_size, exact=True).click()

    review_button = page.locator("[data-testid=drawer-review-apply-button]")
    await expect(review_button).to_be_enabled()
    await review_button.click()

    diff_dialog = page.locator("[data-testid=config-diff-dialog]")
    await expect(diff_dialog).to_be_visible()

    # Diff rows render the human-readable ``label`` (not ``path``).
    storage_section = diff_dialog.locator("[data-testid=diff-section-storageRuntime]")
    await expect(storage_section).to_be_visible()
    await expect(storage_section).to_contain_text("Database size")

    # The dbSize impact rule consequence text — see frontend/src/lib/
    # impact-rules.ts. We match on a substring rather than the full
    # sentence so that wording tweaks don't break the test.
    impact_section = diff_dialog.locator("[data-testid=diff-dialog-impact-section]")
    await expect(impact_section).to_be_visible()
    await expect(impact_section).to_contain_text("Database resize")

    await page.locator("[data-testid=diff-dialog-apply-button]").click()
    await expect(diff_dialog).to_be_hidden(timeout=60_000)

    await _wait_for_persisted_db_size(
        client, deployment_id, new_db_size, timeout=RECONCILE_TIMEOUT_SECONDS
    )
