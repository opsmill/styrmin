"""DOM-reading helpers shared by the Playwright page objects."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.drivers.errors import ScenarioActionError

if TYPE_CHECKING:
    from playwright.async_api import Locator


async def required_attr(locator: Locator, attr: str, *, context: str) -> str:
    """Read ``attr`` from ``locator`` and raise if absent or empty.

    Prevents a frontend test-hook removal from surfacing as a cryptic
    downstream assertion; the missing attribute is reported at the boundary.
    """
    value = await locator.get_attribute(attr)
    if not value:
        raise ScenarioActionError(
            f"{context} rendered without {attr} attribute "
            "(frontend test-hook may have been removed or renamed)"
        )
    return value
