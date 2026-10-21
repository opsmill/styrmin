"""Page objects for the Environments area.

Covers the environments list, create-environment dialog, and the
environment detail page (BSL assignment, deploy entry point).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, expect

from tests.e2e.drivers.errors import ScenarioActionError, ScenarioTimeout
from tests.e2e.drivers.refs import (
    EnvironmentBackupConstituentRef,
    EnvironmentBackupRef,
    EnvironmentCloneDeploymentResultRef,
    EnvironmentCloneRef,
    EnvironmentRef,
    EnvironmentRestoreRef,
    EnvironmentRestoreSkipRef,
)
from tests.e2e.pages._dom import (
    enter_text,
    required_attr as _required_attr,
    submit_dialog,
    wait_for_dialog_open,
)

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


# How long an expanded clone row may take to resolve its ``GetEnvironmentClone``
# detail query. Generous because the same styrmin-server is concurrently running
# a clone's capture and cross-target restore fan-out; short enough that a query
# which errored still fails inside a scenario's own budget.
_CLONE_DETAIL_TIMEOUT_SECONDS = 60.0

# Gap between reads of a clone row's derived status. The list refetches itself
# every 10s while anything is non-terminal, so polling faster than that only
# re-reads the same DOM; 3s matches the environment backup/restore waiters.
_CLONE_STATUS_POLL_SECONDS = 3.0

# How long ``cloneEnvironment`` may take to return and its row to appear. The
# mutation validates the name, resolves the source, registers the clone row plus
# its capture in one transaction and dispatches the constituent fan-out, all
# synchronously — the same shape (and budget) as the environment-restore
# mutation the Backups tab drives.
_CLONE_SUBMIT_TIMEOUT_SECONDS = 300.0


class EnvironmentsListPage:
    def __init__(self, page: Page, *, keystroke_delay_ms: int | None = None) -> None:
        self._page = page
        self._keystroke_delay_ms = keystroke_delay_ms

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
        self,
        *,
        name: str,
        cluster_id: str,
        config: dict[str, Any],
        open_page: bool = True,
    ) -> EnvironmentRef:
        """Drive the CreateEnvironmentDialog to create an environment.

        ``cluster_id`` selects the cluster in the dropdown. The dropdown
        renders option labels as cluster *names*, so the caller must have
        populated the data-cluster-id attribute via a preceding
        ``SettingsPage.create_cluster`` or similar. With ``open_page=False``
        the caller has already opened the environments list.
        """
        if open_page:
            await self.goto()
        await self._page.get_by_role("button", name="New Environment").click()
        dialog = self._page.get_by_role("dialog", name="Create Environment")
        await wait_for_dialog_open(dialog)

        await enter_text(
            dialog.locator("#env-name"),
            name,
            keystroke_delay_ms=self._keystroke_delay_ms,
        )

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
                await enter_text(
                    dialog.locator("#env-ingress-class"),
                    config["ingress_class"],
                    keystroke_delay_ms=self._keystroke_delay_ms,
                )
            if config.get("db_size"):
                await enter_text(
                    dialog.locator("#env-db-size"),
                    config["db_size"],
                    keystroke_delay_ms=self._keystroke_delay_ms,
                )
            if config.get("backup_ttl"):
                await enter_text(
                    dialog.locator("#env-backup-ttl"),
                    config["backup_ttl"],
                    keystroke_delay_ms=self._keystroke_delay_ms,
                )
            if config.get("fqdn_suffix"):
                await enter_text(
                    dialog.locator("#env-fqdn-suffix"),
                    config["fqdn_suffix"],
                    keystroke_delay_ms=self._keystroke_delay_ms,
                )
            ip_list = config.get("ip_whitelist")
            if ip_list:
                await enter_text(
                    dialog.locator("#env-ip-whitelist"),
                    ", ".join(ip_list) if isinstance(ip_list, list) else str(ip_list),
                    keystroke_delay_ms=self._keystroke_delay_ms,
                )
            di = config.get("dedicated_ingress")
            if di:
                await dialog.locator("#env-dedicated-ingress").click()
                if di.get("implementation"):
                    await enter_text(
                        dialog.locator("#env-di-impl"),
                        di["implementation"],
                        keystroke_delay_ms=self._keystroke_delay_ms,
                    )
                if di.get("type"):
                    await dialog.locator("#env-di-type").select_option(di["type"])

        await submit_dialog(dialog, button="Create")

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

    async def open_card(self, *, environment_id: str) -> None:
        """Click the environment's card; ends when the environment's page shows."""
        await self._page.locator(
            f"[data-testid=environment-card][data-environment-id='{environment_id}']"
        ).first.click()
        await EnvironmentDetailPage(self._page).wait_until_shown(
            environment_id=environment_id
        )

    async def read_card_summary(self, *, environment_id: str) -> tuple[str, int]:
        """Return the status and application count an environment card shows."""
        card = self._page.locator(
            f"[data-testid=environment-card][data-environment-id='{environment_id}']"
        ).first
        await card.wait_for()
        context = f"environment card {environment_id}"
        status = await _required_attr(card, "data-environment-status", context=context)
        count = await _required_attr(card, "data-application-count", context=context)
        return status, int(count)


class EnvironmentDetailPage:
    def __init__(self, page: Page, *, keystroke_delay_ms: int | None = None) -> None:
        self._page = page
        self._keystroke_delay_ms = keystroke_delay_ms

    async def goto(self, *, environment_id: str) -> None:
        await self._page.goto(f"/environments/{environment_id}")
        await self.wait_until_shown(environment_id=environment_id)

    async def wait_until_shown(self, *, environment_id: str) -> None:
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

    async def read_listed_deployment_ids(self) -> set[str]:
        """Return the ids of every deployment row the overview lists."""
        rows = self._page.locator("[data-testid=deployment-row]")
        return {
            await _required_attr(
                rows.nth(i), "data-deployment-id", context="deployment row"
            )
            for i in range(await rows.count())
        }

    async def read_application_count(self) -> int:
        """Return the number in the "Applications" summary tile."""
        tile = self._page.locator("[data-testid=environment-application-count]").first
        return int((await tile.inner_text()).strip())

    async def read_environment_status(self) -> str:
        """Return the status the header badge shows for the environment."""
        root = self._page.locator("[data-testid=environment-detail]").first
        return await _required_attr(
            root, "data-environment-status", context="environment detail"
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
            await enter_text(
                new_row.locator("[data-testid=env-var-name-input]"),
                name,
                keystroke_delay_ms=self._keystroke_delay_ms,
            )
            await enter_text(
                new_row.locator("[data-testid=env-var-value-input]"),
                value,
                keystroke_delay_ms=self._keystroke_delay_ms,
            )

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

        await enter_text(
            form.locator("[data-testid=backup-retention-input]"),
            ttl or "",
            keystroke_delay_ms=self._keystroke_delay_ms,
        )

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

    async def assign_bsl(
        self, *, environment_id: str, bsl_id: str, open_page: bool = True
    ) -> None:
        """Open the Parameters tab and pick the BSL from the selector.

        With ``open_page=False`` the caller has already opened the environment's page.
        """
        if open_page:
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

    def __init__(self, page: Page, *, keystroke_delay_ms: int | None = None) -> None:
        self._page = page
        self._keystroke_delay_ms = keystroke_delay_ms

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
                    # ``ListEnvironmentBackups`` does project ``constituents.
                    # error``, and the row publishes it as
                    # ``data-constituent-error``, so the UI driver reports the
                    # same free-text message the API driver does. Hardcoding
                    # ``None`` here would make any future assertion on
                    # ``.error`` pass [api-chromium] and fail [ui-chromium].
                    # "" is the DOM's stand-in for null (an attribute cannot
                    # hold one), normalised back the same way ``backup_id`` is.
                    error=(await item.get_attribute("data-constituent-error")) or None,
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
        button = row.locator("[data-testid=environment-backup-delete-button]").first
        if await button.count() == 0:
            # Same guard as ``restore_backup``: the button is wrapped in
            # ``IfRole minimum="READ_WRITE"``, so for a READ_ONLY operator it is
            # absent rather than disabled. Without this, the click below fails
            # with a bare Playwright "element not found" timeout instead of
            # naming the permission as the cause.
            raise ScenarioActionError(
                "delete button is absent — the signed-in user is not "
                "READ_WRITE or ADMIN"
            )
        await button.click()
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


class EnvironmentClonesTabPage:
    """The Clones tab on the environment detail page (spec 010-environment-clone).

    Backs :class:`~tests.e2e.drivers.ui_driver.UiScenarioDriver`'s
    environment-clone methods. Scoped by the clone's **source** environment: the
    tab lists the clones taken *of* this environment, so every method needs the
    source id even when it is only reading one clone by its own id.

    Three rendering facts drive the shape of this class:

    * the collapsed row publishes identity, derived status, the created
      environment and the backing capture as ``data-*`` attributes, but the
      per-deployment attribution and the recorded events only exist in the DOM
      while the row is expanded — and they come from a *second* query
      (``GetEnvironmentClone``) that resolves after the expansion, so expanding
      is not the same as having the detail;
    * the list polls on a 10s interval only while some listed clone is
      non-terminal, so a status transition needs a poll to become visible while
      a finished list is stable;
    * every read is taken off ``data-*`` attributes rather than visible text, so
      the UI driver reports the same raw enum names (``COMPLETED``, ``CLONED``,
      …) the API driver reads off the generated enums.
    """

    def __init__(self, page: Page, *, keystroke_delay_ms: int | None = None) -> None:
        self._page = page
        self._keystroke_delay_ms = keystroke_delay_ms

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    async def goto(self, *, environment_id: str) -> None:
        """Open ``/environments/{id}`` and switch to the Clones tab."""
        await self._page.goto(f"/environments/{environment_id}")
        detail = self._page.locator(
            f"[data-testid=environment-detail][data-environment-id='{environment_id}']"
        ).first
        await detail.wait_for()
        # Same caveat as the Backups and Configuration tabs: the project's
        # ``Tabs`` primitive renders plain buttons with no ``role="tab"``.
        await self._page.get_by_role("button", name="Clones", exact=True).click()
        await self._section(environment_id).wait_for(state="visible")
        await self._wait_for_list_settled(environment_id=environment_id)

    def _section(self, environment_id: str) -> Locator:
        return self._page.locator(
            f"[data-testid=environment-clones-section]"
            f"[data-environment-id='{environment_id}']"
        ).first

    async def _wait_for_list_settled(self, *, environment_id: str) -> None:
        """Block until ``ListEnvironmentClones`` has committed to an answer.

        A mounted section is not a loaded list: while the query is in flight the
        panel renders "Loading clones..." with no rows at all, so a row lookup
        at that moment reports an existing clone as absent. Settled means at
        least one clone row, or the empty state.
        """
        section = self._section(environment_id)
        deadline = time.time() + _LIST_SETTLE_TIMEOUT_SECONDS
        while time.time() < deadline:
            if await section.locator("[data-testid=environment-clone-row]").count() > 0:
                return
            if await section.locator("[data-testid=environment-clones-empty]").count():
                return
            await asyncio.sleep(0.5)
        raise ScenarioTimeout(
            "environment clones list rendered neither a clone row nor the empty "
            f"state within {_LIST_SETTLE_TIMEOUT_SECONDS}s on environment "
            f"{environment_id} — the query may have failed (the section renders "
            "an ErrorState carrying no test hook)"
        )

    async def _ensure_on_tab(self, *, environment_id: str) -> None:
        """Re-enter the Clones tab unless it is already the active panel.

        The Playwright page is session-scoped and shared with every other
        scenario, so "already there" is never assumed — but re-navigating on
        every call would throw away the row expansions this page relies on.
        """
        section = self._section(environment_id)
        if await section.count() > 0 and await section.is_visible():
            return
        await self.goto(environment_id=environment_id)

    def _row(self, environment_id: str, environment_clone_id: str) -> Locator:
        return (
            self._section(environment_id)
            .locator(
                f"[data-testid=environment-clone-row]"
                f"[data-environment-clone-id='{environment_clone_id}']"
            )
            .first
        )

    async def _find_row(
        self,
        environment_id: str,
        environment_clone_id: str,
        *,
        timeout: float = _ROW_APPEAR_TIMEOUT_SECONDS,
    ) -> Locator | None:
        """Return a clone row, or ``None`` once ``timeout`` proves it absent.

        Polls rather than reading once: the list refetches on a 10s interval
        while anything is non-terminal, so a clone created or changed out of
        band needs a moment to land. Returning ``None`` only after the wait
        keeps "absent" a real answer, which is what lets a scenario assert that
        deleting the source removed a clone record.
        """
        deadline = time.time() + timeout
        while True:
            row = self._row(environment_id, environment_clone_id)
            if await row.count() > 0:
                return row
            # The empty state is a *positive* "no clones at all" answer, so an
            # absent record resolves at once instead of burning the budget.
            if (
                await self._section(environment_id)
                .locator("[data-testid=environment-clones-empty]")
                .count()
                > 0
            ):
                return None
            if time.time() >= deadline:
                return None
            await asyncio.sleep(1.0)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def _ensure_detail_loaded(self, row: Locator, *, context: str) -> None:
        """Expand a clone row and wait for its detail query to resolve.

        Two steps, because expanding only mounts the panel: the attribution
        list and the recorded events come from ``GetEnvironmentClone``, which is
        ``enabled`` on expansion and renders "Loading clone details..." until it
        resolves. Waiting only for the panel would read an empty attribution
        list as "no source deployments considered".
        """
        button = row.locator("[data-testid=environment-clone-expand-button]").first
        if await button.get_attribute("aria-expanded") != "true":
            await button.click()
        detail = row.locator("[data-testid=environment-clone-detail]").first
        try:
            await detail.wait_for(state="visible", timeout=15_000)
        except PlaywrightTimeoutError as exc:
            raise ScenarioActionError(
                f"{context}: clone row did not expand its detail panel"
            ) from exc

        deadline = time.time() + _CLONE_DETAIL_TIMEOUT_SECONDS
        while time.time() < deadline:
            if await detail.locator("[data-testid=environment-clone-results]").count():
                return
            if await detail.locator(
                "[data-testid=environment-clone-results-empty]"
            ).count():
                return
            error = detail.locator("[data-testid=environment-clone-detail-error]")
            if await error.count() > 0:
                raise ScenarioActionError(
                    f"{context}: GetEnvironmentClone failed: "
                    f"{(await error.first.inner_text()).strip()}"
                )
            await asyncio.sleep(1.0)
        raise ScenarioTimeout(
            f"{context}: the expanded clone detail did not resolve its "
            f"attribution list within {_CLONE_DETAIL_TIMEOUT_SECONDS}s"
        )

    async def _read_results(
        self, row: Locator
    ) -> tuple[EnvironmentCloneDeploymentResultRef, ...]:
        items = row.locator("[data-testid=environment-clone-result]")
        results: list[EnvironmentCloneDeploymentResultRef] = []
        for i in range(await items.count()):
            item = items.nth(i)
            context = "environment clone deployment result"
            results.append(
                EnvironmentCloneDeploymentResultRef(
                    deployment_id=await _required_attr(
                        item, "data-deployment-id", context=context
                    ),
                    deployment_name=await _required_attr(
                        item, "data-deployment-name", context=context
                    ),
                    outcome=await _required_attr(item, "data-outcome", context=context),
                    # "" is the DOM's stand-in for null (an attribute cannot
                    # hold one), normalised back so both drivers agree.
                    reason=(await item.get_attribute("data-reason")) or None,
                    counterpart_deployment_id=(
                        await item.get_attribute("data-counterpart-deployment-id")
                    )
                    or None,
                    restore_id=(await item.get_attribute("data-restore-id")) or None,
                )
            )
        return tuple(results)

    async def _read_clone_errors(self, row: Locator) -> tuple[str, ...]:
        """Read the recorded operation-level events, already ``"step: error"``.

        The list is only rendered when there is at least one entry, so an
        absent ``environment-clone-errors`` block is an empty tuple rather than
        a missing hook.
        """
        entries = row.locator("[data-testid=environment-clone-error-entry]")
        # An explicit loop rather than ``tuple(... for ...)``: a generator
        # expression containing ``await`` is an *async* generator, which
        # ``tuple()`` cannot consume.
        rendered: list[str] = []
        for i in range(await entries.count()):
            rendered.append((await entries.nth(i).inner_text()).strip())
        return tuple(rendered)

    async def _read_row(
        self, row: Locator, *, environment_clone_id: str
    ) -> EnvironmentCloneRef:
        context = f"environment clone row {environment_clone_id}"
        await self._ensure_detail_loaded(row, context=context)
        return EnvironmentCloneRef(
            id=environment_clone_id,
            name=await _required_attr(
                row, "data-environment-clone-name", context=context
            ),
            status=await _required_attr(
                row, "data-environment-clone-status", context=context
            ),
            created_environment_id=(
                await row.get_attribute("data-created-environment-id")
            )
            or None,
            environment_backup_id=(
                await row.get_attribute("data-environment-backup-id")
            )
            or None,
            discarded=(
                await _required_attr(
                    row, "data-environment-clone-discarded", context=context
                )
            )
            == "true",
            deployment_results=await self._read_results(row),
            clone_errors=await self._read_clone_errors(row),
        )

    async def read_clone(
        self, *, environment_id: str, environment_clone_id: str
    ) -> EnvironmentCloneRef | None:
        """Read a clone row, or ``None`` when the list no longer shows it.

        Deliberately re-navigates instead of reusing an already-visible tab the
        way ``_ensure_on_tab`` would: the list drops its refetch interval as
        soon as every listed clone is terminal, and the expanded detail does the
        same. A terminal clone that then changes out of band — its created
        environment deleted, its backing capture removed — would therefore never
        appear, and this method is exactly how a scenario asserts that such a
        change landed. Remounting the queries is what makes the read honest;
        nothing is lost, since ``_read_row`` re-expands the row anyway.
        """
        await self.goto(environment_id=environment_id)
        row = await self._find_row(environment_id, environment_clone_id)
        if row is None:
            return None
        return await self._read_row(row, environment_clone_id=environment_clone_id)

    async def wait_for_clone_status(
        self,
        *,
        environment_id: str,
        environment_clone_id: str,
        terminal_statuses: frozenset[str],
        max_wait: float,
    ) -> EnvironmentCloneRef:
        """Poll ``data-environment-clone-status`` until it is terminal.

        Only the collapsed row's attribute is polled — the list refetches on its
        own while anything is non-terminal, and expanding on every iteration
        would add a detail query per poll for no gain. The expansion (and the
        full attribution read) happens once, after the status settles.
        """
        await self._ensure_on_tab(environment_id=environment_id)
        row = self._row(environment_id, environment_clone_id)
        context = f"environment clone row {environment_clone_id}"
        deadline = time.time() + max_wait
        last_status = "<row absent>"
        while time.time() < deadline:
            if await row.count() > 0:
                last_status = await _required_attr(
                    row, "data-environment-clone-status", context=context
                )
                if last_status in terminal_statuses:
                    return await self._read_row(
                        row, environment_clone_id=environment_clone_id
                    )
            else:
                # The shared session page may have been navigated away by
                # another step of the same scenario (the counterpart deployment
                # lives on a different environment's pages), so re-enter rather
                # than burning the whole budget on a detached locator.
                await self._ensure_on_tab(environment_id=environment_id)
                row = self._row(environment_id, environment_clone_id)
            await asyncio.sleep(_CLONE_STATUS_POLL_SECONDS)
        raise ScenarioTimeout(
            f"environment clone {environment_clone_id} did not reach a terminal "
            f"derived status within {max_wait}s (last seen: {last_status})"
        )

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_clone(
        self,
        *,
        environment_id: str,
        name: str,
        deployment_ids: list[str] | None,
        config_override: dict[str, Any] | None,
        clear_config_fields: list[str] | None,
    ) -> EnvironmentCloneRef:
        """Drive the clone dialog and return the newly-added clone row."""
        await self.goto(environment_id=environment_id)

        section = self._section(environment_id)
        existing_ids: set[str] = set()
        rows = section.locator("[data-testid=environment-clone-row]")
        for i in range(await rows.count()):
            existing_ids.add(
                await _required_attr(
                    rows.nth(i),
                    "data-environment-clone-id",
                    context="environment clone row",
                )
            )

        trigger = section.locator("[data-testid=clone-environment-button]").first
        if await trigger.count() == 0:
            # The whole dialog — trigger included — is wrapped in
            # ``IfRole minimum="ADMIN"``, so for a non-admin operator it is
            # absent rather than disabled. Without this the click below would
            # fail as a bare "element not found" timeout instead of naming the
            # permission as the cause.
            raise ScenarioActionError(
                "clone trigger is absent — the signed-in user is not ADMIN "
                "(cloning creates an environment and reads every included "
                "deployment's data)"
            )
        await trigger.click()
        dialog = self._page.locator("[data-testid=clone-environment-dialog]").first
        await wait_for_dialog_open(dialog)

        await enter_text(
            dialog.locator("[data-testid=clone-environment-name-input]"),
            name,
            keystroke_delay_ms=self._keystroke_delay_ms,
        )
        await self._fill_selection(dialog, deployment_ids=deployment_ids)
        await self._fill_config_override(dialog, config_override=config_override)
        await self._fill_clear_fields(dialog, clear_config_fields=clear_config_fields)

        await dialog.locator("[data-testid=clone-submit-button]").click()

        # ``cloneEnvironment`` validates the target name, resolves the source,
        # registers the clone row and its capture, and dispatches the
        # constituent fan-out — all synchronously — so the mutation can take a
        # while to return. On success the dialog closes itself; on a rejection
        # it stays open with the typed error rendered inline.
        deadline = time.time() + _CLONE_SUBMIT_TIMEOUT_SECONDS
        while time.time() < deadline:
            error = dialog.locator("[data-testid=clone-environment-error]")
            if await error.count() > 0:
                raise ScenarioActionError(
                    f"cloneEnvironment failed: "
                    f"{(await error.first.inner_text()).strip()}"
                )
            rows = section.locator("[data-testid=environment-clone-row]")
            for i in range(await rows.count()):
                candidate = rows.nth(i)
                candidate_id = await _required_attr(
                    candidate,
                    "data-environment-clone-id",
                    context="environment clone row",
                )
                if candidate_id in existing_ids:
                    continue
                return await self._read_row(
                    candidate, environment_clone_id=candidate_id
                )
            await asyncio.sleep(2.0)
        raise ScenarioTimeout(
            "clone_environment: no new clone row appeared within "
            f"{_CLONE_SUBMIT_TIMEOUT_SECONDS}s"
        )

    async def _fill_selection(
        self, dialog: Locator, *, deployment_ids: list[str] | None
    ) -> None:
        """Express the tri-state deployment selection in the dialog.

        ``None`` leaves "Include every eligible application" checked, which is
        what omits the ``deploymentIds`` argument. Anything else unchecks it and
        then reconciles the per-deployment checkboxes — including the empty
        list, which unchecks every one of them and sends the legal
        configuration-only request.

        The picker also renders the source's *ineligible* deployments (internal,
        tombstoned, never deployed) as locked rows with a reason, so a selection
        naming one of those has no checkbox to tick. That is reported as a
        driver error rather than silently sending a smaller selection.
        """
        include_all = dialog.locator("[data-testid=clone-include-all-checkbox]").first
        if deployment_ids is None:
            await expect(include_all).to_have_attribute("aria-checked", "true")
            return

        requested = set(deployment_ids)
        await include_all.click()
        await expect(include_all).to_have_attribute("aria-checked", "false")

        options = dialog.locator("[data-testid=clone-deployment-option]")
        seen: set[str] = set()
        for i in range(await options.count()):
            option = options.nth(i)
            context = "clone deployment option"
            deployment_id = await _required_attr(
                option, "data-deployment-id", context=context
            )
            seen.add(deployment_id)
            eligible = (
                await _required_attr(option, "data-eligible", context=context)
            ) == "true"
            wanted = deployment_id in requested
            if wanted and not eligible:
                raise ScenarioActionError(
                    f"deployment {deployment_id} was requested for the clone but "
                    "the dialog renders it as ineligible "
                    f"({await option.get_attribute('data-ineligible-reason')!r}); "
                    "the UI has no checkbox for it"
                )
            if not eligible:
                continue
            selected = (
                await _required_attr(option, "data-selected", context=context)
            ) == "true"
            if selected != wanted:
                await option.locator(
                    "[data-testid=clone-deployment-checkbox]"
                ).first.click()
            await expect(option).to_have_attribute(
                "data-selected", "true" if wanted else "false"
            )

        missing = sorted(requested - seen)
        if missing:
            raise ScenarioActionError(
                f"deployment(s) {missing} were requested for the clone but the "
                "dialog's picker does not list them (the source environment's "
                "deployment list may be stale, or they belong to another "
                "environment)"
            )

    async def _fill_config_override(
        self, dialog: Locator, *, config_override: dict[str, Any] | None
    ) -> None:
        """Type the override JSON into the textarea, blank meaning "no override".

        The form parses the text on every keystroke and disables submission
        while it does not parse, so a malformed payload is reported here rather
        than as a click that silently does nothing.
        """
        if config_override is None:
            return
        await enter_text(
            dialog.locator("[data-testid=clone-config-override-input]"),
            json.dumps(config_override),
            keystroke_delay_ms=self._keystroke_delay_ms,
        )
        error = dialog.locator("[data-testid=clone-config-override-error]")
        if await error.count() > 0:
            raise ScenarioActionError(
                "the clone dialog rejected the config override: "
                f"{(await error.first.inner_text()).strip()}"
            )

    async def _fill_clear_fields(
        self, dialog: Locator, *, clear_config_fields: list[str] | None
    ) -> None:
        """Tick the captured-config fields to clear.

        The checkboxes are built from the source environment's own config keys,
        so a field the source does not set has no row — reported as a driver
        error, since the UI cannot express it (the API driver can, and would
        accept it as a no-op).
        """
        for field_name in clear_config_fields or ():
            option = dialog.locator(
                f"[data-testid=clone-clear-field-option]"
                f"[data-config-field='{field_name}']"
            ).first
            if await option.count() == 0:
                raise ScenarioActionError(
                    f"config field {field_name!r} was requested for clearing but "
                    "the clone dialog does not offer it — the source "
                    "environment's config does not set that field"
                )
            if await option.get_attribute("data-selected") != "true":
                await option.locator(
                    "[data-testid=clone-clear-field-checkbox]"
                ).first.click()
            await expect(option).to_have_attribute("data-selected", "true")


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
