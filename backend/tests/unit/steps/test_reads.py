"""Step reads against a real database (spec 019, T013 and T078)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pytest_mock import MockerFixture

from styrmin_backend.db.models import DeploymentStatus
from styrmin_backend.domain.models import (
    Step,
    StepKind,
    StepParent,
    StepStatus,
    Task,
    TaskType,
)
from styrmin_backend.services.steps.exceptions import StepNotFoundError
from styrmin_backend.services.steps.reads import (
    get_no_report_since,
    get_started_tasks,
    get_step,
    list_steps,
    no_report_since,
    no_report_since_by_step,
)
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork
from tests.unit.steps.conftest import Parents

T0 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


async def _seed(
    uow: SqlModelUnitOfWork,
    parent: StepParent,
    key: str,
    started_at: datetime | None,
    kind: StepKind = StepKind.HOOK,
    status: StepStatus | None = None,
) -> Step:
    if status is None:
        status = StepStatus.PENDING if started_at is None else StepStatus.RUNNING
    step = Step.create(parent, key, f"Step {key}", kind, status, started_at)
    await uow.steps.save(step)
    await uow.session.flush()
    return step


async def test_get_step_returns_the_step(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    step = await _seed(uow, StepParent.of_task(parents.task.id), "plan", T0)

    found = await get_step(step.id, uow)

    assert found.id == step.id
    assert found.key == "plan"
    assert found.started_at == T0


async def test_get_step_raises_for_an_unknown_id(uow: SqlModelUnitOfWork) -> None:
    with pytest.raises(StepNotFoundError):
        await get_step(uuid4(), uow)


@pytest.mark.parametrize("parent_type", ["task", "backup", "restore"])
async def test_list_steps_returns_the_parent_steps_in_start_order(
    uow: SqlModelUnitOfWork, parents: Parents, parent_type: str
) -> None:
    parent = {
        "task": StepParent.of_task(parents.task.id),
        "backup": StepParent.of_backup(parents.backup_id),
        "restore": StepParent.of_restore(parents.restore_id),
    }[parent_type]
    late = await _seed(uow, parent, "late", T0 + timedelta(minutes=1))
    pending = await _seed(uow, parent, "pending", None)
    early = await _seed(uow, parent, "early", T0)
    await _seed(uow, StepParent.of_task(parents.other_task.id), "other", T0)

    steps = await list_steps(parent, uow)

    assert [step.id for step in steps] == [early.id, late.id, pending.id]


async def test_get_started_tasks_lists_the_tasks_a_step_started(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    hook = await _seed(uow, StepParent.of_task(parents.task.id), "hook", T0)
    started = Task.create(
        type=TaskType.STOP_COMPONENTS,
        deployment_id=parents.deployment_id,
        started_by_step_id=hook.id,
    )
    await uow.tasks.save(started)
    await uow.session.flush()

    tasks = await get_started_tasks(hook.id, uow)

    assert [task.id for task in tasks] == [started.id]


# no_report_since --------------------------------------------------------


def _operator_step(
    status: StepStatus = StepStatus.RUNNING,
    task_id: UUID | None = None,
    started_at: datetime | None = T0,
) -> Step:
    return Step.create(
        StepParent.of_task(task_id or uuid4()),
        "operator:helmrelease",
        "Install or upgrade the HelmRelease",
        StepKind.OPERATOR_PHASE,
        status,
        started_at,
    )


def test_no_report_since_returns_an_old_report_time() -> None:
    now = T0 + timedelta(minutes=5)
    last_report = now - timedelta(seconds=61)

    assert no_report_since(_operator_step(), last_report, now) == last_report


def test_no_report_since_is_none_while_reports_are_recent() -> None:
    now = T0 + timedelta(minutes=5)

    assert no_report_since(_operator_step(), now - timedelta(seconds=60), now) is None


def test_no_report_since_uses_the_step_start_without_a_report() -> None:
    assert no_report_since(_operator_step(), None, T0 + timedelta(minutes=2)) == T0


def test_no_report_since_is_none_for_a_recent_step_start_without_a_report() -> None:
    assert no_report_since(_operator_step(), None, T0 + timedelta(seconds=30)) is None


def test_no_report_since_shows_an_old_report_on_a_step_that_just_started() -> None:
    # The agent stopped reporting before the step started.
    last_report = T0 - timedelta(minutes=5)

    assert (
        no_report_since(_operator_step(), last_report, T0 + timedelta(seconds=1))
        == last_report
    )


def test_no_report_since_reads_a_stored_time_without_a_zone_as_utc() -> None:
    naive_report = datetime(2026, 10, 6, 12, 0)

    assert no_report_since(
        _operator_step(), naive_report, T0 + timedelta(minutes=2)
    ) == naive_report.replace(tzinfo=UTC)


@pytest.mark.parametrize(
    "step",
    [
        _operator_step(StepStatus.SUCCEEDED),
        _operator_step(StepStatus.FAILED),
        _operator_step(StepStatus.SUPERSEDED),
        _operator_step(StepStatus.PENDING, started_at=None),
        Step.create(
            StepParent.of_task(uuid4()),
            "hook",
            "Run the hook",
            StepKind.HOOK,
            StepStatus.RUNNING,
            T0,
        ),
    ],
    ids=["succeeded", "failed", "superseded", "pending", "flow-step"],
)
def test_no_report_since_is_none_for_other_steps(step: Step) -> None:
    assert no_report_since(step, T0, T0 + timedelta(hours=1)) is None


async def test_get_no_report_since_reads_the_deployment_last_report(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    step = await _seed(
        uow,
        StepParent.of_task(parents.task.id),
        "operator:ready",
        T0,
        kind=StepKind.OPERATOR_PHASE,
    )
    last_report = T0 + timedelta(minutes=1)
    uow.session.add(
        DeploymentStatus(
            deployment_id=parents.deployment_id,
            phase="Ready",
            last_polled_at=last_report,
        )
    )
    await uow.session.flush()

    assert await get_no_report_since(
        step, uow, now=last_report + timedelta(minutes=2)
    ) == (last_report)
    assert await get_no_report_since(step, uow, now=last_report) is None


async def test_get_no_report_since_uses_the_step_start_without_a_report(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    step = await _seed(
        uow,
        StepParent.of_task(parents.task.id),
        "operator:prerequisites",
        T0,
        kind=StepKind.OPERATOR_PHASE,
    )

    assert await get_no_report_since(step, uow, now=T0 + timedelta(minutes=2)) == T0
    assert await get_no_report_since(step, uow, now=T0 + timedelta(seconds=30)) is None


# no_report_since_by_step (the timeline read model) ----------------------


async def test_no_report_since_by_step_reads_the_last_reports_in_one_query(
    uow: SqlModelUnitOfWork, parents: Parents, mocker: MockerFixture
) -> None:
    now = T0 + timedelta(minutes=10)
    last_report = now - timedelta(minutes=2)
    uow.session.add(
        DeploymentStatus(
            deployment_id=parents.deployment_id,
            phase="CreatingHelmRelease",
            last_polled_at=last_report,
        )
    )
    await uow.session.flush()
    unreported = Task.create(type=TaskType.UPGRADE_INSTANCE, deployment_id=uuid4())
    tasks = {task.id: task for task in (parents.task, parents.other_task, unreported)}
    reported = [
        _operator_step(task_id=parents.task.id),
        _operator_step(task_id=parents.other_task.id),
    ]
    never_reported = _operator_step(task_id=unreported.id)
    others = [
        _operator_step(StepStatus.SUCCEEDED, task_id=parents.task.id),
        Step.create(
            StepParent.of_task(parents.task.id),
            "hook",
            "Run the hook",
            StepKind.HOOK,
            StepStatus.RUNNING,
            T0,
        ),
    ]
    spy = mocker.spy(uow.deployment_statuses, "find_by_deployments")

    notices = await no_report_since_by_step(
        [*reported, never_reported, *others], tasks, uow, now
    )

    assert notices == {
        reported[0].id: last_report,
        reported[1].id: last_report,
        never_reported.id: T0,
    }
    spy.assert_awaited_once()


async def test_no_report_since_by_step_leaves_out_steps_with_recent_reports(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    now = T0 + timedelta(minutes=10)
    uow.session.add(
        DeploymentStatus(
            deployment_id=parents.deployment_id,
            phase="CreatingHelmRelease",
            last_polled_at=now - timedelta(seconds=10),
        )
    )
    await uow.session.flush()
    step = _operator_step(task_id=parents.task.id)

    assert (
        await no_report_since_by_step([step], {parents.task.id: parents.task}, uow, now)
        == {}
    )


async def test_find_by_deployments_reads_nothing_for_no_deployments(
    uow: SqlModelUnitOfWork,
) -> None:
    assert await uow.deployment_statuses.find_by_deployments(set()) == []
