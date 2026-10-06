"""Task result calculation (spec 019, research D8; data-model "Task result calculation").

A task result is calculated on every read and never stored. It covers the
task's family: the task and every task its steps started, transitively. The
calculation functions are pure, so a read model can apply them to data it
loaded in bulk; ``load_families`` and ``get_task_result`` serve single reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from styrmin_backend.domain.models import StepStatus, TaskResult, TaskStatus

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from uuid import UUID

    from styrmin_backend.domain.models import Step, Task
    from styrmin_backend.services.unit_of_work import UnitOfWork

    #: The steps of each task, by task id.
    StepsByTask = Mapping[UUID, Sequence[Step]]
    #: The tasks each step started, by step id.
    StartedByStep = Mapping[UUID, Sequence[Task]]

_RESULT_OF_STATUS = {
    TaskStatus.PENDING: TaskResult.RUNNING,
    TaskStatus.RUNNING: TaskResult.RUNNING,
    TaskStatus.SUCCESS: TaskResult.SUCCEEDED,
    TaskStatus.FAILED: TaskResult.FAILED,
}
#: The rules in the order they apply; a family that matches none succeeded.
_RULE_ORDER = (TaskResult.RUNNING, TaskResult.FAILED, TaskResult.SUPERSEDED)


def group_started_tasks(tasks: Iterable[Task]) -> dict[UUID, list[Task]]:
    """The tasks that a step started, by the step's id; tasks no step started are left out."""
    started_by_step: dict[UUID, list[Task]] = {}
    for task in tasks:
        if task.started_by_step_id is not None:
            started_by_step.setdefault(task.started_by_step_id, []).append(task)
    return started_by_step


def task_family(
    task: Task, steps_by_task: StepsByTask, started_by_step: StartedByStep
) -> list[Task]:
    """The task, then every task its steps started, transitively; each task once."""
    family = [task]
    seen = {task.id}
    for member in family:  # Grows while it is walked, breadth first.
        for step in steps_by_task.get(member.id, ()):
            for started in started_by_step.get(step.id, ()):
                if started.id not in seen:
                    seen.add(started.id)
                    family.append(started)
    return family


def _signals(
    member: Task, family_ids: set[UUID], steps_by_task: StepsByTask
) -> set[TaskResult]:
    """The results that one family member's ``Task.status`` and steps call for.

    The status counts even when every step succeeded: the flow can fail, or
    still run, between two steps.
    """
    signals = {_RESULT_OF_STATUS[member.status]}
    member_steps = steps_by_task.get(member.id, ())
    # Pending steps wait behind a failed step until it runs again (SC-003).
    blocked = any(step.status is StepStatus.FAILED for step in member_steps)
    for step in member_steps:
        if step.status is StepStatus.RUNNING or (
            step.status is StepStatus.PENDING and not blocked
        ):
            signals.add(TaskResult.RUNNING)
        elif step.status is StepStatus.FAILED:
            signals.add(TaskResult.FAILED)
        elif (
            step.status is StepStatus.SUPERSEDED
            and step.superseded_by_task_id not in family_ids
        ):
            signals.add(TaskResult.SUPERSEDED)
    return signals


def compute_task_result(
    task: Task, steps_by_task: StepsByTask, started_by_step: StartedByStep
) -> TaskResult:
    """The task result of ``task``, calculated on its family.

    ``steps_by_task`` must hold the steps of every family member, and
    ``started_by_step`` the tasks that each of those steps started. A step
    superseded by a family member is the family's own work and counts as done.
    """
    family = task_family(task, steps_by_task, started_by_step)
    family_ids = {member.id for member in family}
    signals: set[TaskResult] = set()
    for member in family:
        signals |= _signals(member, family_ids, steps_by_task)
    return next(
        (result for result in _RULE_ORDER if result in signals), TaskResult.SUCCEEDED
    )


def family_results(
    tasks: Iterable[Task], steps_by_task: StepsByTask, started_by_step: StartedByStep
) -> dict[UUID, TaskResult]:
    """The task result of each of ``tasks``, by task id, from data loaded in bulk.

    Runs no query. Each task gets the result of its own family, so a started
    task interrupted by a sibling is superseded while its starter is not.
    """
    return {
        task.id: compute_task_result(task, steps_by_task, started_by_step)
        for task in tasks
    }


@dataclass(frozen=True)
class TaskFamilies:
    """The steps and started tasks of one or more task families."""

    steps_by_task: dict[UUID, list[Step]] = field(default_factory=dict)
    started_by_step: dict[UUID, list[Task]] = field(default_factory=dict)

    def result_of(self, task: Task) -> TaskResult:
        return compute_task_result(task, self.steps_by_task, self.started_by_step)


async def load_families(tasks: Sequence[Task], uow: UnitOfWork) -> TaskFamilies:
    """Load the steps and started tasks of the families of ``tasks``.

    Two queries per generation of started tasks, whatever the number of tasks.
    Runs inside the caller's transaction.
    """
    families = TaskFamilies()
    seen = {task.id for task in tasks}
    generation = list(tasks)
    while generation:
        for task in generation:
            families.steps_by_task.setdefault(task.id, [])
        loaded = await uow.steps.list_by_task_ids([task.id for task in generation])
        for step in loaded:
            if step.task_id is not None:
                families.steps_by_task[step.task_id].append(step)
        started = await uow.tasks.find_started_by_steps([step.id for step in loaded])
        generation = []
        for task in started:
            if task.started_by_step_id is not None:
                families.started_by_step.setdefault(task.started_by_step_id, []).append(
                    task
                )
            if task.id not in seen:
                seen.add(task.id)
                generation.append(task)
    return families


async def get_task_result(task: Task, uow: UnitOfWork) -> TaskResult:
    """The task result of one task, loading its family."""
    async with uow:
        families = await load_families([task], uow)
    return families.result_of(task)
