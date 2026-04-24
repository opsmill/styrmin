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

    # ------------------------------------------------------------------
    # Scheduling dialog
    # ------------------------------------------------------------------
    #
    # The frontend renders a single form over the whole SchedulingConfig
    # shape (tolerations, resources, topology spread, three affinity
    # blocks, runtime class). The fill helper below wipes each section's
    # existing rows before populating the new payload — tests submit a
    # full desired scheduling config, not a patch, so the semantics match
    # a fresh fill.

    async def open_scheduling_dialog(self) -> None:
        await self._page.get_by_role("button", name="Scheduling", exact=True).click()
        await self._page.get_by_role("dialog", name="Edit Scheduling").wait_for()

    async def save_scheduling_config(self) -> None:
        dialog = self._page.get_by_role("dialog", name="Edit Scheduling")
        await dialog.get_by_role("button", name="Save", exact=True).click()
        # The dialog closes on server-accepted mutation. An error surfaces
        # as an inline <Alert> that keeps the dialog open — surface that as
        # a ScenarioActionError so callers see the backend message.
        try:
            await dialog.wait_for(state="hidden", timeout=30_000)
        except AssertionError as exc:
            alert = dialog.locator("[role=alert]")
            message = (
                await alert.inner_text()
                if await alert.count() > 0
                else "(no alert rendered)"
            )
            raise ScenarioActionError(
                f"scheduling save did not close the dialog: {message}"
            ) from exc

    async def fill_scheduling_config(self, scheduling: dict) -> None:
        dialog = self._page.get_by_role("dialog", name="Edit Scheduling")
        await self._reset_scheduling_form(dialog)

        resources = scheduling.get("resources")
        if isinstance(resources, dict):
            await self._fill_scheduling_resources(dialog, resources)

        tolerations = scheduling.get("tolerations") or []
        for entry in tolerations:
            await self._add_scheduling_toleration(dialog, entry)

        topology = scheduling.get("topology_spread_constraints") or []
        for entry in topology:
            await self._add_scheduling_topology_spread(dialog, entry)

        for kind in ("pod_affinity", "pod_anti_affinity", "node_affinity"):
            block = scheduling.get(kind)
            if isinstance(block, dict):
                await self._fill_scheduling_affinity(dialog, kind, block)

        runtime_class = scheduling.get("runtime_class")
        if isinstance(runtime_class, str):
            await dialog.get_by_label("Runtime class name").fill(runtime_class)

    async def _reset_scheduling_form(self, dialog: Locator) -> None:
        # Clear every list-based section by clicking each row's remove
        # button. Iterates to count() each loop so removals shrink the
        # list in place. Resource inputs are cleared by filling with "".
        for testid in (
            "toleration-row",
            "topology-spread-row",
            "pod_affinity-required-row",
            "pod_affinity-preferred-row",
            "pod_anti_affinity-required-row",
            "pod_anti_affinity-preferred-row",
            "node_affinity-required-row",
            "node_affinity-preferred-row",
            "match-label-row",
            "match-expression-row",
        ):
            rows = dialog.locator(f"[data-testid={testid}]")
            # Deleting from the end avoids re-indexing the selectors between
            # clicks.
            while True:
                count = await rows.count()
                if count == 0:
                    break
                row = rows.nth(count - 1)
                await row.locator("[aria-label^='Remove']").first.click()
        # Clear resource input fields — they are plain <Input>s that never
        # create/remove rows.
        for variant in ("requests", "limits"):
            for field in ("cpu", "memory", "ephemeral_storage"):
                await dialog.locator(f"#res-{variant}-{field}").fill("")
        await dialog.get_by_label("Runtime class name").fill("")

    async def _fill_scheduling_resources(
        self, dialog: Locator, resources: dict
    ) -> None:
        for variant in ("requests", "limits"):
            spec = resources.get(variant)
            if not isinstance(spec, dict):
                continue
            for field in ("cpu", "memory", "ephemeral_storage"):
                value = spec.get(field)
                if value is None:
                    continue
                await dialog.locator(f"#res-{variant}-{field}").fill(str(value))

    async def _add_scheduling_toleration(self, dialog: Locator, entry: dict) -> None:
        await dialog.get_by_role("button", name="Add toleration", exact=True).click()
        row = dialog.locator("[data-testid=toleration-row]").last
        if (key := entry.get("key")) is not None:
            await row.get_by_label("Key").fill(str(key))
        if (operator := entry.get("operator")) is not None:
            await self._select_value(row, "Operator", str(operator))
        if (value := entry.get("value")) is not None:
            await row.get_by_label("Value").fill(str(value))
        if (effect := entry.get("effect")) is not None:
            await self._select_value(row, "Effect", str(effect))
        if (seconds := entry.get("toleration_seconds")) is not None:
            await row.get_by_label("Toleration seconds (optional)").fill(str(seconds))

    async def _add_scheduling_topology_spread(
        self, dialog: Locator, entry: dict
    ) -> None:
        await dialog.get_by_role(
            "button", name="Add topology spread constraint", exact=True
        ).click()
        row = dialog.locator("[data-testid=topology-spread-row]").last
        if (skew := entry.get("max_skew")) is not None:
            await row.get_by_label("Max skew").fill(str(skew))
        if (topology_key := entry.get("topology_key")) is not None:
            await row.get_by_label("Topology key").fill(str(topology_key))
        if (when := entry.get("when_unsatisfiable")) is not None:
            await self._select_value(row, "When unsatisfiable", str(when))
        label_selector = entry.get("label_selector")
        if isinstance(label_selector, dict):
            await self._fill_label_selector(row, label_selector)

    async def _fill_scheduling_affinity(
        self, dialog: Locator, kind: str, block: dict
    ) -> None:
        required_terms = block.get("required") or []
        preferred_terms = block.get("preferred") or []
        # Find the section by its testid (built in SchedulingConfigDialog).
        section_testid = {
            "pod_affinity": "scheduling-section-pod-affinity",
            "pod_anti_affinity": "scheduling-section-pod-anti-affinity",
            "node_affinity": "scheduling-section-node-affinity",
        }[kind]
        section = dialog.locator(f"[data-testid={section_testid}]")

        for term in required_terms:
            await section.get_by_role(
                "button", name="Add required term", exact=True
            ).click()
            row = section.locator(f"[data-testid={kind}-required-row]").last
            await self._fill_affinity_term(row, kind, term)

        for weighted in preferred_terms:
            await section.get_by_role(
                "button", name="Add preferred term", exact=True
            ).click()
            row = section.locator(f"[data-testid={kind}-preferred-row]").last
            if (weight := weighted.get("weight")) is not None:
                await row.get_by_label("Weight (1–100)").fill(str(weight))
            term = weighted.get("term")
            if isinstance(term, dict):
                await self._fill_affinity_term(row, kind, term)

    async def _fill_affinity_term(self, row: Locator, kind: str, term: dict) -> None:
        topology_key = term.get("topology_key")
        if kind != "node_affinity" and topology_key is not None:
            await row.get_by_label("Topology key").fill(str(topology_key))

        if kind in ("pod_affinity", "pod_anti_affinity"):
            # The target-mode selector only appears on pod-affinity rows.
            if term.get("deployment_ref"):
                await self._select_value(row, "Target by", "Deployment")
                dep_ref = term["deployment_ref"]
                if dep_id := dep_ref.get("deployment_id"):
                    await row.get_by_label("Deployment ID").fill(str(dep_id))
                if dep_name := dep_ref.get("deployment_name"):
                    await row.get_by_label("Deployment name (alternative)").fill(
                        str(dep_name)
                    )
                return
            # Fall through to label_selector (the default mode).
            await self._select_value(row, "Target by", "Label selector")

        label_selector = term.get("label_selector")
        if isinstance(label_selector, dict):
            await self._fill_label_selector(row, label_selector)

    async def _fill_label_selector(self, row: Locator, label_selector: dict) -> None:
        match_labels = label_selector.get("match_labels") or {}
        for key, value in match_labels.items():
            await row.get_by_role("button", name="Add match label", exact=True).click()
            ml_row = row.locator("[data-testid=match-label-row]").last
            # aria-label ends with the row's 1-based ordinal; targeting the
            # last row by its aria-label would require knowing the count, so
            # we fill the first empty key/value pair inside it.
            await ml_row.locator("input[placeholder='key']").fill(str(key))
            await ml_row.locator("input[placeholder='value']").fill(str(value))

        match_expressions = label_selector.get("match_expressions") or []
        for expr in match_expressions:
            await row.get_by_role(
                "button", name="Add match expression", exact=True
            ).click()
            expr_row = row.locator("[data-testid=match-expression-row]").last
            if (k := expr.get("key")) is not None:
                await expr_row.locator("input[placeholder='key']").fill(str(k))
            if (op := expr.get("operator")) is not None:
                # Each expression row contains exactly one combobox (the
                # operator Select); scope to the row and click it.
                await expr_row.get_by_role("combobox").click()
                await self._page.get_by_role("option", name=op, exact=True).click()
            values = expr.get("values") or []
            if values:
                await expr_row.locator(
                    "input[placeholder='values (comma-separated)']"
                ).fill(",".join(str(v) for v in values))

    async def _select_value(
        self, container: Locator, label_text: str, option: str
    ) -> None:
        # Base UI's Select renders the trigger as a <button role="combobox">.
        # Options appear inside a portal outside the dialog, so click handling
        # happens at the page level.
        trigger = container.get_by_label(label_text)
        await trigger.click()
        await self._page.get_by_role("option", name=option, exact=True).click()

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
