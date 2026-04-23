"""Page object for the settings area (``/settings``)."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from tests.e2e.drivers.refs import ClusterRef

if TYPE_CHECKING:
    from playwright.async_api import Page


class SettingsPage:
    """Settings nav + Clusters sub-page (create cluster)."""

    def __init__(self, page: Page) -> None:
        self._page = page

    async def open_clusters_tab(self) -> None:
        raise NotImplementedError  # T018

    async def create_cluster(self, *, name: str, config: dict[str, Any]) -> ClusterRef:
        raise NotImplementedError  # T018
