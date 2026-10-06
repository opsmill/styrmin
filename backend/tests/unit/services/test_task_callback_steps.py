"""The task callback fails the steps a dead flow left open (spec 019, data-model "Closing open steps")."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from styrmin_backend.domain.models import (
    Step,
    StepKind,
    StepParent,
    StepStatus,
    TaskStatus,
)
from styrmin_backend.services.steps.recorder import open_step, succeed_step
from styrmin_backend.services.tasks import FLOW_FAILED_MESSAGE, update_task_state
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork
from tests.unit.steps import conftest as step_fixtures
from tests.unit.steps.conftest import Parents

# The real database fixtures of the step tests (SQLite and PostgreSQL).
database_url = step_fixtures.database_url
session = step_fixtures.session
uow = step_fixtures.uow
parents = step_fixtures.parents

T0 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


async def _seed(uow: SqlModelUnitOfWork, parent: StepParent) -> dict[str, Step]:
    """A running hook, a succeeded resource write and a pending operator phase."""
    hook = await open_step(
        parent, "hook:upgrade:core", "Run the upgrade hook", StepKind.HOOK, T0, uow=uow
    )
    write = await open_step(
        parent,
        "resource:styrmindeployment",
        "Write the StyrminDeployment resource",
        StepKind.RESOURCE_WRITE,
        T0,
        uow=uow,
    )
    write = await succeed_step(write, T0, uow=uow)
    operator = Step.create(
        parent,
        "operator:ready",
        "Wait for the deployment to be ready",
        StepKind.OPERATOR_PHASE,
        StepStatus.PENDING,
        None,
    )
    await uow.steps.save(operator)
    await uow.commit()
    return {"hook": hook, "write": write, "operator": operator}


async def _statuses(
    uow: SqlModelUnitOfWork, seeded: dict[str, Step]
) -> dict[str, StepStatus]:
    await uow.rollback()  # Only committed writes remain.
    statuses = {}
    for name, step in seeded.items():
        stored = await uow.steps.get(step.id)
        assert stored is not None
        statuses[name] = stored.status
    return statuses


async def test_failed_callback_fails_the_open_flow_steps_with_the_state_message(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    seeded = await _seed(uow, StepParent.of_task(parents.task.id))
    message = "Flow run encountered an exception: RuntimeError: hook broke"

    await update_task_state(parents.task.id, "Failed", message, uow)

    assert await _statuses(uow, seeded) == {
        "hook": StepStatus.FAILED,
        "write": StepStatus.SUCCEEDED,
        "operator": StepStatus.PENDING,
    }
    hook = await uow.steps.get(seeded["hook"].id)
    assert hook is not None
    assert [error.message for error in hook.errors] == [message]
    task = await uow.tasks.find(parents.task.id)
    assert task is not None
    assert (task.status, task.message) == (TaskStatus.FAILED, message)


async def test_failed_callback_without_a_message_uses_a_default_error(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    seeded = await _seed(uow, StepParent.of_task(parents.task.id))

    await update_task_state(parents.task.id, "Failed", None, uow)

    hook = await uow.steps.get(seeded["hook"].id)
    assert hook is not None
    assert hook.status is StepStatus.FAILED
    assert [error.message for error in hook.errors] == [FLOW_FAILED_MESSAGE]


@pytest.mark.parametrize("state_name", ["Running", "Completed"])
async def test_other_callbacks_leave_the_steps_alone(
    uow: SqlModelUnitOfWork, parents: Parents, state_name: str
) -> None:
    seeded = await _seed(uow, StepParent.of_task(parents.task.id))

    await update_task_state(parents.task.id, state_name, "message", uow)

    assert await _statuses(uow, seeded) == {
        "hook": StepStatus.RUNNING,
        "write": StepStatus.SUCCEEDED,
        "operator": StepStatus.PENDING,
    }


async def test_failed_callback_leaves_the_steps_of_other_tasks_alone(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    other = await _seed(uow, StepParent.of_task(parents.other_task.id))

    await update_task_state(parents.task.id, "Failed", "boom", uow)

    assert (await _statuses(uow, other))["hook"] is StepStatus.RUNNING
