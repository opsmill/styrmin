"""Page objects for the Environments area.

Covers the environments list, create-environment dialog, and the
environment detail page (BSL assignment, deploy entry point).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, expect

from tests.e2e.drivers.errors import ScenarioActionError, ScenarioTimeout
from tests.e2e.drivers.refs import EnvironmentRef

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page


class EnvironmentsListPage:
    def __init__(self, page: Page) -> None:
        self._page = page

    async def goto(self) -> None:
        await self._page.goto("/")
        # First navigation after a fresh styrmin deployment can be slow
        # (frontend served by the same pod that's still warming caches);
        # the Playwright default of 5s is tight. 15s absorbs the jitter
        # without silently hiding a real stall.
        await expect(
            self._page.get_by_role("heading", name="Environments", exact=True)
        ).to_be_visible(timeout=15_000)

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

    # ------------------------------------------------------------------
    # Deletion-aware list helpers (spec 008)
    # ------------------------------------------------------------------

    def _row(self, deployment_id: str) -> Locator:
        return self._page.locator(
            f"[data-testid=deployment-row][data-deployment-id='{deployment_id}']"
        ).first

    async def read_row_status(self, *, deployment_id: str) -> str | None:
        """Return ``data-deployment-status`` from the row, or None if absent."""
        row = self._row(deployment_id)
        if await row.count() == 0:
            return None
        return await row.get_attribute("data-deployment-status")

    async def row_has_deleting_badge(self, *, deployment_id: str) -> bool:
        """Return True if the row shows the amber 'Deleting…' badge."""
        row = self._row(deployment_id)
        if await row.count() == 0:
            return False
        return await row.locator("[data-testid=deleting-badge]").count() > 0

    async def wait_for_row_to_vanish(
        self, *, deployment_id: str, timeout: float = 300.0
    ) -> None:
        """Block until the deployment row leaves the rendered list.

        Tombstoned deployments are hidden from the default view (FR-029)
        — once the status flips to DELETED and the urql cache invalidates,
        the row should disappear.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if await self._row(deployment_id).count() == 0:
                return
            await asyncio.sleep(2.0)
        raise ScenarioTimeout(
            f"deployment row {deployment_id} did not vanish from default "
            f"list within {timeout}s"
        )

    async def wait_for_row_to_appear(
        self, *, deployment_id: str, timeout: float = 30.0
    ) -> None:
        """Block until the deployment row is present in the rendered list."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if await self._row(deployment_id).count() > 0:
                return
            await asyncio.sleep(1.0)
        raise ScenarioTimeout(
            f"deployment row {deployment_id} did not appear within {timeout}s"
        )

    async def toggle_show_deleted(self) -> None:
        """Click the 'Show deleted' toggle in the list header."""
        await self._page.locator("[data-testid=show-deleted-toggle]").first.click()

    async def update_env_vars_via_form(
        self,
        *,
        environment_id: str,
        env_vars: dict[str, str],
    ) -> None:
        """Drive the EnvVarsForm on the Configuration tab to add env vars.

        Implements the UI side of the
        ``ScenarioDriver.update_environment_via_form`` contract for
        011-env-config-input-hardening / US4. Each ``(name, value)`` is
        appended via "Add Variable"; existing rows are left in place so
        the form's full-replacement payload preserves what was already
        persisted (matching the api_driver's read-modify-write shape).
        """
        from playwright.async_api import expect

        await self.goto(environment_id=environment_id)

        # The Configuration tab uses the project's plain-button-based
        # ``Tabs`` primitive (see frontend/src/components/ui/tabs.tsx),
        # which does NOT set ``role="tab"``. We match it as a button
        # with the exact label.
        await self._page.get_by_role("button", name="Configuration", exact=True).click()

        form = self._page.locator("[data-testid=env-vars-form]").first
        await form.wait_for(state="visible")

        # Snapshot the row count before adding so we can target the new
        # rows by index without disturbing existing values.
        existing_rows = self._page.locator("[data-testid=env-vars-form-row]")
        existing_count = await existing_rows.count()

        for offset, (name, value) in enumerate(env_vars.items()):
            await self._page.locator("[data-testid=env-vars-form-add-button]").click()
            new_row_index = existing_count + offset
            new_row = self._page.locator("[data-testid=env-vars-form-row]").nth(
                new_row_index
            )
            await new_row.locator("[data-testid=env-var-name-input]").fill(name)
            await new_row.locator("[data-testid=env-var-value-input]").fill(value)

        save = self._page.locator("[data-testid=env-vars-form-save-button]")
        await save.click()

        dialog = self._page.locator("[data-testid=redeploy-confirm-dialog]")
        await dialog.wait_for(state="visible")
        await self._page.locator("[data-testid=redeploy-confirm-redeploy]").click()
        # Dialog must close before we let the test continue — otherwise
        # the next assertion can race the still-pending mutation.
        await dialog.wait_for(state="hidden")

        # Wait for the form to settle: the Save button drops out of its
        # "Saving..." pending state. ``expect`` retries the locator's
        # text until it matches (or times out), giving the urql cache
        # invalidation room to land without a hardcoded sleep.
        await expect(save).to_have_text("Save")

    async def assign_bsl(self, *, environment_id: str, bsl_id: str) -> None:
        """Open the Parameters tab and pick the BSL from the selector."""
        await self.goto(environment_id=environment_id)
        await self._page.get_by_role("button", name="Parameters", exact=True).click()
        selector = self._page.locator("[data-testid=bsl-selector]").first
        await selector.wait_for()
        await selector.get_by_role("combobox").click()
        option = self._page.locator(f"[role=option][data-value='{bsl_id}']").first
        # Options render inside a Base UI Portal after the combobox's open-
        # animation kicks in; `count()` right after the click can race the
        # mount. `wait_for` lets Playwright retry until the option attaches
        # (or times out with a clearer signal than a silent `count == 0`).
        try:
            await option.wait_for(state="visible", timeout=5_000)
        except PlaywrightTimeoutError as exc:
            raise ScenarioActionError(
                f"BSL {bsl_id!r} is not listed on environment {environment_id!r}"
            ) from exc
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
