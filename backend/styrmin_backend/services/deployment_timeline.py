"""Provides the deployment timeline service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from styrmin_backend.domain.models import Task
from styrmin_backend.services.env_vars.patch_builder import ChartEnvCollision
from styrmin_backend.services.unit_of_work import UnitOfWork


@dataclass
class ContextChange:
    """A single change within a context diff."""

    path: str
    action: str  # "added", "removed", "modified"
    old_value: Any = None
    new_value: Any = None


@dataclass
class ContextDiff:
    """Diff between two ApplicationInstance context objects."""

    changes: list[ContextChange] = field(default_factory=list)


@dataclass
class TimelineEntry:
    """A task enriched with version and diff data for the deployment timeline.

    ``env_var_collisions`` carries chart-vs-user env var collisions detected
    during the reconcile this entry represents (US7 / FR-027). In v1 the
    field is always ``[]`` because the backend has no line-of-sight into
    the post-rendered manifest at the layer where collisions could be
    diffed (the env-var patch is shipped to FluxCD as a JSON-patch
    document and Kustomize processes it on-cluster). FR-028 explicitly
    authorises this degradation: the structured-log fallback is the
    authoritative collision signal in v1, emitted by the patch builder
    per operator-set env var key. The field is wired through to keep the
    GraphQL surface stable and unlock a future iteration that fetches
    rendered manifests post-apply, diffs them, and reports collisions
    back through the agent layer.
    """

    task: Task
    application_version: str | None = None
    context_diff: ContextDiff | None = None
    env_var_collisions: list[ChartEnvCollision] = field(default_factory=list)


async def build_deployment_timeline(
    deployment_id: UUID, uow: UnitOfWork
) -> list[TimelineEntry]:
    """Build the deployment timeline with version correlation and context diffs.

    Fetches tasks (newest-first) and application instances for a deployment,
    then correlates each task with the application version that was active
    at the time of that operation and computes context diffs between consecutive
    operations.
    """
    async with uow:
        tasks = await uow.tasks.find_by_deployment(deployment_id)
        instances = await uow.application_instances.find_by_deployment(deployment_id)

    # Build version and context data sorted chronologically
    instance_data: list[tuple[float, str, dict[str, Any] | None]] = []
    for inst in instances:
        if inst.created_on is not None:
            instance_data.append(
                (inst.created_on.timestamp(), inst.application_version, inst.context)
            )

    entries: list[TimelineEntry] = []
    for task in tasks:
        version = _correlate_version(task, instance_data)
        context_diff = _compute_task_context_diff(task, instance_data)
        entries.append(
            TimelineEntry(
                task=task,
                application_version=version,
                context_diff=context_diff,
            )
        )

    return entries


def _correlate_version(
    task: Task, instance_data: list[tuple[float, str, dict[str, Any] | None]]
) -> str | None:
    """Find the application version active at the time of a task."""
    if not instance_data or task.created_on is None:
        return None

    task_ts = task.created_on.timestamp()
    best_version: str | None = None

    for inst_ts, version, _ in instance_data:
        if inst_ts <= task_ts:
            best_version = version
        else:
            break

    if best_version is None:
        best_version = instance_data[0][1]

    return best_version


def _compute_task_context_diff(
    task: Task, instance_data: list[tuple[float, str, dict[str, Any] | None]]
) -> ContextDiff | None:
    """Compute context diff for a task based on consecutive ApplicationInstances."""
    if not instance_data or task.created_on is None:
        return None

    task_ts = task.created_on.timestamp()

    # Find the current and previous instance relative to this task
    current_idx: int | None = None
    for i, (inst_ts, _, _) in enumerate(instance_data):
        if inst_ts <= task_ts:
            current_idx = i
        else:
            break

    if current_idx is None:
        return None

    current_context = instance_data[current_idx][2]
    previous_context = instance_data[current_idx - 1][2] if current_idx > 0 else None

    if current_context is None:
        return None

    # First operation — no previous context to diff against
    if previous_context is None:
        return None

    return compute_context_diff(previous_context, current_context)


def compute_context_diff(
    previous: dict[str, Any], current: dict[str, Any]
) -> ContextDiff:
    """Compare two context dicts and return a structured diff."""
    changes: list[ContextChange] = []
    _diff_dicts(previous, current, "", changes)
    return ContextDiff(changes=changes)


def _diff_dicts(
    old: dict[str, Any],
    new: dict[str, Any],
    prefix: str,
    changes: list[ContextChange],
) -> None:
    """Recursively diff two dicts, collecting changes."""
    all_keys = set(old.keys()) | set(new.keys())

    for key in sorted(all_keys):
        path = f"{prefix}.{key}" if prefix else key
        old_val = old.get(key)
        new_val = new.get(key)

        if key not in old:
            changes.append(ContextChange(path=path, action="added", new_value=new_val))
        elif key not in new:
            changes.append(
                ContextChange(path=path, action="removed", old_value=old_val)
            )
        elif isinstance(old_val, dict) and isinstance(new_val, dict):
            _diff_dicts(old_val, new_val, path, changes)
        elif old_val != new_val:
            changes.append(
                ContextChange(
                    path=path, action="modified", old_value=old_val, new_value=new_val
                )
            )
