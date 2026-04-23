"""Page object for the drivers list view (``/drivers``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.drivers.refs import DriverVersionRef

if TYPE_CHECKING:
    from playwright.async_api import Page


class DriversListPage:
    """Drivers list — add-driver dialog (paste git URL + ref)."""

    def __init__(self, page: Page) -> None:
        self._page = page

    async def add_driver(self, *, git_url: str, ref: str) -> DriverVersionRef:
        raise NotImplementedError  # T017
