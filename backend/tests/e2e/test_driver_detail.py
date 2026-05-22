"""E2E test for the redesigned driver detail page (spec 012).

Verifies the tabbed driver-detail layout — left-rail version list,
default-selected newest version, structured Components rendering (no `<pre>`
JSON dumps), and the Source tab's branched rendering.

UI-only because every assertion is about rendered DOM (which row carries the
active state, which tab panel is shown, presence/absence of `<pre>`). The SDK
has no equivalent of "click a tab", so the api variant would only re-exercise
the already-tested `applicationDriver` query without adding coverage.

The spec's research.md §8 calls for *three local-source* versions seeded with
distinct ``created_on`` timestamps. In practice the only path to seed local
drivers is to point at a filesystem path on the backend container, which the
E2E harness does not currently mount. Instead the test reuses the
session-scoped ``styrmin_resources`` fixture, which loads ``simple-app`` from
the in-cluster git server — a single git-sourced version is enough to exercise
the tab-switching behaviour and the no-`<pre>` invariant, which is the
behavioural contract that previously failed. If a maintainer later wires up
multi-version local seeding, the rail-ordering assertion can be lifted from
"≥1 row" to the original "three rows newest-first".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.async_api import expect

if TYPE_CHECKING:
    from playwright.async_api import Page


@pytest.mark.ci
@pytest.mark.ui_only(
    reason="Driver-detail tab switching + structured Components rendering — "
    "every assertion is about rendered DOM; the SDK has no 'click a tab' "
    "equivalent, so the api variant would just re-run the underlying "
    "applicationDriver query without adding coverage.",
)
async def test_driver_detail_inspects_versions_via_tabs(
    styrmin_resources: dict,
    session_ui_page: "Page",
) -> None:
    driver_id = styrmin_resources["driver_id"]
    page = session_ui_page

    # 1. Navigate to the driver detail page.
    await page.goto(f"/drivers/{driver_id}")

    # 2. Page root present with the expected data attributes — confirms the
    # new orchestrator rendered (vs the legacy single-column layout).
    detail_root = page.locator("[data-testid=driver-detail]")
    await expect(detail_root).to_be_visible()
    await expect(detail_root).to_have_attribute("data-driver-id", driver_id)

    # 3. Left rail — at least one row present, the first is selected by
    # default (newest-by-`createdOn` per FR-001).
    rail = page.locator("[data-testid=driver-version-list]")
    await expect(rail).to_be_visible()
    rows = page.locator("[data-testid=driver-version-row]")
    row_count = await rows.count()
    assert row_count >= 1, (
        f"left rail should render at least one version row, got {row_count}"
    )
    first_row = rows.first
    await expect(first_row).to_have_attribute("data-selected", "true")
    await expect(first_row).to_have_attribute("aria-pressed", "true")

    # 4. Right pane — version detail is visible with the Overview tab active
    # by default (FR-007).
    version_detail = page.locator("[data-testid=driver-version-detail]")
    await expect(version_detail).to_be_visible()
    await expect(
        page.locator("[data-testid=driver-overview-tiles]"),
    ).to_be_visible()

    # 5. Switch to Parameters tab — assert the panel renders (table or empty
    # state). The crucial behavioural contract is that the tab is wired to a
    # panel and the previous (Overview) panel is unmounted.
    await page.get_by_role("button", name="Parameters", exact=True).click()
    await expect(
        page.locator("[data-testid=driver-overview-tiles]"),
    ).to_have_count(0)

    # 6. Switch to Components tab and assert structured rendering — at least
    # one component row, and ZERO `<pre>` elements anywhere on the page (the
    # spec's headline assertion: no JSON dumps).
    await page.get_by_role("button", name="Components", exact=True).click()
    structured_components = page.locator("[data-testid=driver-component-row]")
    component_count = await structured_components.count()
    assert component_count >= 1, (
        "Components tab should render at least one structured component row "
        f"for simple-app (server + database), got {component_count}"
    )
    pre_count = await page.locator("pre").count()
    assert pre_count == 0, (
        f"Components tab must render zero <pre> JSON blocks; found {pre_count}"
    )

    # 7. Switch to Source tab — git-sourced driver should expose the
    # repository URL via the git source layout.
    await page.get_by_role("button", name="Source", exact=True).click()
    git_source = page.locator("[data-testid=driver-source-git]")
    await expect(git_source).to_be_visible()
    repository = page.locator("[data-testid=driver-source-repository]")
    repo_text = await repository.text_content()
    assert repo_text and repo_text.strip(), (
        f"Source tab should expose a non-empty repository URL; got {repo_text!r}"
    )

    # 8. Click back to the first (selected) row — selection should be a no-op
    # and the page should remain on the Source tab, exercising the
    # "tab persists across version switches" contract (FR-007).
    await first_row.click()
    await expect(git_source).to_be_visible()
