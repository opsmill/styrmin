"""Page object for the sidebar that every Styrmin page shows."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page


class SidebarPage:
    def __init__(self, page: Page) -> None:
        self._page = page

    async def open(self, label: str) -> None:
        """Click the sidebar link ``label``, for example "Backup Storage", instead of opening the page by its address.

        The sidebar lists Environments and Drivers at the top, and Clusters, Backup Storage and Settings at the
        bottom, outside its ``<nav>`` element.
        """
        await (
            self._page.locator("aside")
            .get_by_role("link", name=label, exact=True)
            .click()
        )
