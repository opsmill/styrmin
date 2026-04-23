"""Page objects for the Environments area.

Covers the environments list, create-environment dialog, and the
environment detail page (BSL assignment, deploy entry point).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, TYPE_CHECKING

from playwright.async_api import expect

from tests.e2e.drivers.errors import ScenarioActionError, ScenarioTimeout
from tests.e2e.drivers.refs import EnvironmentRef

if TYPE_CHECKING:
    from playwright.async_api import Page


class EnvironmentsListPage:
    def __init__(self, page: Page) -> None:
        self._page = page

    async def goto(self) -> None:
        await self._page.goto("/")
        await expect(
            self._page.get_by_role("heading", name="Environments")
        ).to_be_visible()

    async def create_environment(
        self, *, name: str, cluster_id: str, config: dict[str, Any]
    ) -> EnvironmentRef:
        """Drive the CreateEnvironmentDialog to create an environment.

        ``cluster_id`` selects the cluster in the dropdown. The dropdown
        renders option labels as cluster *names*, so the caller must have
        populated the data-cluster-id attribute via a preceding
        ``SettingsPage.create_cluster`` or similar.
        """
        await self.goto()
        await self._page.get_by_role("button", name="New Environment").click()
        dialog = self._page.get_by_role("dialog", name="Create Environment")
        await dialog.wait_for()

        await dialog.locator("#env-name").fill(name)

        # The cluster select renders items by cluster name; map cluster_id
        # back to a name by reading the list on the settings page would be
        # expensive, so instead we open the dropdown and match on the
        # SelectItem's value attribute (the cluster id).
        trigger = dialog.get_by_role("combobox")
        await trigger.click()
        option = self._page.locator(f"[role=option][data-value='{cluster_id}']").first
        if await option.count() == 0:
            # Fallback: Radix doesn't expose value on the option itself —
            # select by position with the first option if only one cluster.
            option = self._page.get_by_role("option").first
        await option.click()

        if _needs_advanced(config):
            await dialog.get_by_role("button", name="Advanced Configuration").click()
            if config.get("ingress_class"):
                await dialog.locator("#env-ingress-class").fill(config["ingress_class"])
            if config.get("db_size"):
                await dialog.locator("#env-db-size").fill(config["db_size"])
            if config.get("fqdn_suffix"):
                await dialog.locator("#env-fqdn-suffix").fill(config["fqdn_suffix"])
            ip_list = config.get("ip_whitelist")
            if ip_list:
                await dialog.locator("#env-ip-whitelist").fill(
                    ", ".join(ip_list) if isinstance(ip_list, list) else str(ip_list)
                )
            di = config.get("dedicated_ingress")
            if di:
                await dialog.locator("#env-dedicated-ingress").click()
                if di.get("implementation"):
                    await dialog.locator("#env-di-impl").fill(di["implementation"])
                if di.get("type"):
                    await dialog.locator("#env-di-type").fill(di["type"])

        await dialog.get_by_role("button", name="Create", exact=True).click()
        await dialog.wait_for(state="hidden")

        card = self._page.locator(
            f"[data-testid=environment-card][data-environment-name='{name}']"
        ).first
        await card.wait_for()
        env_id = await card.get_attribute("data-environment-id")
        if not env_id:
            raise ScenarioActionError(
                f"env card for {name!r} rendered without data-environment-id"
            )
        return EnvironmentRef(id=env_id, name=name, cluster_id=cluster_id)


class EnvironmentDetailPage:
    def __init__(self, page: Page) -> None:
        self._page = page

    async def goto(self, *, environment_id: str) -> None:
        await self._page.goto(f"/environments/{environment_id}")
        root = self._page.locator(
            f"[data-testid=environment-detail][data-environment-id='{environment_id}']"
        ).first
        await root.wait_for()

    async def assign_bsl(self, *, environment_id: str, bsl_id: str) -> None:
        """Open the Parameters tab and pick the BSL from the selector."""
        await self.goto(environment_id=environment_id)
        await self._page.get_by_role("button", name="Parameters", exact=True).click()
        selector = self._page.locator("[data-testid=bsl-selector]").first
        await selector.wait_for()
        await selector.get_by_role("combobox").click()
        option = self._page.locator(f"[role=option][data-value='{bsl_id}']").first
        if await option.count() == 0:
            raise ScenarioActionError(
                f"BSL {bsl_id!r} is not listed on environment {environment_id!r}"
            )
        await option.click()

        # Wait until the detail page's data-bsl-id reflects the assignment.
        root = self._page.locator(
            f"[data-testid=environment-detail][data-environment-id='{environment_id}']"
        ).first
        deadline = time.time() + 15.0
        while time.time() < deadline:
            current = await root.get_attribute("data-bsl-id")
            if current == bsl_id:
                return
            await asyncio.sleep(0.5)
        raise ScenarioTimeout(
            f"BSL assignment did not reflect within 15s on environment {environment_id!r}"
        )


def _needs_advanced(config: dict[str, Any]) -> bool:
    keys = (
        "ingress_class",
        "db_size",
        "fqdn_suffix",
        "ip_whitelist",
        "dedicated_ingress",
    )
    return any(config.get(k) for k in keys)
