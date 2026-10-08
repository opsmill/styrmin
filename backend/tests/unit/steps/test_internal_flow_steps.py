"""Step writes from INTERNAL flows against a real database (spec 019, research D2)."""

from __future__ import annotations

import io
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from loguru import logger

from styrmin_backend.domain import steps
from styrmin_backend.domain.models import (
    Step,
    StepKind,
    StepParent,
    StepStatus,
    Task,
    TaskType,
)
from styrmin_backend.services.steps import internal_flows
from styrmin_backend.services.steps.internal_flows import (
    end_step,
    fail_open_steps,
    open_task_step,
)
from styrmin_backend.services.steps.recorder import open_step
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork
from tests.helpers.unit_of_work import yield_unit_of_work
from tests.unit.steps.conftest import Parents

T0 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


@pytest.fixture
async def committed(uow: SqlModelUnitOfWork, parents: Parents) -> Parents:
    """The parents, committed: a failed write rolls the session back."""
    await uow.commit()
    return parents


@pytest.fixture(autouse=True)
def flow_uow(monkeypatch: pytest.MonkeyPatch, uow: SqlModelUnitOfWork) -> None:
    monkeypatch.setattr(internal_flows, "get_unit_of_work", yield_unit_of_work(uow))


@pytest.fixture
def warnings_log() -> Iterator[io.StringIO]:
    sink = io.StringIO()
    handler_id = logger.add(sink, level="WARNING", format="{message}")
    yield sink
    logger.remove(handler_id)


@pytest.fixture
def broken_database(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def _get_unit_of_work() -> AsyncGenerator[None, None]:
        raise RuntimeError("database is down")
        yield

    monkeypatch.setattr(internal_flows, "get_unit_of_work", _get_unit_of_work)


async def _stored(uow: SqlModelUnitOfWork, step_id) -> Step:
    stored = await uow.steps.get(step_id)
    assert stored is not None
    return stored


# open_task_step


async def test_open_task_step_opens_a_running_step(
    uow: SqlModelUnitOfWork, committed: Parents
) -> None:
    step_id = await open_task_step(committed.task.id, steps.PLAN)
    await uow.rollback()  # Only committed writes remain.

    assert step_id is not None
    step = await _stored(uow, step_id)
    assert (step.parent, step.key, step.name, step.kind, step.status) == (
        StepParent.of_task(committed.task.id),
        "plan",
        "Plan the changes",
        StepKind.PLAN,
        StepStatus.RUNNING,
    )
    assert step.started_at is not None


async def test_open_task_step_waits_for_the_task_row(
    uow: SqlModelUnitOfWork, committed: Parents, monkeypatch: pytest.MonkeyPatch
) -> None:
    late_task = Task.create(
        type=TaskType.UPDATE_INSTANCE, deployment_id=committed.deployment_id
    )
    sleeps: list[float] = []

    async def _caller_commits_the_task(seconds: float) -> None:
        sleeps.append(seconds)
        await uow.tasks.save(late_task)
        await uow.commit()

    monkeypatch.setattr(
        internal_flows, "asyncio", SimpleNamespace(sleep=_caller_commits_the_task)
    )

    step_id = await open_task_step(late_task.id, steps.PLAN)

    assert sleeps == [internal_flows.RETRY_INTERVAL_SECONDS]
    assert step_id is not None
    assert (await _stored(uow, step_id)).parent == StepParent.of_task(late_task.id)


async def test_open_task_step_gives_up_when_the_task_never_appears(
    uow: SqlModelUnitOfWork, committed: Parents, warnings_log: io.StringIO
) -> None:
    missing = uuid4()

    step_id = await open_task_step(missing, steps.PLAN, wait_seconds=0)

    assert step_id is None
    assert await uow.steps.find_by_key(StepParent.of_task(missing), "plan") is None
    assert f"Step plan not recorded: task {missing} not found" in (
        warnings_log.getvalue()
    )


@pytest.mark.usefixtures("broken_database")
async def test_open_task_step_logs_a_write_error_and_returns_none(
    warnings_log: io.StringIO,
) -> None:
    assert await open_task_step(uuid4(), steps.PLAN) is None
    assert "database is down" in warnings_log.getvalue()


# end_step


async def test_end_step_succeeds_the_step(
    uow: SqlModelUnitOfWork, committed: Parents
) -> None:
    step_id = await open_task_step(committed.task.id, steps.PLAN)

    await end_step(step_id)
    await uow.rollback()  # Only committed writes remain.

    step = await _stored(uow, step_id)
    assert step.status is StepStatus.SUCCEEDED
    assert step.ended_at is not None


async def test_end_step_fails_the_step_with_the_error(
    uow: SqlModelUnitOfWork, committed: Parents
) -> None:
    step_id = await open_task_step(committed.task.id, steps.PLAN)

    await end_step(step_id, error="ReconciliationError: No upgrade hook")
    await uow.rollback()  # Only committed writes remain.

    step = await _stored(uow, step_id)
    assert step.status is StepStatus.FAILED
    assert [error.message for error in step.errors] == [
        "ReconciliationError: No upgrade hook"
    ]


@pytest.mark.usefixtures("broken_database")
async def test_end_step_without_a_step_writes_nothing() -> None:
    await end_step(None)
    await end_step(None, error="boom")


@pytest.mark.usefixtures("broken_database")
async def test_end_step_logs_a_write_error(warnings_log: io.StringIO) -> None:
    step_id = uuid4()

    await end_step(step_id)

    assert f"Could not end step {step_id}: database is down" in warnings_log.getvalue()


async def test_end_step_logs_an_unknown_step(
    committed: Parents, warnings_log: io.StringIO
) -> None:
    step_id = uuid4()

    await end_step(step_id)

    assert f"Could not end step {step_id}" in warnings_log.getvalue()


# fail_open_steps


async def test_fail_open_steps_fails_open_flow_steps_and_commits(
    uow: SqlModelUnitOfWork, committed: Parents
) -> None:
    parent = StepParent.of_task(committed.task.id)
    running = await open_step(
        parent, "hook:upgrade:core", "Run the upgrade hook", StepKind.HOOK, T0, uow=uow
    )
    pending_operator = Step.create(
        parent,
        "operator:ready",
        "Wait for the deployment to be ready",
        StepKind.OPERATOR_PHASE,
        StepStatus.PENDING,
        None,
    )
    await uow.steps.save(pending_operator)
    await uow.commit()

    await fail_open_steps(parent, "Deployment flow run 1 crashed: exit code 137")
    await uow.rollback()  # Only committed writes remain.

    failed = await _stored(uow, running.id)
    assert failed.status is StepStatus.FAILED
    assert [error.message for error in failed.errors] == [
        "Deployment flow run 1 crashed: exit code 137"
    ]
    assert (await _stored(uow, pending_operator.id)).status is StepStatus.PENDING


@pytest.mark.usefixtures("broken_database")
async def test_fail_open_steps_logs_a_write_error(warnings_log: io.StringIO) -> None:
    await fail_open_steps(StepParent.of_task(uuid4()), "crashed")

    assert "database is down" in warnings_log.getvalue()
