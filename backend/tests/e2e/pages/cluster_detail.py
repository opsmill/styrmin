"""Page object for the cluster detail page (``/clusters/$clusterId``).

Each configuration area renders as a ``<section>`` labelled by its heading
(``ClusterConfiguration.tsx``), so sections resolve by ARIA ``region`` name.
The admin-only Edit button opens ``EditClusterDialog.tsx``, which reviews the
change with a dry run, then saves and shows what the save started.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, expect

from tests.e2e.drivers.errors import ScenarioActionError
from tests.e2e.pages._dom import enter_text

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page

_EDIT_DIALOG_TITLE = "Edit Cluster Configuration"


class ClusterDetailPage:
    def __init__(self, page: Page, *, keystroke_delay_ms: int | None = None) -> None:
        self._page = page
        self._keystroke_delay_ms = keystroke_delay_ms

    async def goto(self, *, cluster_id: str) -> None:
        await self._page.goto(f"/clusters/{cluster_id}")
        await expect(
            self._page.get_by_role("heading", name="Configuration", level=2)
        ).to_be_visible()

    def _section(self, name: str) -> Locator:
        return self._page.get_by_role("region", name=name, exact=True)

    async def read_section(self, name: str) -> str:
        """Return the rendered text of one configuration section."""
        section = self._section(name)
        await expect(section).to_be_visible()
        return await section.inner_text()

    async def wait_for_section_text(self, name: str, text: str) -> None:
        """Wait until a configuration section shows ``text``, e.g. after a save refetches the cluster."""
        await expect(self._section(name)).to_contain_text(text)

    def _edit_dialog(self) -> Locator:
        return self._page.get_by_role("dialog", name=_EDIT_DIALOG_TITLE)

    async def open_edit_dialog(self) -> None:
        await self._page.get_by_role("button", name="Edit", exact=True).click()
        await expect(self._edit_dialog()).to_be_visible()

    async def set_fqdn_suffix(self, value: str) -> None:
        await enter_text(
            self._edit_dialog().get_by_label("FQDN suffix", exact=True),
            value,
            keystroke_delay_ms=self._keystroke_delay_ms,
        )

    async def _alert_text(self) -> str:
        alert = self._edit_dialog().get_by_role("alert").last
        return (
            await alert.inner_text()
            if await alert.count() > 0
            else "(no alert rendered)"
        )

    async def review(self) -> str:
        """Run the dry run and return the text of the review step."""
        dialog = self._edit_dialog()
        await dialog.get_by_role("button", name="Review changes", exact=True).click()
        review = dialog.get_by_test_id("cluster-update-review")
        try:
            await review.wait_for(state="visible", timeout=30_000)
        except PlaywrightTimeoutError as exc:
            raise ScenarioActionError(
                f"cluster config review did not open: {await self._alert_text()}"
            ) from exc
        return await review.inner_text()

    async def save(self) -> str:
        """Review unless already reviewed, save, and close the dialog; return the text of the result step."""
        dialog = self._edit_dialog()
        if not await dialog.get_by_test_id("cluster-update-review").is_visible():
            await self.review()
        await dialog.get_by_role("button", name="Save and redeploy", exact=True).click()
        result = dialog.get_by_test_id("cluster-update-result")
        try:
            await result.wait_for(state="visible", timeout=30_000)
        except PlaywrightTimeoutError as exc:
            # A refused update keeps the review open with an alert next to the buttons.
            raise ScenarioActionError(
                f"cluster config save did not finish: {await self._alert_text()}"
            ) from exc
        text = await result.inner_text()
        await dialog.get_by_role("button", name="Done", exact=True).click()
        await dialog.wait_for(state="hidden")
        return text
