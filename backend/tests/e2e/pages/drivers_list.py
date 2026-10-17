"""Page object for the drivers list (`/drivers`) and its Load Driver drawer."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from tests.e2e.drivers.errors import ScenarioActionError
from tests.e2e.drivers.refs import DriverVersionRef
from tests.e2e.pages._dom import wait_for_dialog_open

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page


class DriversListPage:
    """Drivers list + the Load Driver drawer (remote Git flow)."""

    def __init__(self, page: Page) -> None:
        self._page = page

    async def goto(self) -> None:
        await self._page.goto("/drivers")

    def driver_group_logo(self, driver_name: str) -> Locator:
        """The logo in the grouped-view header of ``driver_name``."""
        return self._page.locator(
            f'[data-testid=driver-group][data-driver-name="{driver_name}"] '
            "[data-testid=driver-logo]"
        )

    async def open(self) -> None:
        """Navigate to the list and wait for at least one group to render."""
        await self._page.goto("/drivers")
        await self._page.locator("[data-testid=driver-group]").first.wait_for()

    def group(self, driver_name: str) -> "Locator":
        """The card for one application driver."""
        return self._page.locator(
            f"[data-testid=driver-group][data-driver-name={driver_name!r}]"
        )

    async def visible_version_count(self, driver_name: str) -> int:
        """How many version rows the group renders (the cap's observable effect)."""
        return (
            await self.group(driver_name)
            .locator("[data-testid=driver-version-row]")
            .count()
        )

    async def versions_loaded_label(self, driver_name: str) -> str:
        """Text of the group header's "N versions loaded" counter."""
        return (
            await self.group(driver_name)
            .locator("[data-testid=driver-group-count]")
            .inner_text()
        ).strip()

    async def older_versions_label(self, driver_name: str) -> str | None:
        """Text of the "N older versions" strip, or None when the cap did not fire."""
        strip = self.group(driver_name).locator("[data-testid=driver-older-versions]")
        if await strip.count() == 0:
            return None
        return (await strip.inner_text()).strip()

    async def open_driver_from_older_versions(self, driver_name: str) -> str:
        """Click the truncation strip; returns the driver id it navigated to."""
        await (
            self.group(driver_name)
            .locator("[data-testid=driver-older-versions]")
            .click()
        )
        detail_root = self._page.locator("[data-testid=driver-detail]").first
        await detail_root.wait_for()
        driver_id = await detail_root.get_attribute("data-driver-id")
        if not driver_id:
            raise ScenarioActionError(
                "driver detail page rendered without data-driver-id"
            )
        return driver_id

    async def load_remote_version(
        self, *, git_url: str, ref: str, driver_directory: str | None = None
    ) -> DriverVersionRef:
        """Drive the Load Driver drawer (Git tab) and return the new version ref.

        The drawer opens from the ``Load driver`` action on ``/drivers``. There
        is no scan/preview step, so submitting loads the version directly; on
        success the drawer closes, a toast confirms the load, and the app
        navigates to ``/drivers/<applicationDriverId>?version=<id>`` — the driver
        detail page — whose root carries the ids we need as data attributes.
        """
        await self._page.goto("/drivers")

        # Open the drawer (header action). Only one "Load driver" trigger exists
        # until the drawer mounts its own footer submit button.
        await self._page.get_by_role("button", name="Load driver").first.click()
        await wait_for_dialog_open(
            self._page.get_by_role("dialog", name="Load a driver")
        )

        # Git repository is the default tab.
        await self._page.locator("#repositoryUrl").fill(git_url)
        await self._page.locator("#branch").fill(ref)
        if driver_directory is not None:
            await self._page.locator("#driverDirectory").fill(driver_directory)

        # The footer submit is the only button bound to the drawer form.
        await self._page.locator("button[form=load-driver-form]").click()

        # Auto-navigation to the detail page is the success signal (the wait
        # absorbs the load mutation resolving and the redirect).
        detail_root = self._page.locator("[data-testid=driver-detail]").first
        await detail_root.wait_for()

        application_driver_id = await detail_root.get_attribute("data-driver-id")
        if not application_driver_id:
            raise ScenarioActionError(
                "driver detail page rendered without data-driver-id"
            )
        driver_name = await detail_root.get_attribute("data-driver-name")
        if not driver_name:
            raise ScenarioActionError(
                "driver detail page rendered without data-driver-name"
            )
        version_id = await detail_root.get_attribute("data-version-id")
        if not version_id:
            raise ScenarioActionError(
                "driver detail page rendered without data-version-id"
            )
        version = await detail_root.get_attribute("data-version-label")
        if not version:
            raise ScenarioActionError(
                "driver detail page rendered without data-version-label"
            )

        # Validate the URL matches the detail root, to catch layout surprises
        # during refactors (query string carries ?version=, so compare path).
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
