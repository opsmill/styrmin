"""Page object for the deployment detail view.

Route: ``/environments/$environmentId/deployments/$deploymentId``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.async_api import expect

from tests.e2e.drivers.errors import ScenarioActionError
from tests.e2e.drivers.refs import BackupRef, RestoreRef, TimelineEntry

if TYPE_CHECKING:
    from playwright.async_api import Page


# StatusBadge renders these labels for the corresponding backend statuses.
_STATUS_LABELS = {
    "running": "Running",
    "pending": "Pending",
    "in_progress": "In Progress",
    "completed": "Complete",
    "failed": "Failed",
}


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

        Must target the *deployment* status badge, not the timeline task
        badges. The detail page renders multiple StatusBadges (one for the
        deployment in the header, one per task under "Recent Timeline"),
        and the task "Create Instance" hits ``Running`` long before the
        deployment does — matching any ``Running`` on the page falsely
        succeeds while the deployment itself is still ``Pending``.

        Target the badge that sits immediately after the deployment-name
        ``<h1>`` via the CSS adjacent-sibling selector. The page
        auto-refreshes every 10s; ``expect().to_contain_text`` polls the
        DOM for us — no manual reload needed.
        """
        want_label = _STATUS_LABELS.get(expected.lower(), expected)
        header_badge = self._page.locator("h1 + *").first
        try:
            await expect(header_badge).to_contain_text(
                want_label, timeout=int(timeout * 1000)
            )
        except AssertionError as exc:
            raise ScenarioActionError(
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
            task_id = (await row.get_attribute("data-task-id")) or ""
            task_type = (await row.get_attribute("data-task-type")) or ""
            task_status = (await row.get_attribute("data-task-status")) or ""
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

    async def open_backups_tab(self) -> None:
        await self._page.get_by_role("button", name="Backups", exact=True).click()

    async def create_backup(self) -> BackupRef:
        """Click 'Create Backup' and return the newly-added row as a ref."""
        await self.open_backups_tab()

        existing_ids: set[str] = set()
        for i in range(await self._page.locator("[data-testid=backup-row]").count()):
            row = self._page.locator("[data-testid=backup-row]").nth(i)
            row_id = await row.get_attribute("data-backup-id")
            if row_id:
                existing_ids.add(row_id)

        await self._page.get_by_role("button", name="Create Backup").click()

        # Wait for a new row to appear.
        async def _first_new_row() -> BackupRef | None:
            rows = self._page.locator("[data-testid=backup-row]")
            for i in range(await rows.count()):
                row = rows.nth(i)
                row_id = await row.get_attribute("data-backup-id")
                if row_id and row_id not in existing_ids:
                    name = (await row.get_attribute("data-backup-name")) or ""
                    status = (await row.get_attribute("data-backup-status")) or ""
                    return BackupRef(id=row_id, name=name, status=status)
            return None

        import asyncio
        import time

        deadline = time.time() + 60.0
        while time.time() < deadline:
            ref = await _first_new_row()
            if ref is not None:
                return ref
            await asyncio.sleep(1.0)
        raise ScenarioActionError(
            "create_backup: new backup row did not appear within 60s"
        )

    async def wait_for_backup_status(
        self, *, backup_id: str, terminal_statuses: tuple[str, ...], max_wait: float
    ) -> BackupRef:
        """Poll the backup row until ``data-backup-status`` is terminal."""
        import asyncio
        import time

        deadline = time.time() + max_wait
        row = self._page.locator(
            f"[data-testid=backup-row][data-backup-id='{backup_id}']"
        ).first
        while time.time() < deadline:
            if await row.count() > 0:
                status = (await row.get_attribute("data-backup-status")) or ""
                if status in terminal_statuses:
                    name = (await row.get_attribute("data-backup-name")) or ""
                    return BackupRef(id=backup_id, name=name, status=status)
            await asyncio.sleep(2.0)
        raise ScenarioActionError(
            f"backup {backup_id} did not reach a terminal status within {max_wait}s"
        )

    async def read_backup(self, *, backup_id: str) -> BackupRef | None:
        """Read a backup row by id, or return ``None`` if the row is absent."""
        row = self._page.locator(
            f"[data-testid=backup-row][data-backup-id='{backup_id}']"
        ).first
        if await row.count() == 0:
            return None
        status = (await row.get_attribute("data-backup-status")) or ""
        name = (await row.get_attribute("data-backup-name")) or ""
        return BackupRef(id=backup_id, name=name, status=status)

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

        ``target_namespace`` is passed by scenarios for protocol parity — the
        dialog reads it from the deployment context (readOnly input) and we
        simply verify the displayed value matches what the scenario expects.
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
            r_id = await restore_rows.nth(i).get_attribute("data-restore-id")
            if r_id:
                existing_ids.add(r_id)

        await dialog.get_by_role("button", name="Restore", exact=True).click()
        await dialog.wait_for(state="hidden")

        import asyncio
        import time

        deadline = time.time() + 60.0
        while time.time() < deadline:
            rows = self._page.locator("[data-testid=restore-row]")
            for i in range(await rows.count()):
                r = rows.nth(i)
                rid = await r.get_attribute("data-restore-id")
                if rid and rid not in existing_ids:
                    status = (await r.get_attribute("data-restore-status")) or ""
                    return RestoreRef(id=rid, status=status)
            await asyncio.sleep(1.0)
        raise ScenarioActionError(
            "create_restore: new restore row did not appear within 60s"
        )

    async def wait_for_restore_status(
        self, *, restore_id: str, terminal_statuses: tuple[str, ...], max_wait: float
    ) -> RestoreRef:
        """Poll the restore row until ``data-restore-status`` is terminal."""
        import asyncio
        import time

        deadline = time.time() + max_wait
        row = self._page.locator(
            f"[data-testid=restore-row][data-restore-id='{restore_id}']"
        ).first
        while time.time() < deadline:
            if await row.count() > 0:
                status = (await row.get_attribute("data-restore-status")) or ""
                if status in terminal_statuses:
                    return RestoreRef(id=restore_id, status=status)
            await asyncio.sleep(2.0)
        raise ScenarioActionError(
            f"restore {restore_id} did not reach a terminal status within {max_wait}s"
        )

    async def open_restores_tab(self) -> None:
        # There is no separate Restores tab today — restores are shown under
        # their parent backup in the Backups tab. Alias for clarity in
        # scenarios that expect one.
        await self.open_backups_tab()
