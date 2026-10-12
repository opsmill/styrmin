"""Page object for the cluster detail page (``/clusters/$clusterId``).

Each configuration area renders as a ``<section>`` labelled by its heading
(``ClusterConfiguration.tsx``), so sections resolve by ARIA ``region`` name.
The admin-only Edit button opens ``EditClusterDialog.tsx``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, expect

from tests.e2e.drivers.errors import ScenarioActionError

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page

_EDIT_DIALOG_TITLE = "Edit Cluster Configuration"


class ClusterDetailPage:
    def __init__(self, page: Page) -> None:
        self._page = page

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
        await self._edit_dialog().get_by_label("FQDN Suffix", exact=True).fill(value)

    async def save(self) -> None:
        """Save the dialog; it closes once the server accepted the update."""
        dialog = self._edit_dialog()
        await dialog.get_by_role("button", name="Save", exact=True).click()
        try:
            await dialog.wait_for(state="hidden", timeout=30_000)
        except PlaywrightTimeoutError as exc:
            # A refused update keeps the dialog open with an inline alert.
            alert = dialog.get_by_role("alert")
            message = (
                await alert.inner_text()
                if await alert.count() > 0
                else "(no alert rendered)"
            )
            raise ScenarioActionError(
                f"cluster config save did not close the dialog: {message}"
            ) from exc
