"""Task repository: step links and finders (spec 019, T010)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlmodel import update

from styrmin_backend.db.models import Task as TaskModel
from styrmin_backend.domain.models import (
    Step,
    StepKind,
    StepParent,
    StepStatus,
    Task,
    TaskStatus,
    TaskType,
)
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork
from tests.unit.steps.conftest import Parents

T0 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


async def _set_created_on(uow: SqlModelUnitOfWork, task_id: UUID, at: datetime) -> None:
    await uow.session.exec(
        update(TaskModel).where(TaskModel.id == task_id).values(created_on=at)  # type: ignore[arg-type]
    )


async def _hook_step(uow: SqlModelUnitOfWork, task: Task, key: str) -> Step:
    step = Step.create(
        StepParent.of_task(task.id), key, key, StepKind.HOOK, StepStatus.RUNNING, T0
    )
    await uow.steps.insert_if_absent(step)
    return step


async def test_task_keeps_its_instance_and_starting_step(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    hook = await _hook_step(uow, parents.task, "hook:upgrade:core")
    started = Task.create(
        type=TaskType.STOP_COMPONENTS,
        deployment_id=parents.deployment_id,
        status=TaskStatus.RUNNING,
        instance_id=parents.instance_id,
        started_by_step_id=hook.id,
    )
    await uow.tasks.save(started)
    await uow.session.flush()

    stored = await uow.tasks.find(started.id)
    assert stored is not None
    assert stored.status is TaskStatus.RUNNING
    assert stored.instance_id == parents.instance_id
    assert stored.started_by_step_id == hook.id

    # Saving a loaded task again keeps the columns it does not change.
    await uow.tasks.save(stored.model_copy(update={"status": TaskStatus.SUCCESS}))
    await uow.session.flush()
    updated = await uow.tasks.find(started.id)
    assert updated is not None and updated.created_on == stored.created_on
    assert updated.started_by_step_id == hook.id


async def test_find_by_instance(uow: SqlModelUnitOfWork, parents: Parents) -> None:
    found = await uow.tasks.find_by_instance(parents.instance_id)

    assert found is not None and found.id == parents.task.id
    assert await uow.tasks.find_by_instance(uuid4()) is None


async def test_find_latest_by_type_returns_the_newest_task_of_that_type(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    older = Task.create(TaskType.DELETE_DEPLOYMENT, parents.deployment_id)
    newer = Task.create(TaskType.DELETE_DEPLOYMENT, parents.deployment_id)
    for task in (newer, older):
        await uow.tasks.save(task)
    await uow.session.flush()
    await _set_created_on(uow, older.id, T0)
    await _set_created_on(uow, newer.id, T0 + timedelta(minutes=1))

    found = await uow.tasks.find_latest_by_type(
        parents.deployment_id, TaskType.DELETE_DEPLOYMENT
    )

    assert found is not None and found.id == newer.id
    assert (
        await uow.tasks.find_latest_by_type(uuid4(), TaskType.DELETE_DEPLOYMENT) is None
    )
    assert (
        await uow.tasks.find_latest_by_type(parents.deployment_id, TaskType.RUN_JOB)
        is None
    )


async def test_find_started_by_steps_lists_tasks_oldest_first(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    pre = await _hook_step(uow, parents.task, "hook:upgrade:pre")
    core = await _hook_step(uow, parents.task, "hook:upgrade:core")
    stop = Task.create(
        TaskType.STOP_COMPONENTS, parents.deployment_id, started_by_step_id=core.id
    )
    start = Task.create(
        TaskType.START_COMPONENTS, parents.deployment_id, started_by_step_id=core.id
    )
    unrelated = Task.create(
        TaskType.UPDATE_INSTANCE, parents.deployment_id, started_by_step_id=pre.id
    )
    for task in (start, stop, unrelated):
        await uow.tasks.save(task)
    await uow.session.flush()
    await _set_created_on(uow, stop.id, T0)
    await _set_created_on(uow, start.id, T0 + timedelta(seconds=5))

    found = await uow.tasks.find_started_by_steps([core.id])

    assert [task.id for task in found] == [stop.id, start.id]
    assert await uow.tasks.find_started_by_steps([]) == []
