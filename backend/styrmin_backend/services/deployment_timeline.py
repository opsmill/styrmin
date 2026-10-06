"""Provides the deployment timeline service."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from styrmin_backend.domain.models import Step, Task, TaskResult
from styrmin_backend.services.steps.results import family_results, load_families
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
class TimelineReadModel:
    """What the timeline shows of its tasks, loaded with a fixed number of queries.

    Each part comes from one bulk query or is calculated in memory, so the
    GraphQL types read it instead of querying per task or per step (019 D14).
    It holds the timeline's tasks and every task their steps started, with
    their steps and task results.
    """

    steps_by_task: dict[UUID, list[Step]] = field(default_factory=dict)
    #: The tasks that each step started, oldest first, by step id.
    started_by_step: dict[UUID, list[Task]] = field(default_factory=dict)
    tasks: dict[UUID, Task] = field(default_factory=dict)
    results: dict[UUID, TaskResult] = field(default_factory=dict)
    steps: dict[UUID, Step] = field(default_factory=dict)

    def steps_of(self, task_id: UUID) -> list[Step]:
        """The steps of a task by start time, pending steps last."""
        return self.steps_by_task.get(task_id, [])

    def task(self, task_id: UUID) -> Task | None:
        """A loaded task; None when the read model did not load it."""
        return self.tasks.get(task_id)

    def result_of(self, task_id: UUID) -> TaskResult | None:
        """The task result of a loaded task; None when it is not loaded."""
        return self.results.get(task_id)

    def started_by(self, step_id: UUID) -> list[Task]:
        """The tasks that a loaded step started, oldest first."""
        return self.started_by_step.get(step_id, [])

    def started_tasks_of(self, task_id: UUID) -> list[Task]:
        """The tasks that the steps of a loaded task started, oldest first."""
        started = [
            task for step in self.steps_of(task_id) for task in self.started_by(step.id)
        ]
        return sorted(started, key=_creation_order)

    def starting_task(self, task: Task) -> Task | None:
        """The task whose step started ``task``; None when that step is not loaded."""
        if task.started_by_step_id is None:
            return None
        step = self.steps.get(task.started_by_step_id)
        if step is None or step.task_id is None:
            return None
        return self.tasks.get(step.task_id)


def _creation_order(task: Task) -> tuple[bool, float]:
    created_on = task.created_on
    return (created_on is None, created_on.timestamp() if created_on else 0.0)


async def load_timeline_read_model(
    tasks: Sequence[Task], uow: UnitOfWork
) -> TimelineReadModel:
    """Load the read model of ``tasks`` inside the caller's transaction.

    Two queries: the steps of the tasks, and the tasks those steps started.
    Started tasks outside ``tasks`` (another deployment) add two queries for
    their own steps and started tasks.
    """
    families = await load_families(tasks, uow)
    loaded = {task.id: task for task in tasks}
    for started in families.started_by_step.values():
        for task in started:
            loaded.setdefault(task.id, task)
    return TimelineReadModel(
        steps_by_task=families.steps_by_task,
        started_by_step=families.started_by_step,
        tasks=loaded,
        results=family_results(
            loaded.values(), families.steps_by_task, families.started_by_step
        ),
        steps={
            step.id: step
            for task_steps in families.steps_by_task.values()
            for step in task_steps
        },
    )


@dataclass
class TimelineEntry:
    """A task enriched with version and diff data for the deployment timeline."""

    task: Task
    application_version: str | None = None
    context_diff: ContextDiff | None = None
    # Shared by every entry of one timeline.
    read_model: TimelineReadModel = field(default_factory=TimelineReadModel)


async def build_deployment_timeline(
    deployment_id: UUID, uow: UnitOfWork
) -> list[TimelineEntry]:
    """Build the deployment timeline with version correlation and context diffs.

    Fetches tasks (newest-first) and application instances for a deployment,
    then correlates each task with the application version that was active
    at the time of that operation and computes context diffs between consecutive
    operations. The steps, started tasks and task results of every task come
    from the read model, loaded with a fixed number of queries.
    """
    async with uow:
        tasks = await uow.tasks.find_by_deployment(deployment_id)
        instances = await uow.application_instances.find_by_deployment(deployment_id)
        read_model = await load_timeline_read_model(tasks, uow)

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
                read_model=read_model,
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
