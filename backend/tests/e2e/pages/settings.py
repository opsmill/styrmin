"""Page object for the clusters area (``/clusters``).

Originally lived under ``/settings`` — the cluster surface moved out of
Settings into a dedicated top-level page when multi-cluster support was
introduced. The page object class is still called ``SettingsPage`` so
downstream drivers don't have to know about the move; only the route
and the heading wait changed.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from playwright.async_api import expect

from tests.e2e.drivers.errors import ScenarioActionError
from tests.e2e.drivers.refs import ClusterRef

if TYPE_CHECKING:
    from playwright.async_api import Page


class SettingsPage:
    def __init__(self, page: Page) -> None:
        self._page = page

    async def goto(self) -> None:
        await self._page.goto("/clusters")
        try:
            await expect(
                self._page.get_by_role("heading", name="Clusters")
            ).to_be_visible()
        except AssertionError:
            # Surface what the browser is actually showing — most
            # auth-misconfiguration paths land us on /login or on the
            # AuthProvider "Loading..." gate, and the raw assertion error
            # ("element(s) not found") doesn't say which.
            url = self._page.url
            body_text = await self._page.locator("body").inner_text()
            print(f"SettingsPage.goto() failed at url={url!r}")
            print(
                f"--- body text (truncated) ---\n{body_text[:1000]}\n--- end body ---"
            )
            raise

    async def create_cluster(self, *, name: str, config: dict[str, Any]) -> ClusterRef:
        """Create a cluster by driving the CreateClusterDialog form.

        The Clusters page only shows the "New Cluster" button when no
        cluster exists yet. Callers must ensure this is the first cluster
        on the instance (``styrmin_resources`` currently enforces this).
        """
        await self.goto()
        trigger = self._page.get_by_role("button", name="New Cluster")
        await trigger.click()
        dialog = self._page.get_by_role("dialog", name="Create Cluster")
        await dialog.wait_for()

        await dialog.locator("#cluster-name").fill(name)

        if _needs_advanced(config):
            await dialog.get_by_role("button", name="Advanced Configuration").click()
            if config.get("ingress_class"):
                await dialog.locator("#cluster-ingress-class").fill(
                    config["ingress_class"]
                )
            if config.get("fqdn_suffix"):
                await dialog.locator("#cluster-fqdn-suffix").fill(config["fqdn_suffix"])
            if config.get("runtime_class"):
                await dialog.locator("#cluster-runtime-class").fill(
                    config["runtime_class"]
                )
            if config.get("external_url_scheme"):
                await dialog.locator("#cluster-external-url-scheme").select_option(
                    config["external_url_scheme"]
                )
            if config.get("external_url_port") is not None:
                await dialog.locator("#cluster-external-url-port").fill(
                    str(config["external_url_port"])
                )
            if config.get("external_dns_endpoints_type"):
                await dialog.locator(
                    "#cluster-external-dns-endpoints-type"
                ).select_option(config["external_dns_endpoints_type"])
            di = config.get("dedicated_ingress")
            if di:
                # Base UI's <Checkbox> puts the id on a hidden <input>
                # (aria-hidden, tabindex=-1) underneath the visible button.
                # Clicking the hidden input is intercepted by the dialog
                # backdrop, so drive it through the associated <label>.
                await dialog.locator("label[for='cluster-dedicated-ingress']").click()
                if di.get("implementation"):
                    await dialog.locator("#cluster-di-impl").fill(di["implementation"])
                if di.get("type"):
                    await dialog.locator("#cluster-di-type").select_option(di["type"])
            ss = config.get("standard_storage")
            if ss:
                await dialog.locator("label[for='cluster-standard-storage']").click()
                if ss.get("storage_class"):
                    await dialog.locator("#cluster-sc").fill(ss["storage_class"])

        await dialog.get_by_role("button", name="Create", exact=True).click()
        await dialog.wait_for(state="hidden")

        # After creation the Clusters page refreshes and renders the cluster
        # card with a stable data-cluster-id attribute.
        card = self._page.locator(
            f"[data-testid=cluster-card][data-cluster-name='{name}']"
        ).first
        await card.wait_for()
        cluster_id = await card.get_attribute("data-cluster-id")
        if not cluster_id:
            raise ScenarioActionError(
                f"cluster card for {name!r} rendered without data-cluster-id"
            )
        return ClusterRef(id=cluster_id, name=name)


def _needs_advanced(config: dict[str, Any]) -> bool:
    keys = (
        "ingress_class",
        "fqdn_suffix",
        "runtime_class",
        "external_url_scheme",
        "external_url_port",
        "external_dns_endpoints_type",
        "dedicated_ingress",
        "standard_storage",
    )
    return any(config.get(k) is not None and config.get(k) != "" for k in keys)


class BackupStorageLocationsListPage:
    """``/backup-storage-locations`` — list + create-BSL dialog."""

    def __init__(self, page: Page) -> None:
        self._page = page

    async def goto(self) -> None:
        await self._page.goto("/backup-storage-locations")

    async def create(
        self,
        *,
        name: str,
        endpoint: str,
        bucket: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> str:
        """Open the dialog, fill, submit, and return the new BSL's id."""
        await self.goto()
        await self._page.get_by_role("button", name="New Storage Location").click()
        dialog = self._page.get_by_role("dialog", name="Create Backup Storage Location")
        await dialog.wait_for()
        await dialog.locator("#bsl-name").fill(name)
        await dialog.locator("#bsl-endpoint").fill(endpoint)
        await dialog.locator("#bsl-bucket").fill(bucket)
        await dialog.locator("#bsl-region").fill(region)
        await dialog.locator("#bsl-access-key").fill(access_key_id)
        await dialog.locator("#bsl-secret-key").fill(secret_access_key)
        await dialog.get_by_role("button", name="Create", exact=True).click()
        await dialog.wait_for(state="hidden")

        card = self._page.locator(
            f"[data-testid=bsl-card][data-bsl-name='{name}']"
        ).first
        await card.wait_for()
        bsl_id = await card.get_attribute("data-bsl-id")
        if not bsl_id:
            raise ScenarioActionError(
                f"BSL card for {name!r} rendered without data-bsl-id"
            )
        return bsl_id
