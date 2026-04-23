"""Page object for the deployment detail view.

Route: ``/environments/$environmentId/deployments/$deploymentId``.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from playwright.async_api import expect

from tests.e2e.drivers.errors import ScenarioActionError, ScenarioTimeout
from tests.e2e.drivers.refs import BackupRef, RestoreRef, TimelineEntry

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page


# StatusBadge renders these labels for the corresponding backend statuses.
_STATUS_LABELS = {
    "running": "Running",
    "pending": "Pending",
    "in_progress": "In Progress",
    "completed": "Complete",
    "failed": "Failed",
}


async def _required_attr(locator: Locator, attr: str, *, context: str) -> str:
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


class DeploymentDetailPage:
    """Deployment detail — status, Upgrade, Timeline tab, Backups tab, Restores tab."""

    def __init__(self, page: Page) -> None:
        self._page = page

    async def goto(self, *, environment_id: str, deployment_id: str) -> None:
        await self._page.goto(
            f"/environments/{environment_id}/deployments/{deployment_id}"
        )

    async def wait_for_status(self, *, expected: str, timeout: float = 300.0) -> None:
        """Wait for the header StatusBadge to render *expected*.

        Must target the deployment's header badge, not the per-task badges
        rendered under "Recent Timeline" — the "Create Instance" task
        reaches ``Running`` long before the deployment does, so matching
        any ``Running`` on the page would succeed prematurely.
        """
        want_label = _STATUS_LABELS.get(expected.lower(), expected)
        header_badge = self._page.locator("h1 + *").first
        try:
            await expect(header_badge).to_contain_text(
                want_label, timeout=int(timeout * 1000)
            )
        except AssertionError as exc:
            raise ScenarioTimeout(
                f"deployment did not reach status {want_label!r} within {timeout}s"
            ) from exc

    async def open_upgrade_dialog(self) -> None:
        """Open the Upgrade Deployment dialog from the detail header."""
        await self._page.get_by_role("button", name="Upgrade", exact=True).click()
        await self._page.get_by_role("dialog", name="Upgrade Deployment").wait_for()

    async def confirm_upgrade(self, *, version: str) -> None:
        """Fill the New Version input and click Upgrade inside the dialog."""
        dialog = self._page.get_by_role("dialog", name="Upgrade Deployment")
        await dialog.get_by_label("New Version").fill(version)
        await dialog.get_by_role("button", name="Upgrade", exact=True).click()
        # Dialog closes on success; treat its disappearance as the signal.
        await dialog.wait_for(state="hidden")

    async def read_timeline(self) -> list[TimelineEntry]:
        """Click the Timeline tab and read every entry from the rendered DOM.

        Relies on the ``data-task-*`` attributes attached to
        ``DeploymentTimeline`` so we don't have to reverse-map the
        human-readable type labels the UI shows to users.
        """
        # The shared Tabs component renders each tab as a plain <button>,
        # not role="tab" — target by role=button + accessible name.
        await self._page.get_by_role("button", name="Timeline", exact=True).click()
        # Wait for either at least one entry OR the "No operations" placeholder
        entries_loc = self._page.locator("[data-testid=timeline-entry]")
        placeholder = self._page.get_by_text(
            "No operations have been recorded for this deployment."
        )
        await expect(entries_loc.first.or_(placeholder)).to_be_visible()

        count = await entries_loc.count()
        results: list[TimelineEntry] = []
        for i in range(count):
            row = entries_loc.nth(i)
            task_id = await _required_attr(
                row, "data-task-id", context="timeline entry"
            )
            task_type = await _required_attr(
                row, "data-task-type", context=f"timeline entry {task_id}"
            )
            task_status = await _required_attr(
                row, "data-task-status", context=f"timeline entry {task_id}"
            )
            created_on = await row.get_attribute("data-created-on")
            application_version = await row.get_attribute("data-application-version")
            results.append(
                TimelineEntry(
                    task_id=task_id,
                    task_type=task_type,
                    task_status=task_status,
                    application_version=application_version or None,
                    created_on=created_on or None,
                )
            )
        return results

    async def read_instance_id(self) -> str | None:
        """Read the deployment's instance id from the detail page attributes."""
        root = self._page.locator("[data-testid=deployment-detail]").first
        await root.wait_for()
        value = await root.get_attribute("data-instance-id")
        return value or None

    async def read_application_version(self) -> str | None:
        """Read the deployment's application version from the page attributes."""
        root = self._page.locator("[data-testid=deployment-detail]").first
        await root.wait_for()
        value = await root.get_attribute("data-application-version")
        return value or None

    async def open_backups_tab(self) -> None:
        await self._page.get_by_role("button", name="Backups", exact=True).click()

    async def create_backup(self) -> BackupRef:
        """Click 'Create Backup' and return the newly-added row as a ref."""
        await self.open_backups_tab()

        existing_ids: set[str] = set()
        for i in range(await self._page.locator("[data-testid=backup-row]").count()):
            row = self._page.locator("[data-testid=backup-row]").nth(i)
            existing_ids.add(
                await _required_attr(row, "data-backup-id", context="backup row")
            )

        await self._page.get_by_role("button", name="Create Backup").click()

        async def _first_new_row() -> BackupRef | None:
            rows = self._page.locator("[data-testid=backup-row]")
            for i in range(await rows.count()):
                row = rows.nth(i)
                row_id = await _required_attr(
                    row, "data-backup-id", context="backup row"
                )
                if row_id in existing_ids:
                    continue
                return BackupRef(
                    id=row_id,
                    name=await _required_attr(
                        row, "data-backup-name", context=f"backup row {row_id}"
                    ),
                    status=await _required_attr(
                        row, "data-backup-status", context=f"backup row {row_id}"
                    ),
                )
            return None

        deadline = time.time() + 60.0
        while time.time() < deadline:
            ref = await _first_new_row()
            if ref is not None:
                return ref
            await asyncio.sleep(1.0)
        raise ScenarioTimeout("create_backup: new backup row did not appear within 60s")

    async def wait_for_backup_status(
        self, *, backup_id: str, terminal_statuses: tuple[str, ...], max_wait: float
    ) -> BackupRef:
        """Poll the backup row until ``data-backup-status`` is terminal."""
        deadline = time.time() + max_wait
        row = self._page.locator(
            f"[data-testid=backup-row][data-backup-id='{backup_id}']"
        ).first
        context = f"backup row {backup_id}"
        while time.time() < deadline:
            if await row.count() > 0:
                status = await _required_attr(
                    row, "data-backup-status", context=context
                )
                if status in terminal_statuses:
                    name = await _required_attr(
                        row, "data-backup-name", context=context
                    )
                    return BackupRef(id=backup_id, name=name, status=status)
            await asyncio.sleep(2.0)
        raise ScenarioTimeout(
            f"backup {backup_id} did not reach a terminal status within {max_wait}s"
        )

    async def read_backup(self, *, backup_id: str) -> BackupRef | None:
        """Read a backup row by id, or return ``None`` if the row is absent."""
        row = self._page.locator(
            f"[data-testid=backup-row][data-backup-id='{backup_id}']"
        ).first
        if await row.count() == 0:
            return None
        context = f"backup row {backup_id}"
        return BackupRef(
            id=backup_id,
            name=await _required_attr(row, "data-backup-name", context=context),
            status=await _required_attr(row, "data-backup-status", context=context),
        )

    async def delete_backup(self, *, backup_id: str) -> None:
        """Click the row's Delete, then confirm in the dialog."""
        await self.open_backups_tab()
        row = self._page.locator(
            f"[data-testid=backup-row][data-backup-id='{backup_id}']"
        ).first
        await row.get_by_role("button", name="Delete", exact=True).click()
        dialog = self._page.get_by_role("dialog", name="Delete Backup")
        await dialog.wait_for()
        await dialog.get_by_role("button", name="Delete", exact=True).click()
        await dialog.wait_for(state="hidden")
        # Row should disappear after successful delete.
        await row.wait_for(state="detached", timeout=30_000)

    async def create_restore(
        self, *, backup_id: str, target_namespace: str
    ) -> RestoreRef:
        """Click the row's Restore, confirm in the dialog, return the new restore ref.

        ``target_namespace`` is a readOnly input on the UI (the dialog
        derives it from the deployment context). Scenarios still pass it so
        the same argument list works against both entrypoints — we verify
        the displayed value matches so API/UI results stay equivalent.
        """
        await self.open_backups_tab()
        row = self._page.locator(
            f"[data-testid=backup-row][data-backup-id='{backup_id}']"
        ).first
        await row.get_by_role("button", name="Restore", exact=True).click()
        dialog = self._page.get_by_role("dialog", name="Restore Backup")
        await dialog.wait_for()

        shown_namespace = await dialog.get_by_label("Target Namespace").input_value()
        if shown_namespace != target_namespace:
            raise ScenarioActionError(
                f"Restore dialog shows target namespace {shown_namespace!r} but "
                f"scenario expected {target_namespace!r}"
            )

        # Existing restore ids so we can pick the new one.
        existing_ids: set[str] = set()
        restore_rows = self._page.locator("[data-testid=restore-row]")
        for i in range(await restore_rows.count()):
            existing_ids.add(
                await _required_attr(
                    restore_rows.nth(i), "data-restore-id", context="restore row"
                )
            )

        await dialog.get_by_role("button", name="Restore", exact=True).click()
        await dialog.wait_for(state="hidden")

        deadline = time.time() + 60.0
        while time.time() < deadline:
            rows = self._page.locator("[data-testid=restore-row]")
            for i in range(await rows.count()):
                r = rows.nth(i)
                rid = await _required_attr(r, "data-restore-id", context="restore row")
                if rid in existing_ids:
                    continue
                return RestoreRef(
                    id=rid,
                    status=await _required_attr(
                        r, "data-restore-status", context=f"restore row {rid}"
                    ),
                )
            await asyncio.sleep(1.0)
        raise ScenarioTimeout(
            "create_restore: new restore row did not appear within 60s"
        )

    async def wait_for_restore_status(
        self, *, restore_id: str, terminal_statuses: tuple[str, ...], max_wait: float
    ) -> RestoreRef:
        """Poll the restore row until ``data-restore-status`` is terminal."""
        deadline = time.time() + max_wait
        row = self._page.locator(
            f"[data-testid=restore-row][data-restore-id='{restore_id}']"
        ).first
        context = f"restore row {restore_id}"
        while time.time() < deadline:
            if await row.count() > 0:
                status = await _required_attr(
                    row, "data-restore-status", context=context
                )
                if status in terminal_statuses:
                    return RestoreRef(id=restore_id, status=status)
            await asyncio.sleep(2.0)
        raise ScenarioTimeout(
            f"restore {restore_id} did not reach a terminal status within {max_wait}s"
        )

    async def open_restores_tab(self) -> None:
        # There is no separate Restores tab today — restores are shown under
        # their parent backup in the Backups tab. Alias for clarity in
        # scenarios that expect one.
        await self.open_backups_tab()
