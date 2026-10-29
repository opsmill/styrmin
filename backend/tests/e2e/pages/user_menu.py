"""Page object for the user menu in the header of every signed-in page.

Selectors mirror the ``data-testid`` values declared in
``frontend/src/components/HeaderUserMenu.tsx``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page


class UserMenu:
    def __init__(self, page: Page) -> None:
        self._page = page

    async def logout(self) -> None:
        """Open the user menu and select Logout."""
        await self._page.get_by_test_id("header-user-menu-trigger").click()
        await self._page.get_by_test_id("header-user-menu-logout").click()
