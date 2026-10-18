"""Page object for the network device list of Infrahub 1.11 (``/objects/InfraDevice``), used by the demos only."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.async_api import expect

from tests.e2e.pages._dom import enter_text, submit_dialog

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page

DEVICES_PATH = "/objects/InfraDevice"
# Infrahub's initial admin account, which both Infrahub drivers keep. Never print the password.
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "infrahub"  # noqa: S105
TIMEOUT_MS = 30_000
# The list's footer, e.g. "2 counts", at the end of its rendered text.
_COUNT_PATTERN = re.compile(r"(?<!\w)(\d+)\s*counts?\s*$")


def footer_count(text: str) -> int | None:
    """Return the number of devices the list's footer shows at the end of ``text``, or ``None``."""
    match = _COUNT_PATTERN.search(text)
    return int(match.group(1)) if match else None


class InfrahubDevicesPage:
    """Read, add and delete network devices in the Infrahub web UI."""

    def __init__(self, page: Page, *, keystroke_delay_ms: int | None = None) -> None:
        self._page = page
        self._keystroke_delay_ms = keystroke_delay_ms

    async def log_in(
        self,
        base_url: str,
        *,
        username: str = ADMIN_USERNAME,
        password: str = ADMIN_PASSWORD,
    ) -> None:
        """Log in at ``/login``; ends when Infrahub leaves the login page."""
        await self._page.goto(f"{base_url}/login")
        await enter_text(
            self._page.get_by_label("Username"),
            username,
            keystroke_delay_ms=self._keystroke_delay_ms,
        )
        await enter_text(
            self._page.get_by_label("Password"),
            password,
            keystroke_delay_ms=self._keystroke_delay_ms,
        )
        await self._page.get_by_role("button", name="Log in", exact=True).click()
        await self._page.wait_for_url(
            lambda url: not url.rstrip("/").endswith("/login"), timeout=TIMEOUT_MS
        )

    async def goto(self, base_url: str) -> None:
        """Open the device list and wait until it shows as many rows as its footer counts."""
        await self._page.goto(f"{base_url}{DEVICES_PATH}")
        await expect(self._items).to_contain_text(
            _COUNT_PATTERN, use_inner_text=True, timeout=TIMEOUT_MS
        )
        # The footer can show the count a moment before the rows render.
        total = footer_count(await self._items.inner_text())
        await expect(self._items.get_by_test_id("data-table-row")).to_have_count(
            total or 0, timeout=TIMEOUT_MS
        )

    async def list_device_names(self) -> list[str]:
        return await self._device_links.all_inner_texts()

    async def add_device(self, name: str) -> None:
        """Create a device named ``name`` in the side panel; ends when its row appears."""
        await self._page.get_by_test_id("create-object-button").click()
        panel = self._page.get_by_role("dialog").filter(
            has=self._page.get_by_role("heading", name="Create Network device")
        )
        await enter_text(
            panel.get_by_role("textbox", name="Name"),
            name,
            keystroke_delay_ms=self._keystroke_delay_ms,
        )
        await submit_dialog(panel, button="Save", timeout=TIMEOUT_MS)
        await expect(self._device_link(name)).to_be_visible(timeout=TIMEOUT_MS)

    async def delete_device(self, name: str) -> None:
        """Delete device ``name`` from its row menu; ends when its row disappears."""
        await self._page.get_by_test_id(f"actions-cell-{name}").click()
        await self._page.get_by_role("menuitem", name="Delete", exact=True).click()
        await self._page.get_by_test_id("modal-delete-confirm").click()
        await expect(self._device_link(name)).to_have_count(0, timeout=TIMEOUT_MS)

    @property
    def _items(self) -> Locator:
        return self._page.get_by_test_id("object-items")

    @property
    def _device_links(self) -> Locator:
        # The identifier cell holds the row's checkbox and the link to the device.
        return (
            self._items.get_by_test_id("data-table-row")
            .get_by_test_id("identifier-cell")
            .get_by_role("link")
        )

    def _device_link(self, name: str) -> Locator:
        return self._items.get_by_test_id("identifier-cell").get_by_role(
            "link", name=name, exact=True
        )
