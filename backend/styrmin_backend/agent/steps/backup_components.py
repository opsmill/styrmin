"""One step per component of a Velero backup, from its PodVolumeBackups (spec 019, research D13).

Velero backs up the whole namespace and creates one PodVolumeBackup per pod
volume. Each pod belongs to a component through its ``styrmin/component``
label. A component's step starts at its earliest item, ends at its latest
item once all have ended, and fails when any item failed. A component that
has not ended when the backup ends gets the backup's result and times.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from styrmin_backend.agent.service.kubernetes.velero.client import failure_message
from styrmin_backend.agent.steps.reporter import StepReporter
from styrmin_backend.domain.steps import backup_component_step

#: The pod label that names the component a pod belongs to.
COMPONENT_LABEL = "styrmin/component"
_FAILED_PHASES = frozenset({"Failed", "Canceled"})
_ENDED_PHASES = _FAILED_PHASES | {"Completed"}

ListItems = Callable[[], Awaitable[list[dict[str, Any]]]]
ComponentOfPod = Callable[[str, str], Awaitable[str | None]]


@dataclass(frozen=True)
class ComponentProgress:
    """How far a component's backup is; ``error`` is set when it failed."""

    started_at: datetime | None = None
    ended_at: datetime | None = None
    error: str | None = None


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _item_error(item: Mapping[str, Any]) -> str:
    spec = item.get("spec") or {}
    status = item.get("status") or {}
    volume = f"{(spec.get('pod') or {}).get('name', '')}/{spec.get('volume', '')}"
    reason = status.get("message") or f"phase {status.get('phase', '')}"
    return f"Pod volume {volume}: {reason}"


def component_progress(items: Sequence[Mapping[str, Any]]) -> ComponentProgress:
    """The progress of one component from the PodVolumeBackups of its pods."""
    statuses = [item.get("status") or {} for item in items]
    starts = [t for s in statuses if (t := _timestamp(s.get("startTimestamp")))]
    ends = [t for s in statuses if (t := _timestamp(s.get("completionTimestamp")))]
    ended = bool(items) and all(s.get("phase") in _ENDED_PHASES for s in statuses)
    started_at = min(starts or (ends if ended else []), default=None)
    if not ended:
        return ComponentProgress(started_at=started_at)
    errors = [
        _item_error(item)
        for item, status in zip(items, statuses, strict=True)
        if status.get("phase") in _FAILED_PHASES
    ]
    ended_at = max(ends, default=None) if started_at is not None else None
    return ComponentProgress(started_at, ended_at, "; ".join(errors) or None)


class PodComponents:
    """The component of each pod, from its ``styrmin/component`` label.

    Lists the namespace's pods once, and again when asked about a pod it has not seen.
    """

    def __init__(self, core_api: Any) -> None:
        self._core_api = core_api
        self._components: dict[tuple[str, str], str | None] = {}

    async def component_of(self, namespace: str, pod: str) -> str | None:
        if (namespace, pod) not in self._components:
            pods = await self._core_api.list_namespaced_pod(
                namespace=namespace, label_selector=COMPONENT_LABEL
            )
            for item in pods.items:
                labels = item.metadata.labels or {}
                self._components[(namespace, item.metadata.name)] = labels.get(
                    COMPONENT_LABEL
                )
            self._components.setdefault((namespace, pod), None)
        return self._components[(namespace, pod)]


class BackupComponentSteps:
    """Records a ``backup:component:<name>`` step for each component of one backup.

    A failure here never fails the backup: it is logged and the backup goes on.
    """

    def __init__(
        self,
        reporter: StepReporter,
        components: Sequence[str],
        *,
        list_items: ListItems,
        component_of_pod: ComponentOfPod,
    ) -> None:
        self._reporter = reporter
        self._components = list(dict.fromkeys(components))
        self._list_items = list_items
        self._component_of_pod = component_of_pod
        self._progress: dict[str, ComponentProgress] = {}
        self._started: set[str] = set()
        self._ended: set[str] = set()

    @property
    def _enabled(self) -> bool:
        return self._reporter.enabled and bool(self._components)

    async def on_poll(self, backup: dict[str, Any]) -> None:
        """``poll_backup_status`` callback: record each component's progress."""
        del backup  # The PodVolumeBackups carry the progress.
        if not self._enabled:
            return
        try:
            items = await self._items_by_component()
            for component in self._components:
                progress = component_progress(items.get(component, []))
                self._progress[component] = progress
                await self._record(component, progress)
        except Exception as exc:  # noqa: BLE001 - a step write never fails the backup
            logger.warning("Could not record the backup's component steps: {}", exc)

    async def finish(self, backup: dict[str, Any]) -> None:
        """End each component that has not ended with the backup's result and times."""
        if not self._enabled:
            return
        try:
            status = backup.get("status") or {}
            now = datetime.now(UTC)
            started_at = _timestamp(status.get("startTimestamp")) or now
            ended_at = _timestamp(status.get("completionTimestamp")) or now
            error = (
                None
                if status.get("phase") == "Completed"
                else failure_message("backup", status)
            )
            for component in self._components:
                if component in self._ended:
                    continue
                progress = self._progress.get(component, ComponentProgress())
                if progress.ended_at is None:
                    start = progress.started_at or started_at
                    progress = ComponentProgress(
                        start, max(ended_at, start), progress.error or error
                    )
                await self._record(component, progress)
        except Exception as exc:  # noqa: BLE001 - a step write never fails the backup
            logger.warning("Could not end the backup's component steps: {}", exc)

    async def _items_by_component(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in await self._list_items():
            pod = (item.get("spec") or {}).get("pod") or {}
            component = await self._component_of_pod(
                pod.get("namespace", ""), pod.get("name", "")
            )
            if component is not None:
                grouped.setdefault(component, []).append(item)
        return grouped

    async def _record(self, component: str, progress: ComponentProgress) -> None:
        """Send what changed; a write that was not recorded is sent again next time."""
        if progress.started_at is None or component in self._ended:
            return
        step = backup_component_step(component)
        if component not in self._started:
            if await self._reporter.start_step(*step, at=progress.started_at) is None:
                return
            self._started.add(component)
        if progress.ended_at is None:
            return
        if progress.error is None:
            ended = await self._reporter.succeed_step(step.key, at=progress.ended_at)
        else:
            ended = await self._reporter.fail_step(
                step.key, progress.error, at=progress.ended_at
            )
        if ended is not None:
            self._ended.add(component)
