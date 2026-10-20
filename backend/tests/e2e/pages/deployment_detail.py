"""Page object for the deployment detail view.

Route: ``/environments/$environmentId/deployments/$deploymentId``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, expect

from tests.e2e.drivers.errors import ScenarioActionError, ScenarioTimeout
from tests.e2e.drivers.refs import (
    BackupRef,
    RestoreRef,
    StepErrorRef,
    StepRef,
    TaskLinkRef,
    TimelineEntry,
)

# Shared with ``pages/environments.py`` — both read their state off ``data-*``
# test hooks and must fail identically when one is missing.
from tests.e2e.pages._dom import (
    enter_text,
    required_attr as _required_attr,
    submit_dialog,
    wait_for_dialog_open,
)

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


# One round trip per entry: the step rows of collapsed entries stay mounted.
_READ_STEP_ROWS_JS = """
rows => rows.map(row => ({
  ...row.dataset,
  name: row.querySelector('[data-testid=step-name]')?.textContent ?? '',
  errors: [...row.querySelectorAll('[data-testid=step-error]')].map(error => ({
    attempt: error.dataset.attempt,
    occurredAt: error.dataset.occurredAt,
    message: error.querySelector('[data-testid=step-error-message]')?.textContent ?? '',
  })),
  detail: row.querySelector('[data-testid=step-detail]')?.textContent ?? null,
}))
"""

_STEP_REQUIRED_ATTRS = ("stepId", "stepKey", "stepKind", "stepStatus", "stepAttempts")

# Started tasks are listed under the hook steps that started them.
_READ_STARTED_TASKS_JS = """
items => items.map(item => ({ ...item.dataset }))
"""


_TIMELINE_EMPTY_TEXT = "No operations have been recorded for this deployment."
_TIMELINE_POLL_SECONDS = 2.0

# One round trip for the id, type and result of every timeline entry.
_READ_TIMELINE_TASKS_JS = """
rows => rows.map(row => ({
  id: row.dataset.taskId ?? '',
  type: row.dataset.taskType ?? '',
  result: row.dataset.taskResult ?? '',
}))
"""

# ``TaskResult`` values; the timeline renders them as GraphQL enum names
# (``SUCCEEDED``), so they are compared in lower case.
_TASK_SUCCEEDED = "succeeded"
_TASK_UNSUCCESSFUL = frozenset({"failed", "superseded"})


@dataclass(frozen=True)
class _TimelineTask:
    id: str
    type: str
    result: str


def _timeline_task_from_row(row: dict[str, str]) -> _TimelineTask:
    task = _TimelineTask(id=row["id"], type=row["type"], result=row["result"])
    if not (task.id and task.type and task.result):
        raise ScenarioActionError(
            f"timeline entry {task.id or '?'} rendered without data-task-id, "
            "data-task-type or data-task-result "
            "(frontend test-hook may have been removed or renamed)"
        )
    return task


def _succeeded_new_task(
    tasks: list[_TimelineTask], *, task_type: str, known_task_ids: set[str]
) -> str | None:
    """Return the id of a new ``task_type`` task that succeeded, or ``None``.

    Raises ``ScenarioActionError`` naming a new task that failed or was superseded.
    """
    new = [t for t in tasks if t.type == task_type and t.id not in known_task_ids]
    for task in new:
        if task.result.lower() in _TASK_UNSUCCESSFUL:
            raise ScenarioActionError(
                f"{task_type} task {task.id} ended with result {task.result}"
            )
    for task in new:
        if task.result.lower() == _TASK_SUCCEEDED:
            return task.id
    return None


def _iso_or_none(value: str | None) -> str | None:
    # Same string shape as the API driver's ``datetime.isoformat()``.
    return datetime.fromisoformat(value).isoformat() if value else None


def _step_ref_from_row(row: dict[str, Any], *, context: str) -> StepRef:
    missing = [attr for attr in _STEP_REQUIRED_ATTRS if not row.get(attr)]
    if missing:
        raise ScenarioActionError(
            f"{context} rendered a step row without {missing} "
            "(frontend test-hook may have been removed or renamed)"
        )
    return StepRef(
        id=row["stepId"],
        key=row["stepKey"],
        name=row["name"].strip(),
        kind=row["stepKind"],
        status=row["stepStatus"],
        started_at=_iso_or_none(row.get("stepStartedAt")),
        ended_at=_iso_or_none(row.get("stepEndedAt")),
        attempt_count=int(row["stepAttempts"]),
        # StepList shows the newest error first; the API lists the oldest first.
        errors=tuple(
            StepErrorRef(
                attempt=int(error["attempt"]),
                message=error["message"],
                occurred_at=_iso_or_none(error.get("occurredAt")),
            )
            for error in reversed(row.get("errors") or [])
        ),
        detail=row.get("detail"),
        has_output=row.get("stepHasOutput") == "true",
        superseded_by=row.get("supersededByTaskId") or None,
    )


async def _read_steps(entry: Locator, *, context: str) -> tuple[StepRef, ...]:
    rows = await entry.locator("[data-testid=step-row]").evaluate_all(
        _READ_STEP_ROWS_JS
    )
    return tuple(_step_ref_from_row(row, context=context) for row in rows)


async def _read_started_tasks(
    entry: Locator, *, context: str
) -> tuple[TaskLinkRef, ...]:
    items = await entry.locator("[data-testid=started-task]").evaluate_all(
        _READ_STARTED_TASKS_JS
    )
    for item in items:
        if not item.get("taskId") or not item.get("taskType"):
            raise ScenarioActionError(
                f"{context} rendered a started task without data-task-id or "
                "data-task-type (frontend test-hook may have been removed or renamed)"
            )
    return tuple(
        TaskLinkRef(
            id=item["taskId"],
            type=item["taskType"],
            result=item.get("taskResult") or None,
        )
        for item in items
    )


async def _read_timeline_entry(row: Locator) -> TimelineEntry:
    """Read one ``timeline-entry`` element of the Timeline tab."""
    task_id = await _required_attr(row, "data-task-id", context="timeline entry")
    context = f"timeline entry {task_id}"
    task_type = await _required_attr(row, "data-task-type", context=context)
    task_status = await _required_attr(row, "data-task-status", context=context)
    created_on = await row.get_attribute("data-created-on")
    application_version = await row.get_attribute("data-application-version")
    started_by_step_id = await row.get_attribute("data-started-by-step-id")
    result = await _required_attr(row, "data-task-result", context=context)
    started_by_task_id = await row.get_attribute("data-started-by-task-id")
    started_by_task_type = await row.get_attribute("data-started-by-task-type")
    return TimelineEntry(
        task_id=task_id,
        task_type=task_type,
        task_status=task_status,
        application_version=application_version or None,
        created_on=created_on or None,
        steps=await _read_steps(row, context=context),
        started_by_step_id=started_by_step_id or None,
        result=result,
        # The timeline shows only the type of the starting task.
        started_by=(
            TaskLinkRef(
                id=started_by_task_id, type=started_by_task_type or "", result=None
            )
            if started_by_task_id
            else None
        ),
        started_tasks=await _read_started_tasks(row, context=context),
    )


class DeploymentDetailPage:
    """Deployment detail — status, Upgrade, Timeline tab, Backups tab, Restores tab."""

    def __init__(self, page: Page, *, keystroke_delay_ms: int | None = None) -> None:
        self._page = page
        self._keystroke_delay_ms = keystroke_delay_ms

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
        await wait_for_dialog_open(
            self._page.get_by_role("dialog", name="Upgrade Deployment")
        )

    async def confirm_upgrade(
        self, *, version: str, driver_version_id: str | None = None
    ) -> None:
        """Fill the New Version input and click Upgrade inside the dialog.

        When ``driver_version_id`` is given, pin that driver version through
        the dialog's picker instead of the default "Latest (auto)" option.
        """
        dialog = self._page.get_by_role("dialog", name="Upgrade Deployment")
        await enter_text(
            dialog.get_by_label("New Version"),
            version,
            keystroke_delay_ms=self._keystroke_delay_ms,
        )
        if driver_version_id is not None:
            await dialog.get_by_test_id("upgrade-driver-version-select").click()
            # SelectItem mirrors its value to data-value; the popup renders in
            # a portal outside the dialog element, so locate page-wide.
            await self._page.locator(f'[data-value="{driver_version_id}"]').click()
        await submit_dialog(dialog, button="Upgrade")

    async def read_pinned_image_warning(self, target_version: str) -> list[str]:
        """Open the Upgrade dialog, type ``target_version``, and return the
        sorted components the "Pinned image overrides" notice lists (empty when
        it is absent); cancels without upgrading."""
        await self.open_upgrade_dialog()
        dialog = self._page.get_by_role("dialog", name="Upgrade Deployment")
        await enter_text(
            dialog.get_by_label("New Version"),
            target_version,
            keystroke_delay_ms=self._keystroke_delay_ms,
        )
        # The notice renders from the same query as the page header, so it is
        # already settled once the dialog is open.
        entries = await dialog.get_by_test_id("pinned-image-override").all()
        components = [
            await _required_attr(entry, "data-component", context="pinned override")
            for entry in entries
        ]
        await dialog.get_by_role("button", name="Cancel", exact=True).click()
        await dialog.wait_for(state="hidden")
        return sorted(components)

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
        await wait_for_dialog_open(
            self._page.get_by_role("dialog", name="Edit Scheduling")
        )

    async def save_scheduling_config(self) -> None:
        dialog = self._page.get_by_role("dialog", name="Edit Scheduling")
        await dialog.get_by_role("button", name="Save", exact=True).click()
        # The dialog closes on server-accepted mutation. An error surfaces
        # as an inline <Alert> that keeps the dialog open — surface that as
        # a ScenarioActionError so callers see the backend message. Playwright
        # raises ``TimeoutError`` (not ``AssertionError``) on ``wait_for``,
        # so the except clause must match the real raised type.
        try:
            await dialog.wait_for(state="hidden", timeout=30_000)
        except PlaywrightTimeoutError as exc:
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
            await enter_text(
                dialog.get_by_label("Runtime class name"),
                runtime_class,
                keystroke_delay_ms=self._keystroke_delay_ms,
            )

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
                await enter_text(
                    dialog.locator(f"#res-{variant}-{field}"),
                    "",
                    keystroke_delay_ms=self._keystroke_delay_ms,
                )
        await enter_text(
            dialog.get_by_label("Runtime class name"),
            "",
            keystroke_delay_ms=self._keystroke_delay_ms,
        )

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
                await enter_text(
                    dialog.locator(f"#res-{variant}-{field}"),
                    str(value),
                    keystroke_delay_ms=self._keystroke_delay_ms,
                )

    async def _add_scheduling_toleration(self, dialog: Locator, entry: dict) -> None:
        await dialog.get_by_role("button", name="Add toleration", exact=True).click()
        row = dialog.locator("[data-testid=toleration-row]").last
        if (key := entry.get("key")) is not None:
            await enter_text(
                row.get_by_label("Key"),
                str(key),
                keystroke_delay_ms=self._keystroke_delay_ms,
            )
        if (operator := entry.get("operator")) is not None:
            await self._select_value(row, "Operator", str(operator))
        if (value := entry.get("value")) is not None:
            await enter_text(
                row.get_by_label("Value"),
                str(value),
                keystroke_delay_ms=self._keystroke_delay_ms,
            )
        if (effect := entry.get("effect")) is not None:
            await self._select_value(row, "Effect", str(effect))
        if (seconds := entry.get("toleration_seconds")) is not None:
            await enter_text(
                row.get_by_label("Toleration seconds (optional)"),
                str(seconds),
                keystroke_delay_ms=self._keystroke_delay_ms,
            )

    async def _add_scheduling_topology_spread(
        self, dialog: Locator, entry: dict
    ) -> None:
        await dialog.get_by_role(
            "button", name="Add topology spread constraint", exact=True
        ).click()
        row = dialog.locator("[data-testid=topology-spread-row]").last
        if (skew := entry.get("max_skew")) is not None:
            await enter_text(
                row.get_by_label("Max skew"),
                str(skew),
                keystroke_delay_ms=self._keystroke_delay_ms,
            )
        if (topology_key := entry.get("topology_key")) is not None:
            await enter_text(
                row.get_by_label("Topology key"),
                str(topology_key),
                keystroke_delay_ms=self._keystroke_delay_ms,
            )
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
                await enter_text(
                    row.get_by_label("Weight (1–100)"),
                    str(weight),
                    keystroke_delay_ms=self._keystroke_delay_ms,
                )
            term = weighted.get("term")
            if isinstance(term, dict):
                await self._fill_affinity_term(row, kind, term)

    async def _fill_affinity_term(self, row: Locator, kind: str, term: dict) -> None:
        topology_key = term.get("topology_key")
        if kind != "node_affinity" and topology_key is not None:
            await enter_text(
                row.get_by_label("Topology key"),
                str(topology_key),
                keystroke_delay_ms=self._keystroke_delay_ms,
            )

        if kind in ("pod_affinity", "pod_anti_affinity"):
            # The target-mode selector only appears on pod-affinity rows.
            if term.get("deployment_ref"):
                await self._select_value(row, "Target by", "Deployment")
                dep_ref = term["deployment_ref"]
                if dep_id := dep_ref.get("deployment_id"):
                    await enter_text(
                        row.get_by_label("Deployment ID"),
                        str(dep_id),
                        keystroke_delay_ms=self._keystroke_delay_ms,
                    )
                if dep_name := dep_ref.get("deployment_name"):
                    await enter_text(
                        row.get_by_label("Deployment name (alternative)"),
                        str(dep_name),
                        keystroke_delay_ms=self._keystroke_delay_ms,
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
            await enter_text(
                ml_row.locator("input[placeholder='key']"),
                str(key),
                keystroke_delay_ms=self._keystroke_delay_ms,
            )
            await enter_text(
                ml_row.locator("input[placeholder='value']"),
                str(value),
                keystroke_delay_ms=self._keystroke_delay_ms,
            )

        match_expressions = label_selector.get("match_expressions") or []
        for expr in match_expressions:
            await row.get_by_role(
                "button", name="Add match expression", exact=True
            ).click()
            expr_row = row.locator("[data-testid=match-expression-row]").last
            if (k := expr.get("key")) is not None:
                await enter_text(
                    expr_row.locator("input[placeholder='key']"),
                    str(k),
                    keystroke_delay_ms=self._keystroke_delay_ms,
                )
            if (op := expr.get("operator")) is not None:
                # Each expression row contains exactly one combobox (the
                # operator Select); scope to the row and click it.
                await expr_row.get_by_role("combobox").click()
                await self._page.get_by_role("option", name=op, exact=True).click()
            values = expr.get("values") or []
            if values:
                await enter_text(
                    expr_row.locator("input[placeholder='values (comma-separated)']"),
                    ",".join(str(v) for v in values),
                    keystroke_delay_ms=self._keystroke_delay_ms,
                )

    # ------------------------------------------------------------------
    # Settings drawer — component overrides (017 env vars, 018 image, 022 command/args)
    # ------------------------------------------------------------------

    async def set_component_env_vars(
        self, *, component: str, env_vars: dict[str, str]
    ) -> None:
        """Make ``component``'s env var rows in the Settings edit drawer equal
        ``env_vars``, then apply through the diff dialog.

        Rows are edited in place by index and extras removed from the end; a
        block left with no env vars, image, command or args is removed. Closes
        the drawer without submitting when the rows already match.
        """
        drawer, block = await self._open_component_override_block(component)
        add_block = block.locator(f"[data-testid=component-override-add-{component}]")
        add_row = block.locator(f"[data-testid=comp-env-add-{component}]")
        await expect(add_block.or_(add_row)).to_be_visible()

        rows = block.locator("[data-testid=component-env-var-row]")
        current: list[tuple[str, str]] = []
        for index in range(await rows.count()):
            name_input = block.locator(
                f"[data-testid=comp-env-name-{component}-{index}]"
            )
            value_input = block.locator(
                f"[data-testid=comp-env-value-{component}-{index}]"
            )
            current.append(
                (await name_input.input_value(), await value_input.input_value())
            )
        desired = list(env_vars.items())
        if current == desired:
            await self._close_config_drawer(drawer)
            return

        if await add_block.is_visible():
            await add_block.click()
        for index, (name, value) in enumerate(desired):
            if index >= len(current):
                await add_row.click()
            await enter_text(
                block.locator(f"[data-testid=comp-env-name-{component}-{index}]"),
                name,
                keystroke_delay_ms=self._keystroke_delay_ms,
            )
            value_input = block.locator(
                f"[data-testid=comp-env-value-{component}-{index}]"
            )
            await enter_text(
                value_input, value, keystroke_delay_ms=self._keystroke_delay_ms
            )
            await value_input.press("Tab")
        for index in range(len(current) - 1, len(desired) - 1, -1):
            await block.locator(
                f"[data-testid=comp-env-remove-{component}-{index}]"
            ).click()

        if not desired:
            await self._remove_component_block_if_empty(block, component)
        await self._apply_config_drawer(drawer, what="component env var")

    async def set_component_image(self, *, component: str, image: str | None) -> None:
        """Fill (or clear, for ``None``) ``component``'s Image input in the
        Settings edit drawer, then apply through the diff dialog.

        A block left with no image, env vars, command or args is removed.
        Closes the drawer without submitting when the input already matches.
        """
        drawer, block = await self._open_component_override_block(component)
        add_block = block.locator(f"[data-testid=component-override-add-{component}]")
        image_input = block.get_by_label(f"Image for {component}", exact=True)
        await expect(add_block.or_(image_input)).to_be_visible()

        current = (
            await image_input.input_value() if await image_input.is_visible() else ""
        )
        desired = image or ""
        if current == desired:
            await self._close_config_drawer(drawer)
            return

        if await add_block.is_visible():
            await add_block.click()
        await enter_text(
            image_input, desired, keystroke_delay_ms=self._keystroke_delay_ms
        )
        await image_input.press("Tab")
        error = block.locator(f"[data-testid=comp-image-error-{component}]")
        if await error.count() > 0:
            raise ScenarioActionError(
                f"image {desired!r} rejected inline: {await error.inner_text()}"
            )

        if not desired:
            await self._remove_component_block_if_empty(block, component)
        await self._apply_config_drawer(drawer, what="component image")

    async def set_component_replicas(
        self, *, component: str, replicas: int | None
    ) -> None:
        """Fill (or clear, for ``None``) ``component``'s Replicas field in the
        Settings edit drawer, then apply through the diff dialog.

        A block left with no override is removed. Closes the drawer without
        submitting when the field already matches. Raises
        ``ScenarioActionError`` when the field is read-only (singleton).
        """
        drawer, block = await self._open_component_override_block(component)
        replicas_input = block.locator(f"[data-testid=comp-replicas-{component}]")
        await expect(replicas_input).to_be_visible()
        if await replicas_input.get_attribute("readonly") is not None:
            await self._close_config_drawer(drawer)
            raise ScenarioActionError(
                f"the Replicas field of {component!r} is read-only: "
                f"{await replicas_input.input_value()!r}"
            )

        desired = "" if replicas is None else str(replicas)
        if await replicas_input.input_value() == desired:
            await self._close_config_drawer(drawer)
            return

        # Typing into a component without a block creates the block and re-renders the field.
        await enter_text(
            replicas_input, desired, keystroke_delay_ms=self._keystroke_delay_ms
        )
        await expect(replicas_input).to_have_value(desired)
        await replicas_input.press("Tab")
        error = block.locator(f"[data-testid=comp-replicas-error-{component}]")
        if await error.count() > 0:
            raise ScenarioActionError(
                f"replicas {desired!r} rejected inline: {await error.inner_text()}"
            )

        if not desired:
            await self._remove_component_block_if_empty(block, component)
        await self._apply_config_drawer(drawer, what="component replicas")

    async def read_component_replicas_field(self, *, component: str) -> dict[str, Any]:
        """Open the Settings edit drawer, read ``component``'s Replicas field
        (``value``, ``read_only``) and close the drawer without changes."""
        drawer, block = await self._open_component_override_block(component)
        replicas_input = block.locator(f"[data-testid=comp-replicas-{component}]")
        await expect(replicas_input).to_be_visible()
        field = {
            "value": await replicas_input.input_value(),
            "read_only": await replicas_input.get_attribute("readonly") is not None,
        }
        await self._close_config_drawer(drawer)
        return field

    async def read_component_replicas_summary(self) -> dict[str, str]:
        """Open the Settings tab and read each replicas line of the Component
        Overrides card: ``{component: "2 (override)", ...}``."""
        await self._page.get_by_role("button", name="Settings", exact=True).click()
        lines = self._page.locator("[data-testid=component-replicas]")
        await expect(lines.first).to_be_visible()
        pairs = await lines.evaluate_all(
            """rows => rows.map(row => [
              row.dataset.component,
              row.querySelector('[data-testid=component-replicas-value]')?.textContent ?? '',
            ])"""
        )
        return dict(pairs)

    async def show_component_overrides(self, *, component: str) -> str:
        """Open the Settings tab, scroll ``component``'s row of the Component
        Overrides card to the middle of the page and return the row's text."""
        await self._page.get_by_role("button", name="Settings", exact=True).click()
        row = self._page.locator(
            f"[data-testid=component-override-row][data-component='{component}']"
        )
        await expect(row).to_be_visible()
        await row.evaluate(
            "row => row.scrollIntoView({block: 'center', behavior: 'smooth'})"
        )
        return await row.inner_text()

    async def set_component_container_override(
        self, *, component: str, command: list[str] | None, args: list[str] | None
    ) -> None:
        """Make ``component``'s Command and Args rows in the Settings edit drawer
        equal ``command`` and ``args`` (``None`` means no rows), then apply
        through the diff dialog.

        Rows are found by their accessible names, edited in place and extras
        removed from the end. The block stays when both lists end up empty.
        Closes the drawer without submitting when the rows already match.
        """
        drawer, block = await self._open_component_override_block(component)
        add_block = block.locator(f"[data-testid=component-override-add-{component}]")
        command_editor = block.locator(
            f"[data-testid=component-command-editor-{component}]"
        )
        await expect(add_block.or_(command_editor)).to_be_visible()
        if await add_block.is_visible():
            await add_block.click()

        changed = False
        for field, label, values in (
            ("command", "Command", command or []),
            ("args", "Args", args or []),
        ):
            changed |= await self._set_component_list(
                block, component, field=field, label=label, values=values
            )

        if not changed:
            await self._close_config_drawer(drawer)
            return
        await self._apply_config_drawer(drawer, what="component command and args")

    async def _set_component_list(
        self,
        block: Locator,
        component: str,
        *,
        field: str,
        label: str,
        values: list[str],
    ) -> bool:
        """Edit one Command or Args list in place; returns whether it changed."""

        def element(index: int) -> Locator:
            return block.get_by_label(
                f"{label} element {index + 1} for {component}", exact=True
            )

        current: list[str] = []
        while await element(len(current)).count() > 0:
            current.append(await element(len(current)).input_value())
        if current == values:
            return False
        for index, value in enumerate(values):
            if index >= len(current):
                await block.locator(
                    f"[data-testid=comp-{field}-add-{component}]"
                ).click()
            await enter_text(
                element(index), value, keystroke_delay_ms=self._keystroke_delay_ms
            )
        for index in range(len(current) - 1, len(values) - 1, -1):
            await block.locator(
                f"[data-testid=comp-{field}-remove-{component}-{index}]"
            ).click()
        return True

    async def _open_component_override_block(
        self, component: str
    ) -> tuple[Locator, Locator]:
        """Open the Settings edit drawer on the component overrides section and
        expand ``component``'s block; returns ``(drawer, block)``."""
        page = self._page
        await page.get_by_role("button", name="Settings", exact=True).click()
        await page.locator("[data-testid=settings-update-button]").click()
        drawer = page.locator("[role=dialog][aria-labelledby=config-edit-drawer-title]")
        await expect(drawer).to_be_visible()
        await page.locator("[data-testid=section-nav-componentOverrides]").click()

        trigger = page.locator(f"[data-testid=component-override-trigger-{component}]")
        if await trigger.get_attribute("aria-expanded") != "true":
            await trigger.click()
        block = page.locator(
            f"[data-testid=component-override-block][data-component='{component}']"
        )
        return drawer, block

    async def _remove_component_block_if_empty(
        self, block: Locator, component: str
    ) -> None:
        remaining = block.locator(
            "[data-testid=component-env-var-row], "
            f"[data-testid^='comp-command-{component}-'], "
            f"[data-testid^='comp-args-{component}-']"
        )
        image_input = block.locator(f"[data-testid=comp-image-{component}]")
        has_image = await image_input.count() > 0 and bool(
            await image_input.input_value()
        )
        # A singleton's read-only "1 (singleton)" field is not an override.
        replicas_input = block.locator(
            f"[data-testid=comp-replicas-{component}]:not([readonly])"
        )
        has_replicas = await replicas_input.count() > 0 and bool(
            await replicas_input.input_value()
        )
        if await remaining.count() == 0 and not has_image and not has_replicas:
            await block.locator(
                f"[data-testid=component-override-remove-{component}]"
            ).click()

    async def _close_config_drawer(self, drawer: Locator) -> None:
        await self._page.locator("[data-testid=drawer-close-button]").click()
        await expect(drawer).to_be_hidden()

    async def _apply_config_drawer(self, drawer: Locator, *, what: str) -> None:
        page = self._page
        review = page.locator("[data-testid=drawer-review-apply-button]")
        await expect(review).to_be_enabled()
        await review.click()
        diff_dialog = page.locator("[data-testid=config-diff-dialog]")
        await expect(diff_dialog).to_be_visible()
        await page.locator("[data-testid=diff-dialog-apply-button]").click()
        try:
            await expect(diff_dialog).to_be_hidden(timeout=60_000)
        except AssertionError as exc:
            problem = page.locator(
                "[data-testid=diff-dialog-error], "
                "[data-testid=diff-dialog-conflict-panel]"
            )
            message = (
                await problem.first.inner_text()
                if await problem.count() > 0
                else "(no error rendered)"
            )
            raise ScenarioActionError(
                f"{what} apply did not close the diff dialog: {message}"
            ) from exc
        await expect(drawer).to_be_hidden()

    async def _select_value(
        self, container: Locator, label_text: str, option: str
    ) -> None:
        # Base UI's Select renders the trigger as a <button role="combobox">.
        # Options appear inside a portal outside the dialog, so click handling
        # happens at the page level.
        trigger = container.get_by_label(label_text)
        await trigger.click()
        await self._page.get_by_role("option", name=option, exact=True).click()

    async def open_timeline(self) -> None:
        """Click the Timeline tab and wait for an entry or the empty placeholder."""
        # The shared Tabs component renders each tab as a plain <button>,
        # not role="tab" — target by role=button + accessible name.
        await self._page.get_by_role("button", name="Timeline", exact=True).click()
        entries = self._page.locator("[data-testid=timeline-entry]")
        placeholder = self._page.get_by_text(_TIMELINE_EMPTY_TEXT)
        await expect(entries.first.or_(placeholder)).to_be_visible()

    async def read_task_ids(self) -> set[str]:
        """Open the Timeline tab and return the id of every task it lists."""
        await self.open_timeline()
        return {task.id for task in await self._read_timeline_tasks()}

    async def show_timeline_entry(self, task_id: str) -> TimelineEntry:
        """Expand the entry of ``task_id``, scroll it to the top of the page and
        return it, with its application version and its steps.

        The Timeline tab must already be open (``open_timeline``); this method
        does not click it. Raises ``ScenarioActionError`` when the tab shows no
        entry for the task within 10 s, or when the entry does not expand after
        a click.
        """
        entry = self._page.locator(
            f"[data-testid=timeline-entry][data-task-id='{task_id}']"
        )
        try:
            await entry.wait_for(state="visible", timeout=10_000)
        except PlaywrightTimeoutError as exc:
            raise ScenarioActionError(
                f"no entry for task {task_id} on the open Timeline tab within 10 s"
            ) from exc
        if await entry.get_attribute("data-expanded") != "true":
            await entry.locator("[data-testid=timeline-entry-trigger]").first.click()
            try:
                await expect(entry).to_have_attribute("data-expanded", "true")
            except AssertionError as exc:
                raise ScenarioActionError(
                    f"the entry for task {task_id} on the open Timeline tab "
                    "did not expand after a click"
                ) from exc
        await entry.evaluate(
            "entry => entry.scrollIntoView({block: 'start', behavior: 'smooth'})"
        )
        return await _read_timeline_entry(entry)

    async def wait_for_new_task(
        self, task_type: str, *, known_task_ids: set[str], timeout: float
    ) -> str:
        """Wait until a ``task_type`` task missing from ``known_task_ids`` succeeds
        and return its id; raise when it fails or is superseded.

        Opens the Timeline tab once, then reads it every 2 s without clicking;
        the page refreshes the timeline every 10 s.
        """
        await self.open_timeline()
        deadline = time.monotonic() + timeout
        tasks: list[_TimelineTask] = []
        while time.monotonic() < deadline:
            tasks = await self._read_timeline_tasks()
            task_id = _succeeded_new_task(
                tasks, task_type=task_type, known_task_ids=known_task_ids
            )
            if task_id is not None:
                return task_id
            await asyncio.sleep(_TIMELINE_POLL_SECONDS)
        seen = [
            f"{task.id} ({task.result})"
            for task in tasks
            if task.type == task_type and task.id not in known_task_ids
        ]
        raise ScenarioTimeout(
            f"no new {task_type} task succeeded within {timeout}s; "
            f"new {task_type} tasks in the timeline: {', '.join(seen) or 'none'}"
        )

    async def _read_timeline_tasks(self) -> list[_TimelineTask]:
        rows = await self._page.locator("[data-testid=timeline-entry]").evaluate_all(
            _READ_TIMELINE_TASKS_JS
        )
        return [_timeline_task_from_row(row) for row in rows]

    async def read_timeline(self) -> list[TimelineEntry]:
        """Click the Timeline tab and read every entry from the rendered DOM.

        Relies on the ``data-task-*`` attributes attached to
        ``DeploymentTimeline`` so we don't have to reverse-map the
        human-readable type labels the UI shows to users.
        """
        await self.open_timeline()
        entries_loc = self._page.locator("[data-testid=timeline-entry]")
        count = await entries_loc.count()
        return [await _read_timeline_entry(entries_loc.nth(i)) for i in range(count)]

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

    async def read_driver_name(self) -> str | None:
        """Read the deployment's driver name from the page attributes."""
        root = self._page.locator("[data-testid=deployment-detail]").first
        await root.wait_for()
        value = await root.get_attribute("data-driver-name")
        return value or None

    async def read_header_driver_text(self) -> str:
        """Return the text rendered next to the ``Driver`` label in the header.

        Used to confirm the page shows a human-readable driver name rather
        than the underlying ``applicationDriverVersionId`` UUID.
        """
        root = self._page.locator("[data-testid=deployment-detail]").first
        await root.wait_for()
        # The label and value are adjacent <span>s under the header — match
        # the value span by anchoring on the "Driver " prefix.
        driver_label = root.locator("span", has_text="Driver ").first
        await driver_label.wait_for()
        value = driver_label.locator("span").first
        return (await value.inner_text()).strip()

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

    async def _read_parent_steps(
        self, parent: str, parent_id: str
    ) -> tuple[StepRef, ...]:
        # Scoped to the step container: a backup row also holds its restores' steps.
        container = self._page.locator(
            f"[data-testid={parent}-steps][data-{parent}-id='{parent_id}']"
        )
        context = f"{parent} {parent_id} steps"
        if await container.count() == 0:
            raise ScenarioActionError(
                f"{context}: no {parent}-steps container "
                "(frontend test-hook may have been removed or renamed)"
            )
        return await _read_steps(container, context=context)

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
                    return BackupRef(
                        id=backup_id,
                        name=name,
                        status=status,
                        steps=await self._read_parent_steps("backup", backup_id),
                    )
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
            steps=await self._read_parent_steps("backup", backup_id),
        )

    async def read_backups(self) -> tuple[BackupRef, ...]:
        """Open the Backups tab and read every backup row, in the order listed."""
        await self.open_backups_tab()
        rows = self._page.locator("[data-testid=backup-row]")
        placeholder = self._page.get_by_text("No backups yet", exact=True)
        await expect(rows.first.or_(placeholder)).to_be_visible()

        refs: list[BackupRef] = []
        for i in range(await rows.count()):
            row = rows.nth(i)
            backup_id = await _required_attr(
                row, "data-backup-id", context="backup row"
            )
            context = f"backup row {backup_id}"
            refs.append(
                BackupRef(
                    id=backup_id,
                    name=await _required_attr(row, "data-backup-name", context=context),
                    status=await _required_attr(
                        row, "data-backup-status", context=context
                    ),
                    application_version=await _required_attr(
                        row, "data-backup-application-version", context=context
                    ),
                )
            )
        return tuple(refs)

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
                    return RestoreRef(
                        id=restore_id,
                        status=status,
                        steps=await self._read_parent_steps("restore", restore_id),
                    )
            await asyncio.sleep(2.0)
        raise ScenarioTimeout(
            f"restore {restore_id} did not reach a terminal status within {max_wait}s"
        )

    async def open_restores_tab(self) -> None:
        # There is no separate Restores tab today — restores are shown under
        # their parent backup in the Backups tab. Alias for clarity in
        # scenarios that expect one.
        await self.open_backups_tab()

    # ------------------------------------------------------------------
    # Deletion (spec 008)
    # ------------------------------------------------------------------

    def _delete_button(self) -> Locator:
        return self._page.locator("[data-testid=delete-deployment-button]")

    def _delete_dialog(self) -> Locator:
        return self._page.locator("[data-testid=delete-deployment-dialog]")

    def _delete_confirm_input(self) -> Locator:
        return self._page.locator("[data-testid=delete-deployment-confirm-input]")

    def _delete_confirm_button(self) -> Locator:
        return self._page.locator("[data-testid=delete-deployment-confirm-button]")

    async def open_delete_dialog(self) -> None:
        """Click the header Delete button and wait for the type-to-confirm dialog."""
        await self._delete_button().click()
        await wait_for_dialog_open(self._delete_dialog())

    async def delete_confirm_button_is_disabled(self) -> bool:
        """Return True if the destructive confirm button is currently disabled."""
        return await self._delete_confirm_button().is_disabled()

    async def fill_delete_confirm(self, text: str) -> None:
        """Type *text* into the type-to-confirm input."""
        await enter_text(
            self._delete_confirm_input(),
            text,
            keystroke_delay_ms=self._keystroke_delay_ms,
        )

    async def confirm_delete(self) -> None:
        """Click the dialog's destructive Delete button. Dialog must close."""
        await self._delete_confirm_button().click()
        await self._delete_dialog().wait_for(state="hidden")

    async def has_deleted_banner(self) -> bool:
        """Return True if the tombstone banner ('Deleted at <ts>') is rendered."""
        return await self._page.locator("[data-testid=deleted-banner]").count() > 0

    async def wait_for_deleted_banner(self, *, timeout: float = 30.0) -> None:
        """Block until the tombstone banner is visible.

        ``goto()`` only triggers navigation; the page's GraphQL query is
        still in flight when control returns. Without this wait,
        ``has_deleted_banner()`` races the data fetch and reads the
        empty DOM before the banner mounts.
        """
        banner = self._page.locator("[data-testid=deleted-banner]")
        try:
            await expect(banner).to_be_visible(timeout=int(timeout * 1000))
        except AssertionError as exc:
            raise ScenarioTimeout(
                f"'Deleted at …' banner did not render within {timeout}s"
            ) from exc

    async def has_deleting_banner(self) -> bool:
        """Return True if the in-progress banner ('Deleting...') is rendered."""
        return await self._page.locator("[data-testid=deleting-banner]").count() > 0

    async def assert_action_buttons_disabled(self) -> None:
        """Assert every header action button is disabled.

        Spec 008 US12 / FR-033: a tombstoned deployment's detail page MUST
        disable every lifecycle action button (Delete, Upgrade, Create
        Backup, etc.). The dialog's per-backup Restore / Delete
        buttons are also expected to be disabled, but are only present
        once the Backups tab is opened — covered by a separate helper so
        callers can scope the assertion.

        Note: the standalone "Scheduling" header button was removed in
        feature 011's unified-Settings cleanup (scheduling now lives
        inside the Settings drawer). It is no longer in this list.
        """
        for button_name in ("Delete", "Upgrade"):
            btn = self._page.get_by_role("button", name=button_name, exact=True).first
            assert await btn.is_disabled(), (
                f"{button_name} button should be disabled on tombstoned "
                "deployment detail page"
            )
