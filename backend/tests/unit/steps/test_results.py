"""Task result calculation over a task's family (spec 019, T065; data-model "Task result calculation")."""

from collections.abc import Sequence
from uuid import UUID, uuid4

import pytest

from styrmin_backend.domain import steps
from styrmin_backend.domain.models import (
    Step,
    StepParent,
    StepStatus,
    Task,
    TaskResult,
    TaskStatus,
    TaskType,
)
from styrmin_backend.domain.steps import StepDefinition
from styrmin_backend.services.steps.results import (
    compute_task_result,
    family_results,
    get_task_result,
    group_started_tasks,
    load_families,
    task_family,
)
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork
from tests.unit.steps.conftest import Parents

DEPLOYMENT_ID = uuid4()

PENDING, RUNNING, SUCCEEDED, FAILED, SUPERSEDED = (
    StepStatus.PENDING,
    StepStatus.RUNNING,
    StepStatus.SUCCEEDED,
    StepStatus.FAILED,
    StepStatus.SUPERSEDED,
)


def _task(
    type_: TaskType = TaskType.UPDATE_INSTANCE,
    status: TaskStatus = TaskStatus.SUCCESS,
    started_by: Step | None = None,
) -> Task:
    return Task.create(
        type=type_,
        deployment_id=DEPLOYMENT_ID,
        status=status,
        started_by_step_id=started_by.id if started_by is not None else None,
    )


def _step(
    task: Task,
    status: StepStatus = SUCCEEDED,
    definition: StepDefinition = steps.OPERATOR_READY,
    superseded_by: Task | UUID | None = None,
) -> Step:
    by_id = superseded_by.id if isinstance(superseded_by, Task) else superseded_by
    return Step.create(StepParent.of_task(task.id), *definition, status).model_copy(
        update={"superseded_by_task_id": by_id}
    )


def _result(task: Task, all_steps: Sequence[Step], all_tasks: Sequence[Task] = ()):
    steps_by_task: dict[UUID, list[Step]] = {}
    for step in all_steps:
        assert step.task_id is not None
        steps_by_task.setdefault(step.task_id, []).append(step)
    return compute_task_result(task, steps_by_task, group_started_tasks(all_tasks))


# --- One task ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([SUCCEEDED, SUCCEEDED], TaskResult.SUCCEEDED),
        ([SUCCEEDED, RUNNING], TaskResult.RUNNING),
        ([SUCCEEDED, PENDING], TaskResult.RUNNING),
        ([SUCCEEDED, FAILED], TaskResult.FAILED),
        ([SUCCEEDED, SUPERSEDED], TaskResult.SUPERSEDED),
    ],
    ids=["succeeded", "running", "pending", "failed", "superseded"],
)
def test_each_result_of_a_task_with_steps(
    statuses: list[StepStatus], expected: TaskResult
) -> None:
    task = _task()
    outside = _task()
    task_steps = [
        _step(task, status, superseded_by=outside if status is SUPERSEDED else None)
        for status in statuses
    ]

    assert _result(task, task_steps) is expected


def test_failed_helmrelease_fails_a_task_whose_flow_succeeded() -> None:
    # US3 acceptance scenario 1: Task.status keeps the Prefect flow outcome.
    task = _task(status=TaskStatus.SUCCESS)
    task_steps = [
        _step(task, SUCCEEDED, steps.STYRMIN_DEPLOYMENT_WRITE),
        _step(task, SUCCEEDED, steps.OPERATOR_PREREQUISITES),
        _step(task, FAILED, steps.OPERATOR_HELMRELEASE),
        _step(task, PENDING, steps.OPERATOR_SERVICES).model_copy(
            update={"status": SUPERSEDED, "superseded_by_task_id": uuid4()}
        ),
    ]

    assert _result(task, task_steps) is TaskResult.FAILED


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([FAILED, PENDING], TaskResult.RUNNING),
        ([FAILED, RUNNING], TaskResult.RUNNING),
        ([SUPERSEDED, RUNNING], TaskResult.RUNNING),
        ([SUPERSEDED, FAILED], TaskResult.FAILED),
    ],
    ids=[
        "pending-before-failed",
        "running-before-failed",
        "running-before-superseded",
        "failed-before-superseded",
    ],
)
def test_rules_apply_in_order(statuses: list[StepStatus], expected: TaskResult) -> None:
    task = _task()
    outside = _task()
    task_steps = [
        _step(task, status, superseded_by=outside if status is SUPERSEDED else None)
        for status in statuses
    ]

    assert _result(task, task_steps) is expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (TaskStatus.PENDING, TaskResult.RUNNING),
        (TaskStatus.RUNNING, TaskResult.RUNNING),
        (TaskStatus.SUCCESS, TaskResult.SUCCEEDED),
        (TaskStatus.FAILED, TaskResult.FAILED),
    ],
)
def test_task_without_steps_falls_back_to_its_status(
    status: TaskStatus, expected: TaskResult
) -> None:
    assert _result(_task(status=status), []) is expected


def test_step_superseded_by_a_removed_task_counts_as_outside() -> None:
    # ``superseded_by_task_id`` is set to null when the superseding task is deleted.
    task = _task()

    assert _result(task, [_step(task, SUPERSEDED)]) is TaskResult.SUPERSEDED


def test_step_superseded_by_the_task_itself_counts_as_its_own_work() -> None:
    task = _task()

    assert _result(task, [_step(task, SUPERSEDED, superseded_by=task)]) is (
        TaskResult.SUCCEEDED
    )


# --- Families ----------------------------------------------------------------------


class Upgrade:
    """The simple-app upgrade: its hook starts three tasks, each rollout interrupts the one before."""

    def __init__(self) -> None:
        self.upgrade = _task(TaskType.UPGRADE_INSTANCE)
        self.hook = _step(self.upgrade, SUCCEEDED, steps.UPGRADE_CORE_HOOK)
        self.stop = _task(TaskType.STOP_COMPONENTS, started_by=self.hook)
        self.version = _task(TaskType.UPDATE_INSTANCE, started_by=self.hook)
        self.start = _task(TaskType.START_COMPONENTS, started_by=self.hook)
        self.tasks = [self.upgrade, self.stop, self.version, self.start]
        self.steps: list[Step] = [
            self.hook,
            *self._rollout(self.upgrade, superseded_by=self.stop),
            *self._rollout(self.stop, superseded_by=self.version),
            *self._rollout(self.version, superseded_by=self.start),
            *self._rollout(self.start),
        ]

    @staticmethod
    def _rollout(task: Task, superseded_by: Task | None = None) -> list[Step]:
        """A written CR whose last operator steps a later rollout interrupted, if any."""
        later = SUPERSEDED if superseded_by is not None else SUCCEEDED
        return [
            _step(task, SUCCEEDED, steps.STYRMIN_DEPLOYMENT_WRITE),
            _step(task, SUCCEEDED, steps.OPERATOR_PREREQUISITES),
            _step(task, later, steps.OPERATOR_HELMRELEASE, superseded_by),
            _step(task, later, steps.OPERATOR_SERVICES, superseded_by),
            _step(task, later, steps.OPERATOR_READY, superseded_by),
        ]

    def replace(self, task: Task, key: str, **update: object) -> None:
        self.steps = [
            step.model_copy(update=update)
            if step.task_id == task.id and step.key == key
            else step
            for step in self.steps
        ]

    def results(self) -> dict[UUID, TaskResult]:
        return {task.id: _result(task, self.steps, self.tasks) for task in self.tasks}


def test_family_with_sibling_superseded_started_tasks_succeeds() -> None:
    upgrade = Upgrade()

    results = upgrade.results()

    assert results[upgrade.upgrade.id] is TaskResult.SUCCEEDED
    # Each interrupted started task is superseded on its own entry.
    assert results[upgrade.stop.id] is TaskResult.SUPERSEDED
    assert results[upgrade.version.id] is TaskResult.SUPERSEDED
    assert results[upgrade.start.id] is TaskResult.SUCCEEDED


def test_family_step_superseded_by_an_outside_task_supersedes_the_family() -> None:
    upgrade = Upgrade()
    later_update = _task()
    upgrade.replace(
        upgrade.start,
        steps.OPERATOR_READY.key,
        status=SUPERSEDED,
        superseded_by_task_id=later_update.id,
    )

    results = upgrade.results()

    assert results[upgrade.upgrade.id] is TaskResult.SUPERSEDED
    assert results[upgrade.start.id] is TaskResult.SUPERSEDED


def test_failed_started_task_fails_the_family() -> None:
    # US3 acceptance scenario 3.
    upgrade = Upgrade()
    upgrade.replace(upgrade.start, steps.OPERATOR_HELMRELEASE.key, status=FAILED)

    results = upgrade.results()

    assert results[upgrade.upgrade.id] is TaskResult.FAILED
    assert results[upgrade.start.id] is TaskResult.FAILED


def test_running_started_task_keeps_the_family_running() -> None:
    upgrade = Upgrade()
    upgrade.replace(upgrade.start, steps.OPERATOR_READY.key, status=RUNNING)
    upgrade.replace(upgrade.version, steps.OPERATOR_HELMRELEASE.key, status=FAILED)

    results = upgrade.results()

    assert results[upgrade.upgrade.id] is TaskResult.RUNNING
    assert results[upgrade.start.id] is TaskResult.RUNNING
    assert results[upgrade.version.id] is TaskResult.FAILED


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (TaskStatus.PENDING, TaskResult.RUNNING),
        (TaskStatus.FAILED, TaskResult.FAILED),
        (TaskStatus.SUCCESS, TaskResult.SUCCEEDED),
    ],
)
def test_started_task_without_steps_counts_by_its_status(
    status: TaskStatus, expected: TaskResult
) -> None:
    upgrade = _task(TaskType.UPGRADE_INSTANCE)
    hook = _step(upgrade, SUCCEEDED, steps.UPGRADE_CORE_HOOK)
    started = _task(TaskType.STOP_COMPONENTS, status=status, started_by=hook)

    assert _result(upgrade, [hook], [upgrade, started]) is expected


def test_family_is_collected_transitively() -> None:
    upgrade = _task(TaskType.UPGRADE_INSTANCE)
    hook = _step(upgrade, SUCCEEDED, steps.UPGRADE_CORE_HOOK)
    child = _task(TaskType.UPGRADE_INSTANCE, started_by=hook)
    child_hook = _step(child, SUCCEEDED, steps.UPGRADE_CORE_HOOK)
    grandchild = _task(TaskType.STOP_COMPONENTS, started_by=child_hook)
    all_steps = [hook, child_hook, _step(grandchild, FAILED)]
    all_tasks = [upgrade, child, grandchild]

    assert _result(upgrade, all_steps, all_tasks) is TaskResult.FAILED
    steps_by_task = {upgrade.id: [hook], child.id: [child_hook]}
    family = task_family(upgrade, steps_by_task, group_started_tasks(all_tasks))
    assert [task.id for task in family] == [upgrade.id, child.id, grandchild.id]


def test_cycle_of_started_tasks_ends() -> None:
    first = _task(TaskType.UPGRADE_INSTANCE)
    first_hook = _step(first, SUCCEEDED, steps.UPGRADE_CORE_HOOK)
    second = _task(TaskType.UPGRADE_INSTANCE, started_by=first_hook)
    second_hook = _step(second, SUCCEEDED, steps.UPGRADE_CORE_HOOK)
    # Contrived: no writer links a task to a step of its own family.
    first = first.model_copy(update={"started_by_step_id": second_hook.id})
    looped = _step(second, SUPERSEDED, superseded_by=first)
    all_steps = [first_hook, second_hook, looped]
    all_tasks = [first, second]

    assert _result(first, all_steps, all_tasks) is TaskResult.SUCCEEDED
    assert _result(second, all_steps, all_tasks) is TaskResult.SUCCEEDED


def test_task_started_by_its_own_step_is_counted_once() -> None:
    task = _task(TaskType.UPGRADE_INSTANCE)
    hook = _step(task, SUCCEEDED, steps.UPGRADE_CORE_HOOK)
    task = task.model_copy(update={"started_by_step_id": hook.id})

    family = task_family(task, {task.id: [hook]}, group_started_tasks([task]))

    assert [member.id for member in family] == [task.id]


def test_family_results_gives_each_task_its_own_family_result() -> None:
    upgrade = Upgrade()
    steps_by_task: dict[UUID, list[Step]] = {}
    for step in upgrade.steps:
        assert step.task_id is not None
        steps_by_task.setdefault(step.task_id, []).append(step)

    results = family_results(
        upgrade.tasks, steps_by_task, group_started_tasks(upgrade.tasks)
    )

    assert results == upgrade.results()
    assert list(results) == [task.id for task in upgrade.tasks]


# --- Loading a family from the database ----------------------------------------------


async def test_loaded_family_gives_the_same_result(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    upgrade = Upgrade()
    upgrade.tasks = [
        task.model_copy(update={"deployment_id": parents.deployment_id})
        for task in upgrade.tasks
    ]
    # Foreign keys: started tasks need the hook step, superseded steps their task.
    await uow.tasks.save(upgrade.tasks[0])
    await uow.session.flush()
    await uow.steps.insert_if_absent(upgrade.hook)
    for task in upgrade.tasks[1:]:
        await uow.tasks.save(task)
    await uow.session.flush()
    for step in upgrade.steps:
        await uow.steps.insert_if_absent(step)
    await uow.commit()

    families = await load_families([upgrade.upgrade], uow)

    assert set(families.steps_by_task) == {task.id for task in upgrade.tasks}
    assert {task.id for task in families.started_by_step[upgrade.hook.id]} == {
        upgrade.stop.id,
        upgrade.version.id,
        upgrade.start.id,
    }
    assert await get_task_result(upgrade.upgrade, uow) is TaskResult.SUCCEEDED
    assert await get_task_result(upgrade.stop, uow) is TaskResult.SUPERSEDED


async def test_loaded_task_without_steps_falls_back_to_its_status(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await uow.commit()

    assert await get_task_result(parents.task, uow) is TaskResult.RUNNING


def test_results_ignore_steps_outside_the_families() -> None:
    # A timeline loads the steps of every task at once.
    task, other = _task(), _task()
    steps_by_task = {task.id: [_step(task)], other.id: [_step(other, FAILED)]}

    results = family_results([task], steps_by_task, {})

    assert results == {task.id: TaskResult.SUCCEEDED}
