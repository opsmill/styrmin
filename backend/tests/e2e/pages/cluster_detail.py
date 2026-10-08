"""Page object for the cluster detail page (``/clusters/$clusterId``).

Each configuration area renders as a ``<section>`` labelled by its heading
(``ClusterConfiguration.tsx``), so sections resolve by ARIA ``region`` name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.async_api import expect

if TYPE_CHECKING:
    from playwright.async_api import Page


class ClusterDetailPage:
    def __init__(self, page: Page) -> None:
        self._page = page

    async def goto(self, *, cluster_id: str) -> None:
        await self._page.goto(f"/clusters/{cluster_id}")
        await expect(
            self._page.get_by_role("heading", name="Configuration", level=2)
        ).to_be_visible()

    async def read_section(self, name: str) -> str:
        """Return the rendered text of one configuration section."""
        section = self._page.get_by_role("region", name=name, exact=True)
        await expect(section).to_be_visible()
        return await section.inner_text()
