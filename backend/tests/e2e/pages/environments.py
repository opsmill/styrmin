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
from tests.e2e.drivers.refs import (
    EnvironmentBackupConstituentRef,
    EnvironmentBackupRef,
    EnvironmentRef,
    EnvironmentRestoreRef,
    EnvironmentRestoreSkipRef,
)
from tests.e2e.pages._dom import required_attr as _required_attr

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page

# An ``updateEnvironment`` write queues a redeploy Task on every deployment in
# the environment inside the same transaction, so the mutation the retention
# form awaits can take noticeably longer than Playwright's 5s expect default.
# Generous enough to absorb that; short enough that a form which never settles
# still fails inside the test's own budget.
_SAVE_SETTLE_TIMEOUT_MS = 60_000

# How long the environment Backups tab may take to resolve its
# ``ListEnvironmentBackups`` query after the panel mounts. Generous because the
# same styrmin-server is concurrently running a backup/restore fan-out; short
# enough that a query which errored (the panel renders an ``ErrorState`` with no
# test hook) still fails inside a scenario's own budget.
_LIST_SETTLE_TIMEOUT_SECONDS = 60.0

# How long a specific snapshot row may take to appear once the list has settled.
# Covers the tab's 10s ``refetchInterval`` picking up a change made out of band
# (a constituent deleted through the SDK, a snapshot created by another surface).
_ROW_APPEAR_TIMEOUT_SECONDS = 30.0


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
            if config.get("backup_ttl"):
                await dialog.locator("#env-backup-ttl").fill(config["backup_ttl"])
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
                    await dialog.locator("#env-di-type").select_option(di["type"])

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

    async def set_backup_ttl_via_form(
        self,
        *,
        environment_id: str,
        ttl: str | None,
    ) -> None:
        """Drive the BackupRetentionForm on the Configuration tab (016 / US1).

        Implements the UI side of the
        ``ScenarioDriver.set_environment_backup_ttl`` contract. ``ttl=None``
        is submitted as a blank input, which the form reads as "clear the
        environment policy" and sends as ``backupTtl: null``.
        """
        await self.goto(environment_id=environment_id)

        # Same caveat as ``update_env_vars_via_form``: the project's ``Tabs``
        # primitive does not set ``role="tab"``, so the Configuration tab has
        # to be matched as a button with the exact label.
        await self._page.get_by_role("button", name="Configuration", exact=True).click()

        form = self._page.locator("[data-testid=backup-retention-form]").first
        await form.wait_for(state="visible")

        # The form blocks submission outright when the persisted config
        # carries nested overrides a full-replacement write would clear.
        # Surface that as a driver error instead of timing out on a
        # permanently-disabled Save button.
        blocked = form.locator("[data-testid=backup-retention-blocked-warning]")
        if await blocked.count() > 0:
            raise ScenarioActionError(
                "BackupRetentionForm refuses to save on environment "
                f"{environment_id!r}: {(await blocked.inner_text()).strip()}"
            )

        await form.locator("[data-testid=backup-retention-input]").fill(ttl or "")

        # Client-side validation renders on keystroke (no blur needed) and
        # disables Save, so an invalid duration must fail loudly here rather
        # than hang on the click.
        client_error = form.locator("[data-testid=backup-retention-error]")
        if await client_error.count() > 0:
            raise ScenarioActionError(
                f"BackupRetentionForm rejected ttl={ttl!r}: "
                f"{(await client_error.inner_text()).strip()}"
            )

        save = form.locator("[data-testid=backup-retention-save-button]")
        await save.click()

        dialog = self._page.locator("[data-testid=redeploy-confirm-dialog]")
        await dialog.wait_for(state="visible")
        await self._page.locator("[data-testid=redeploy-confirm-redeploy]").click()

        # The dialog closes synchronously on confirm — before the mutation is
        # even issued — so "dialog hidden" is NOT a completion signal. Settle
        # on the Save button leaving its "Saving..." pending state first (as
        # the env-vars form does), then on the read-state span below. No
        # hardcoded sleeps.
        await expect(save).to_have_text("Save", timeout=_SAVE_SETTLE_TIMEOUT_MS)

        # The input keeps its own state and never re-seeds from the server, so
        # the ``backup-retention-current`` span is the only in-page evidence
        # that the write landed: it renders from the environment refetched by
        # ``invalidateQueries(['GetEnvironment'])`` after the mutation.
        expected = (
            "No environment policy set" if ttl is None else f"Environment policy: {ttl}"
        )
        current = form.locator("[data-testid=backup-retention-current]")
        try:
            await expect(current).to_contain_text(
                expected, timeout=_SAVE_SETTLE_TIMEOUT_MS
            )
        except AssertionError:
            # A rejected mutation leaves the read state untouched and renders
            # the server's message; report that rather than the bare
            # text-mismatch, which says nothing about why.
            submit_error = form.locator("[data-testid=backup-retention-submit-error]")
            if await submit_error.count() > 0:
                raise ScenarioActionError(
                    f"BackupRetentionForm save failed for ttl={ttl!r}: "
                    f"{(await submit_error.inner_text()).strip()}"
                ) from None
            raise

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


class EnvironmentBackupsTabPage:
    """The Backups tab on the environment detail page (spec 001-env-backup-restore).

    Backs :class:`~tests.e2e.drivers.ui_driver.UiScenarioDriver`'s
    environment-level backup/restore methods. Every read is taken off the
    ``data-*`` attributes the tab publishes rather than visible text, so the UI
    driver reports the same raw enum values (``COMPLETED``, ``PARTIAL``, …) and
    the same free-text skip reasons as the API driver.

    Two rendering facts drive the shape of this class:

    * a snapshot's per-constituent outcomes only exist in the DOM while its row
      is expanded, so every constituent read expands the row first;
    * the restore panel is inside that same expansion, and the row keeps its
      own ``expanded`` state across the tab's 10s refetch (the list is keyed by
      snapshot id, so React does not remount it).
    """

    def __init__(self, page: Page) -> None:
        self._page = page

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    async def goto(self, *, environment_id: str) -> None:
        """Open ``/environments/{id}`` and switch to the Backups tab."""
        await self._page.goto(f"/environments/{environment_id}")
        detail = self._page.locator(
            f"[data-testid=environment-detail][data-environment-id='{environment_id}']"
        ).first
        await detail.wait_for()
        # The project's ``Tabs`` primitive renders plain buttons (no
        # ``role="tab"``), same caveat as the Configuration tab above.
        await self._page.get_by_role("button", name="Backups", exact=True).click()
        await self._tab(environment_id).wait_for(state="visible")
        await self._wait_for_list_settled(environment_id=environment_id)

    async def _wait_for_list_settled(self, *, environment_id: str) -> None:
        """Block until the ``ListEnvironmentBackups`` query has resolved.

        A mounted tab is not a loaded list: while the query is in flight the
        panel renders "Loading environment backups..." with no rows at all, so a
        row lookup at that moment reports an existing snapshot as absent. That is
        exactly how the UI entrypoint first failed — re-entering the tab after an
        env-config write and immediately looking for the snapshot it had been
        reading a moment earlier.

        Settled means the panel committed to an answer: at least one snapshot row,
        or the empty state.
        """
        tab = self._tab(environment_id)
        deadline = time.time() + _LIST_SETTLE_TIMEOUT_SECONDS
        while time.time() < deadline:
            if await tab.locator("[data-testid=environment-backup-row]").count() > 0:
                return
            if await tab.locator("[data-testid=environment-backups-empty]").count() > 0:
                return
            await asyncio.sleep(0.5)
        raise ScenarioTimeout(
            "environment backups list rendered neither a snapshot row nor the "
            f"empty state within {_LIST_SETTLE_TIMEOUT_SECONDS}s on environment "
            f"{environment_id} — the query may have failed (the panel renders an "
            "ErrorState carrying no test hook)"
        )

    def _tab(self, environment_id: str) -> Locator:
        return self._page.locator(
            f"[data-testid=environment-backups-tab]"
            f"[data-environment-id='{environment_id}']"
        ).first

    async def _ensure_on_tab(self, *, environment_id: str) -> None:
        """Re-enter the Backups tab unless it is already the active panel.

        The Playwright page is session-scoped and shared with every other
        scenario, so "already there" is never assumed — but re-navigating on
        every call would throw away the row expansions this page relies on.
        """
        if await self._tab(environment_id).count() > 0:
            if await self._tab(environment_id).is_visible():
                return
        await self.goto(environment_id=environment_id)

    def _row(self, environment_backup_id: str) -> Locator:
        return self._page.locator(
            f"[data-testid=environment-backup-row]"
            f"[data-environment-backup-id='{environment_backup_id}']"
        ).first

    async def _find_row(
        self,
        environment_backup_id: str,
        *,
        timeout: float = _ROW_APPEAR_TIMEOUT_SECONDS,
    ) -> Locator | None:
        """Return a snapshot row, or ``None`` once ``timeout`` proves it absent.

        Polls rather than reading once: the list refetches on a 10s interval, so
        a snapshot created or changed out of band (or one whose row is rendering
        from a refetch triggered by a mutation) needs a moment to land. Returning
        ``None`` only after the wait keeps "absent" a real answer — which is what
        makes ``get_environment_backup`` a sound cascade-delete assertion.
        """
        deadline = time.time() + timeout
        while True:
            row = self._row(environment_backup_id)
            if await row.count() > 0:
                return row
            # The empty state is a *positive* "no snapshots at all" answer, so a
            # cascade delete of the last snapshot resolves at once instead of
            # burning the whole budget waiting for a row that cannot come.
            if (
                await self._page.locator(
                    "[data-testid=environment-backups-empty]"
                ).count()
                > 0
            ):
                return None
            if time.time() >= deadline:
                return None
            await asyncio.sleep(1.0)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def _ensure_expanded(self, row: Locator, *, context: str) -> None:
        """Expand a snapshot row so its constituents and restores are rendered."""
        button = row.locator("[data-testid=environment-backup-expand-button]").first
        if await button.get_attribute("aria-expanded") != "true":
            await button.click()
        detail = row.locator("[data-testid=environment-backup-detail]").first
        try:
            await detail.wait_for(state="visible", timeout=15_000)
        except PlaywrightTimeoutError as exc:
            raise ScenarioActionError(
                f"{context}: snapshot row did not expand its detail panel"
            ) from exc

    async def _read_constituents(
        self, row: Locator
    ) -> tuple[EnvironmentBackupConstituentRef, ...]:
        items = row.locator("[data-testid=environment-backup-constituent]")
        constituents: list[EnvironmentBackupConstituentRef] = []
        for i in range(await items.count()):
            item = items.nth(i)
            context = "environment backup constituent"
            backup_id = await item.get_attribute("data-backup-id")
            backup_status = await item.get_attribute("data-backup-status")
            constituents.append(
                EnvironmentBackupConstituentRef(
                    deployment_id=await _required_attr(
                        item, "data-deployment-id", context=context
                    ),
                    deployment_name=await _required_attr(
                        item, "data-deployment-name", context=context
                    ),
                    outcome=await _required_attr(
                        item, "data-constituent-outcome", context=context
                    ),
                    # The row renders "" for an absent backup (a DOM attribute
                    # cannot hold null), which is the `missing` gap — normalise
                    # it back to None so both drivers agree.
                    backup_id=backup_id or None,
                    backup_status=backup_status or None,
                    # The list query does not project the creation error text,
                    # only its presence via ``data-constituent-outcome=error``.
                    # Scenarios assert on the outcome; the API driver carries
                    # the message for diagnosis only.
                    error=None,
                )
            )
        return tuple(constituents)

    async def read_backup(
        self, *, environment_id: str, environment_backup_id: str
    ) -> EnvironmentBackupRef | None:
        """Read a snapshot row, or ``None`` when the list no longer shows it."""
        await self._ensure_on_tab(environment_id=environment_id)
        row = await self._find_row(environment_backup_id)
        if row is None:
            return None
        context = f"environment backup row {environment_backup_id}"
        await self._ensure_expanded(row, context=context)
        return EnvironmentBackupRef(
            id=environment_backup_id,
            name=await _required_attr(
                row, "data-environment-backup-name", context=context
            ),
            status=await _required_attr(
                row, "data-environment-backup-status", context=context
            ),
            constituents=await self._read_constituents(row),
        )

    async def wait_for_backup_status(
        self,
        *,
        environment_id: str,
        environment_backup_id: str,
        terminal_statuses: frozenset[str],
        max_wait: float,
    ) -> EnvironmentBackupRef:
        """Poll ``data-environment-backup-status`` until it is terminal.

        The tab refetches every 10s on its own, so this only has to re-read the
        attribute — no reload, which would collapse the row.
        """
        await self._ensure_on_tab(environment_id=environment_id)
        row = self._row(environment_backup_id)
        context = f"environment backup row {environment_backup_id}"
        deadline = time.time() + max_wait
        last_status = "<row absent>"
        while time.time() < deadline:
            if await row.count() > 0:
                last_status = await _required_attr(
                    row, "data-environment-backup-status", context=context
                )
                if last_status in terminal_statuses:
                    await self._ensure_expanded(row, context=context)
                    return EnvironmentBackupRef(
                        id=environment_backup_id,
                        name=await _required_attr(
                            row, "data-environment-backup-name", context=context
                        ),
                        status=last_status,
                        constituents=await self._read_constituents(row),
                    )
            await asyncio.sleep(3.0)
        raise ScenarioTimeout(
            f"environment backup {environment_backup_id} did not reach a terminal "
            f"derived status within {max_wait}s (last seen: {last_status})"
        )

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_backup(self, *, environment_id: str) -> EnvironmentBackupRef:
        """Click "Create Backup" and return the newly-added snapshot row."""
        await self.goto(environment_id=environment_id)

        rows = self._page.locator("[data-testid=environment-backup-row]")
        existing_ids: set[str] = set()
        for i in range(await rows.count()):
            existing_ids.add(
                await _required_attr(
                    rows.nth(i),
                    "data-environment-backup-id",
                    context="environment backup row",
                )
            )

        await self._page.locator(
            "[data-testid=create-environment-backup-button]"
        ).click()

        deadline = time.time() + 120.0
        while time.time() < deadline:
            await self._raise_on_tab_error(environment_id=environment_id)
            rows = self._page.locator("[data-testid=environment-backup-row]")
            for i in range(await rows.count()):
                row = rows.nth(i)
                row_id = await _required_attr(
                    row,
                    "data-environment-backup-id",
                    context="environment backup row",
                )
                if row_id in existing_ids:
                    continue
                context = f"environment backup row {row_id}"
                await self._ensure_expanded(row, context=context)
                return EnvironmentBackupRef(
                    id=row_id,
                    name=await _required_attr(
                        row, "data-environment-backup-name", context=context
                    ),
                    status=await _required_attr(
                        row, "data-environment-backup-status", context=context
                    ),
                    constituents=await self._read_constituents(row),
                )
            await asyncio.sleep(2.0)
        raise ScenarioTimeout(
            "create_environment_backup: no new snapshot row appeared within 120s"
        )

    async def _raise_on_tab_error(self, *, environment_id: str) -> None:
        """Surface the tab's inline mutation error instead of timing out on it."""
        alert = self._tab(environment_id).locator(
            "[data-testid=environment-backups-error]"
        )
        if await alert.count() > 0:
            raise ScenarioActionError(
                "environment backups tab reported an error: "
                f"{(await alert.first.inner_text()).strip()}"
            )

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    async def _read_restore(self, row: Locator) -> EnvironmentRestoreRef:
        restore_id = await _required_attr(
            row, "data-environment-restore-id", context="environment restore row"
        )
        context = f"environment restore row {restore_id}"
        constituents = row.locator("[data-testid=environment-restore-constituent]")
        restore_ids: list[str] = []
        for i in range(await constituents.count()):
            restore_ids.append(
                await _required_attr(
                    constituents.nth(i), "data-restore-id", context=context
                )
            )
        skips = row.locator("[data-testid=environment-restore-skipped-constituent]")
        skipped: list[EnvironmentRestoreSkipRef] = []
        for i in range(await skips.count()):
            skip = skips.nth(i)
            skipped.append(
                EnvironmentRestoreSkipRef(
                    deployment_id=await _required_attr(
                        skip, "data-deployment-id", context=context
                    ),
                    deployment_name=await _required_attr(
                        skip, "data-deployment-name", context=context
                    ),
                    reason=await _required_attr(
                        skip, "data-skip-reason", context=context
                    ),
                )
            )
        return EnvironmentRestoreRef(
            id=restore_id,
            status=await _required_attr(
                row, "data-environment-restore-status", context=context
            ),
            restore_ids=tuple(restore_ids),
            skipped=tuple(skipped),
        )

    async def restore_backup(
        self, *, environment_id: str, environment_backup_id: str
    ) -> EnvironmentRestoreRef:
        """Drive the restore confirm dialog and return the new restore row.

        The button is gated on ``data-restorable`` (COMPLETED / PARTIAL only),
        so a scenario that reaches here on a non-restorable snapshot gets a
        descriptive error rather than a click that silently does nothing.
        """
        await self._ensure_on_tab(environment_id=environment_id)
        row = await self._find_row(environment_backup_id)
        if row is None:
            raise ScenarioActionError(
                f"environment backup {environment_backup_id} is not listed on "
                f"environment {environment_id}"
            )
        button = row.locator("[data-testid=environment-backup-restore-button]").first
        if await button.count() == 0:
            raise ScenarioActionError(
                "restore button is absent — the signed-in user is not ADMIN "
                "(restoring reverts the environment config)"
            )
        if await button.get_attribute("data-restorable") != "true":
            status = await row.get_attribute("data-environment-backup-status")
            raise ScenarioActionError(
                f"environment backup {environment_backup_id} is not restorable "
                f"(derived status {status!r}); the UI disables the action"
            )

        # The restores panel is inside the row's expansion and the mutation's
        # success handler expands it for us, but existing restores have to be
        # snapshotted first so the new row can be told apart.
        await self._ensure_expanded(
            row, context=f"environment backup row {environment_backup_id}"
        )
        existing_ids: set[str] = set()
        existing = row.locator("[data-testid=environment-restore-row]")
        for i in range(await existing.count()):
            existing_ids.add(
                await _required_attr(
                    existing.nth(i),
                    "data-environment-restore-id",
                    context="environment restore row",
                )
            )

        await button.click()
        dialog = self._page.locator("[data-testid=environment-restore-dialog]").first
        await dialog.wait_for(state="visible")
        await self._page.locator(
            "[data-testid=environment-restore-dialog-confirm]"
        ).click()

        # ``restoreEnvironmentBackup`` classifies every constituent, reverts the
        # environment config, fans the revert out to the non-restoring
        # deployments and dispatches one restore per usable constituent — all
        # synchronously — so the mutation can take a while to return. The panel
        # auto-expands on success (no expand click needed here).
        deadline = time.time() + 300.0
        while time.time() < deadline:
            error = row.locator("[data-testid=environment-backup-restore-error]")
            if await error.count() > 0:
                raise ScenarioActionError(
                    "restoreEnvironmentBackup failed: "
                    f"{(await error.first.inner_text()).strip()}"
                )
            rows = row.locator("[data-testid=environment-restore-row]")
            for i in range(await rows.count()):
                candidate = rows.nth(i)
                candidate_id = await _required_attr(
                    candidate,
                    "data-environment-restore-id",
                    context="environment restore row",
                )
                if candidate_id in existing_ids:
                    continue
                return await self._read_restore(candidate)
            await asyncio.sleep(2.0)
        raise ScenarioTimeout(
            "restore_environment_backup: no new restore row appeared within 300s"
        )

    async def wait_for_restore_status(
        self,
        *,
        environment_id: str,
        environment_backup_id: str,
        environment_restore_id: str,
        terminal_statuses: frozenset[str],
        max_wait: float,
    ) -> EnvironmentRestoreRef:
        """Poll ``data-environment-restore-status`` until it is terminal."""
        deadline = time.time() + max_wait
        last_status = "<row absent>"
        while time.time() < deadline:
            row = self._page.locator(
                f"[data-testid=environment-restore-row]"
                f"[data-environment-restore-id='{environment_restore_id}']"
            ).first
            if await row.count() == 0:
                # The shared session page may have been navigated away, or the
                # snapshot row collapsed — re-enter and re-expand rather than
                # burning the whole budget on an absent locator.
                await self._ensure_on_tab(environment_id=environment_id)
                parent = self._row(environment_backup_id)
                if await parent.count() > 0:
                    await self._ensure_expanded(
                        parent,
                        context=f"environment backup row {environment_backup_id}",
                    )
                await asyncio.sleep(3.0)
                continue
            last_status = await _required_attr(
                row,
                "data-environment-restore-status",
                context=f"environment restore row {environment_restore_id}",
            )
            if last_status in terminal_statuses:
                return await self._read_restore(row)
            await asyncio.sleep(3.0)
        raise ScenarioTimeout(
            f"environment restore {environment_restore_id} did not reach a terminal "
            f"derived status within {max_wait}s (last seen: {last_status})"
        )

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete_backup(
        self, *, environment_id: str, environment_backup_id: str
    ) -> None:
        """Delete a snapshot through the confirm dialog and wait for the row to go.

        The delete button is never disabled by status — deleting an in-progress
        snapshot is the documented escape hatch (spec FR-010).
        """
        await self._ensure_on_tab(environment_id=environment_id)
        row = await self._find_row(environment_backup_id)
        if row is None:
            raise ScenarioActionError(
                f"environment backup {environment_backup_id} is not listed on "
                f"environment {environment_id}"
            )
        await row.locator("[data-testid=environment-backup-delete-button]").click()
        dialog = self._page.locator(
            "[data-testid=environment-backup-delete-dialog]"
        ).first
        await dialog.wait_for(state="visible")
        await self._page.locator(
            "[data-testid=environment-backup-delete-dialog-confirm]"
        ).click()

        deadline = time.time() + 120.0
        while time.time() < deadline:
            error = row.locator("[data-testid=environment-backup-delete-error]")
            if await error.count() > 0:
                raise ScenarioActionError(
                    "deleteEnvironmentBackup failed: "
                    f"{(await error.first.inner_text()).strip()}"
                )
            if await self._row(environment_backup_id).count() == 0:
                return
            await asyncio.sleep(2.0)
        raise ScenarioTimeout(
            f"environment backup {environment_backup_id} row did not disappear "
            "within 120s of confirming the delete"
        )


def _needs_advanced(config: dict[str, Any]) -> bool:
    keys = (
        "ingress_class",
        "db_size",
        "backup_ttl",
        "fqdn_suffix",
        "ip_whitelist",
        "dedicated_ingress",
    )
    return any(config.get(k) for k in keys)
