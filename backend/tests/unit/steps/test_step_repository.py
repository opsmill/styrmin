"""Step repository against a real database (spec 019, T009)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import delete

from styrmin_backend.db.models import Step as StepModel
from styrmin_backend.db.models import StepKind as StepKindModel
from styrmin_backend.db.models import StepStatus as StepStatusModel
from styrmin_backend.db.models import Task as TaskModel
from styrmin_backend.domain.models import (
    Step,
    StepError,
    StepKind,
    StepParent,
    StepStatus,
    Task,
    TaskType,
)
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork
from tests.unit.steps.conftest import Parents

T0 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def _step(
    parent: StepParent,
    key: str,
    kind: StepKind = StepKind.HOOK,
    status: StepStatus = StepStatus.RUNNING,
    started_at: datetime | None = T0,
    created_on: datetime | None = None,
) -> Step:
    step = Step.create(parent, key, f"Step {key}", kind, status, started_at)
    return step.model_copy(update={"created_on": created_on})


def _without_times(step: Step | None) -> dict:
    assert step is not None
    return step.model_dump(exclude={"created_on", "updated_on"})


async def test_insert_if_absent_inserts_one_step_per_parent_and_key(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    task_parent = StepParent.of_task(parents.task.id)
    first = _step(task_parent, "plan")
    retry = _step(task_parent, "plan").model_copy(update={"name": "Retried"})

    assert await uow.steps.insert_if_absent(first) is True
    assert await uow.steps.insert_if_absent(retry) is False

    stored = await uow.steps.find_by_key(task_parent, "plan")
    assert _without_times(stored) == _without_times(first)
    for other_parent in (
        StepParent.of_task(parents.other_task.id),
        StepParent.of_backup(parents.backup_id),
        StepParent.of_restore(parents.restore_id),
    ):
        assert await uow.steps.insert_if_absent(_step(other_parent, "plan")) is True


async def test_save_inserts_and_get_returns_every_field(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    step = Step(
        id=uuid4(),
        parent=StepParent.of_task(parents.task.id),
        key="operator:helmrelease",
        name="Install or upgrade the HelmRelease",
        kind=StepKind.OPERATOR_PHASE,
        status=StepStatus.FAILED,
        started_at=T0,
        ended_at=T0 + timedelta(minutes=5),
        attempt_count=2,
        errors=[
            StepError(attempt=1, message="UpgradeFailed", occurred_at=T0),
            StepError(attempt=2, message="timeout", occurred_at=T0 + timedelta(1)),
        ],
        detail="UpgradeFailed: context deadline exceeded",
        rolled_back_at=T0 + timedelta(minutes=4),
        rollback_message="Helm rollback to previous release succeeded",
        output="line 1\nline 2",
        output_truncated=True,
        superseded_by_task_id=parents.other_task.id,
    )

    await uow.steps.save(step)
    await uow.session.flush()

    stored = await uow.steps.get(step.id)
    assert _without_times(stored) == _without_times(step)
    assert stored is not None and stored.created_on is not None
    assert await uow.steps.get(uuid4()) is None


async def test_save_updates_a_locked_step(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    parent = StepParent.of_task(parents.task.id)
    await uow.steps.insert_if_absent(_step(parent, "hook:upgrade:core"))

    locked = await uow.steps.find_by_key(parent, "hook:upgrade:core", for_update=True)
    assert locked is not None
    failed = locked.model_copy(
        update={
            "status": StepStatus.FAILED,
            "ended_at": T0 + timedelta(seconds=30),
            "errors": [StepError(attempt=1, message="boom", occurred_at=T0)],
        }
    )
    await uow.steps.save(failed)
    await uow.session.flush()

    stored = await uow.steps.get(locked.id, for_update=True)
    assert _without_times(stored) == _without_times(failed)
    assert stored is not None and stored.created_on == locked.created_on


async def test_lists_order_by_start_time_with_pending_steps_last(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    parent = StepParent.of_task(parents.task.id)
    later = _step(parent, "later", started_at=T0 + timedelta(seconds=10))
    earlier = _step(parent, "earlier", started_at=T0)
    pending_second = _step(
        parent, "pending-2", StepKind.OPERATOR_PHASE, StepStatus.PENDING, None, T0
    )
    pending_first = _step(
        parent,
        "pending-1",
        StepKind.OPERATOR_PHASE,
        StepStatus.PENDING,
        None,
        T0 - timedelta(seconds=1),
    )
    other_task_step = _step(StepParent.of_task(parents.other_task.id), "other")
    for step in (later, pending_second, earlier, pending_first, other_task_step):
        assert await uow.steps.insert_if_absent(step)

    steps = await uow.steps.list_by_task_ids([parents.task.id])
    assert [s.key for s in steps] == ["earlier", "later", "pending-1", "pending-2"]

    both = await uow.steps.list_by_task_ids([parents.task.id, parents.other_task.id])
    assert {s.key for s in both} == {s.key for s in steps} | {"other"}
    assert await uow.steps.list_by_task_ids([]) == []


async def test_backup_and_restore_lists_hold_only_their_steps(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    backup = _step(StepParent.of_backup(parents.backup_id), "backup:component:db")
    restore = _step(StepParent.of_restore(parents.restore_id), "restore:velero")
    task = _step(StepParent.of_task(parents.task.id), "plan")
    for step in (backup, restore, task):
        await uow.steps.insert_if_absent(step)

    assert [s.id for s in await uow.steps.list_by_backup(parents.backup_id)] == [
        backup.id
    ]
    assert [s.id for s in await uow.steps.list_by_restore(parents.restore_id)] == [
        restore.id
    ]


@pytest.mark.parametrize("for_update", [False, True])
async def test_open_operator_steps_of_the_deployments_other_tasks(
    uow: SqlModelUnitOfWork, parents: Parents, for_update: bool
) -> None:
    other = StepParent.of_task(parents.other_task.id)
    operator = StepKind.OPERATOR_PHASE
    pending = _step(other, "operator:services", operator, StepStatus.PENDING, None)
    running = _step(other, "operator:helmrelease", operator, StepStatus.RUNNING)
    closed = [
        _step(other, f"operator:{status.value}", operator, status)
        for status in (StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.SUPERSEDED)
    ]
    flow_step = _step(other, "resource:styrmindeployment", StepKind.RESOURCE_WRITE)
    own = _step(StepParent.of_task(parents.task.id), "operator:ready", operator)
    for step in (pending, running, *closed, flow_step, own):
        await uow.steps.insert_if_absent(step)

    steps = await uow.steps.list_open_operator_steps_for_deployment(
        parents.deployment_id, exclude_task_id=parents.task.id, for_update=for_update
    )

    assert [s.id for s in steps] == [running.id, pending.id]


@pytest.mark.parametrize(
    "parent_ids",
    [{}, {"task_id": uuid4(), "backup_id": uuid4()}],
    ids=["no-parent", "two-parents"],
)
def test_step_parent_needs_exactly_one_id(parent_ids: dict) -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        StepParent(**parent_ids)


@pytest.mark.parametrize("two_parents", [False, True], ids=["no-parent", "two-parents"])
async def test_database_rejects_a_step_without_exactly_one_parent(
    uow: SqlModelUnitOfWork, parents: Parents, two_parents: bool
) -> None:
    uow.session.add(
        StepModel(
            task_id=parents.task.id if two_parents else None,
            backup_id=parents.backup_id if two_parents else None,
            key="plan",
            name="Plan the changes",
            kind=StepKindModel.PLAN,
            status=StepStatusModel.RUNNING,
        )
    )

    with pytest.raises(IntegrityError, match="ck_step_one_parent"):
        await uow.session.flush()


async def test_deleting_a_task_removes_its_steps_and_unlinks_the_others(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    if uow.session.bind.dialect.name == "sqlite":  # type: ignore[union-attr]
        pytest.skip("The server does not enforce foreign keys on SQLite")
    deleted = StepParent.of_task(parents.other_task.id)
    hook = _step(deleted, "hook:upgrade:core")
    await uow.steps.insert_if_absent(hook)
    await uow.steps.insert_if_absent(_step(deleted, "plan", StepKind.PLAN))
    started = Task.create(
        TaskType.STOP_COMPONENTS, parents.deployment_id, started_by_step_id=hook.id
    )
    await uow.tasks.save(started)
    interrupted = _step(
        StepParent.of_task(parents.task.id), "operator:ready", StepKind.OPERATOR_PHASE
    ).model_copy(
        update={
            "status": StepStatus.SUPERSEDED,
            "superseded_by_task_id": parents.other_task.id,
        }
    )
    await uow.steps.insert_if_absent(interrupted)
    await uow.session.flush()

    await uow.session.exec(
        delete(TaskModel).where(TaskModel.id == parents.other_task.id)  # type: ignore[arg-type]
    )
    uow.session.expire_all()

    assert await uow.steps.list_by_task_ids([parents.other_task.id]) == []
    started_task = await uow.tasks.find(started.id)
    assert started_task is not None and started_task.started_by_step_id is None
    interrupted_step = await uow.steps.get(interrupted.id)
    assert interrupted_step is not None
    assert interrupted_step.superseded_by_task_id is None
