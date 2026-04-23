"""Page objects for the Environments area.

Covers the environments list, create-environment dialog, and the
environment detail page (BSL assignment, deploy entry point).
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from tests.e2e.drivers.refs import EnvironmentRef

if TYPE_CHECKING:
    from playwright.async_api import Page

    from tests.e2e.pages.deploy_form import DeployFormPage


class EnvironmentsListPage:
    """``/environments`` — list + create-environment dialog."""

    def __init__(self, page: Page) -> None:
        self._page = page

    async def create_environment(
        self, *, name: str, cluster_id: str, config: dict[str, Any]
    ) -> EnvironmentRef:
        raise NotImplementedError  # T015

    async def open_environment(self, *, environment_id: str) -> EnvironmentDetailPage:
        raise NotImplementedError  # T015


class EnvironmentDetailPage:
    """``/environments/$id`` — BSL assign/unassign, deploy entry point."""

    def __init__(self, page: Page) -> None:
        self._page = page

    async def assign_bsl(self, *, bsl_id: str) -> None:
        raise NotImplementedError  # T016

    async def open_deploy_form(self) -> DeployFormPage:
        raise NotImplementedError  # T016
