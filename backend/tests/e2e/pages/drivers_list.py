"""Page object for the Add Driver flow (``/drivers/add``)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from playwright.async_api import expect

from tests.e2e.drivers.errors import ScenarioActionError
from tests.e2e.drivers.refs import DriverVersionRef

if TYPE_CHECKING:
    from playwright.async_api import Page


class DriversListPage:
    """Drivers list + the Add Driver form (remote Git flow)."""

    def __init__(self, page: Page) -> None:
        self._page = page

    async def load_remote_version(self, *, git_url: str, ref: str) -> DriverVersionRef:
        """Drive AddDriverPage (Remote tab) and return the new version ref.

        On success AddDriverPage navigates to ``/drivers/<applicationDriverId>``
        — the driver detail page. We read the driver id from the URL and the
        version id from the most recently added version card.
        """
        await self._page.goto("/drivers/add")
        await expect(
            self._page.get_by_role("heading", name="Add Driver")
        ).to_be_visible()

        await self._page.get_by_role("button", name="Remote", exact=True).click()
        await self._page.locator("#repositoryUrl").fill(git_url)
        branch_input = self._page.locator("#branch")
        await branch_input.fill(ref)
        await self._page.get_by_role("button", name="Load Driver").click()

        # Navigation to /drivers/<id> is the success signal.
        detail_root = self._page.locator("[data-testid=driver-detail]").first
        await detail_root.wait_for()

        application_driver_id = await detail_root.get_attribute("data-driver-id")
        driver_name = (await detail_root.get_attribute("data-driver-name")) or ""
        if not application_driver_id:
            raise ScenarioActionError(
                "driver detail page rendered without data-driver-id"
            )

        # Pick the first version card (AddDriverPage lists versions newest-first
        # — we just loaded one).
        card = self._page.locator("[data-testid=driver-version-card]").first
        await card.wait_for()
        version_id = await card.get_attribute("data-version-id")
        version = (await card.get_attribute("data-version-label")) or ""
        if not version_id:
            raise ScenarioActionError(
                "driver version card rendered without data-version-id"
            )

        # Also validate the URL matches the detail root, just to catch
        # layout surprises during refactors.
        path = urlparse(self._page.url).path
        if not path.endswith(application_driver_id):
            raise ScenarioActionError(
                f"expected URL to end with driver id {application_driver_id!r}, "
                f"got {path!r}"
            )
        return DriverVersionRef(
            id=version_id,
            application_driver_id=application_driver_id,
            driver_name=driver_name,
            version=version,
        )
