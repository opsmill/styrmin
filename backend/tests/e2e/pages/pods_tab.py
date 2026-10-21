"""Page object for the Pods tab on the deployment detail page (spec 012).

Route: ``/environments/$environmentId/deployments/$deploymentId`` with the
``Pods`` tab selected. The tab is mounted alongside Overview / Parameters /
Backups / Timeline in ``frontend/src/pages/deployments/DeploymentDetailPage.tsx``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.async_api import expect

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page


class PodsTabPage:
    """Pods tab — sections, expand, kubectl Copy helpers."""

    def __init__(self, page: Page) -> None:
        self._page = page

    async def open(self) -> None:
        """Click the Pods tab in the deployment-detail tab strip."""
        await self._page.get_by_role("button", name="Pods", exact=True).click()
        # Wait for the tab heading to render so subsequent locators don't
        # latch onto the still-mounted previous tab.
        await self._page.get_by_role("heading", name="Pods", level=2).wait_for()

    def pod_rows(self) -> Locator:
        """Locator for all pod rows currently rendered on the tab."""
        return self._page.locator('[data-testid="pod-row"]')

    async def wait_for_at_least_one_running_pod(self, *, timeout: float = 120.0) -> str:
        """Wait until at least one pod row renders with phase RUNNING.

        Healthy sections start collapsed (see ``shouldSectionAutoExpand``
        on the frontend), so pod rows are not mounted until the section
        opens. This waits for a section to advertise a RUNNING pod via
        its phase-chip summary, expands that section if it isn't open,
        and then resolves the pod row inside it.

        Returns the pod name (``data-pod-name`` attribute) of the first such
        row, so the caller can build per-pod assertions.
        """
        timeout_ms = int(timeout * 1000)
        section = self._page.locator(
            '[data-testid="pod-section"]:has([data-testid="phase-chip-running"])'
        ).first
        await expect(section).to_be_visible(timeout=timeout_ms)
        if await section.get_attribute("data-open") != "true":
            await section.locator("button").first.click()
            await expect(section).to_have_attribute("data-open", "true", timeout=5_000)
        running_rows = section.locator(
            '[data-testid="pod-row"]:has([data-pod-phase="RUNNING"])'
        )
        await expect(running_rows.first).to_be_visible(timeout=timeout_ms)
        name = await running_rows.first.get_attribute("data-pod-name")
        assert name, "pod row rendered without a data-pod-name attribute"
        return name

    def section(self, component: str) -> Locator:
        """Locator for the section of the declared component ``component``."""
        return self._page.locator(
            f'[data-testid="pod-section"][data-variant="declared"][data-component="{component}"]'
        )

    async def expand_section(self, component: str) -> None:
        """Open the section of the declared component ``component`` and scroll it to the top of the page."""
        section = self.section(component)
        await expect(section).to_be_visible()
        if await section.get_attribute("data-open") != "true":
            await section.locator("button").first.click()
            await expect(section).to_have_attribute("data-open", "true", timeout=5_000)
        await section.evaluate(
            "section => section.scrollIntoView({block: 'start', behavior: 'smooth'})"
        )

    async def wait_for_running_pods(
        self, component: str, *, count: int, timeout: float = 120.0
    ) -> list[str]:
        """Wait until the open section of ``component`` lists exactly ``count`` pods, all RUNNING, and return
        their names. The tab refreshes every 10 s, so a pod that an update replaced leaves the list."""
        rows = self.section(component).locator('[data-testid="pod-row"]')
        running = rows.filter(has=self._page.locator('[data-pod-phase="RUNNING"]'))
        timeout_ms = int(timeout * 1000)
        await expect(rows).to_have_count(count, timeout=timeout_ms)
        await expect(running).to_have_count(count, timeout=timeout_ms)
        names = [
            await row.get_attribute("data-pod-name") for row in await running.all()
        ]
        if not all(names):
            raise AssertionError("pod row rendered without a data-pod-name attribute")
        return [name for name in names if name]

    async def show_pod(self, pod_name: str) -> str:
        """Expand the row of ``pod_name`` when it is collapsed, scroll it to the middle of the page and return
        its text, which lists each container with its image."""
        row = self._page.locator(f'[data-testid="pod-row"][data-pod-name="{pod_name}"]')
        toggle = row.get_by_role("button", name=pod_name, exact=False)
        if await toggle.get_attribute("aria-expanded") != "true":
            await toggle.click()
            await expect(toggle).to_have_attribute("aria-expanded", "true")
        await row.evaluate(
            "row => row.scrollIntoView({block: 'center', behavior: 'smooth'})"
        )
        return await row.inner_text()

    async def expand_pod(self, pod_name: str) -> None:
        """Click the pod row identified by ``pod_name`` to expand it."""
        row = self._page.locator(f'[data-pod-name="{pod_name}"]')
        await row.get_by_role("button", name=pod_name, exact=False).click()

    async def open_commands_section(self) -> None:
        """Open the (collapsed-by-default) Commands collapsible."""
        await self._page.get_by_role("button", name="Commands", exact=False).click()
        # The first Copy button only enters the DOM once the panel mounts.
        await self._page.get_by_test_id("copy-logs-button").wait_for()

    async def click_copy_logs(self) -> None:
        await self._page.get_by_test_id("copy-logs-button").click()

    async def read_clipboard(self) -> str:
        """Read the browser clipboard. Requires ``clipboard-read`` permission
        granted on the page's context — call ``grant_clipboard_permissions``
        before driving any Copy buttons.
        """
        return await self._page.evaluate("() => navigator.clipboard.readText()")

    async def grant_clipboard_permissions(self) -> None:
        """Grant clipboard-read/write to the page's browser context.

        Chromium denies clipboard reads by default; without this the Copy
        button still works but ``read_clipboard()`` raises.
        """
        await self._page.context.grant_permissions(
            ["clipboard-read", "clipboard-write"]
        )
