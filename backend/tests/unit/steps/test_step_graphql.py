"""The ``Step`` GraphQL type, ``Query.step`` and ``Mutation.recordStep`` resolvers (spec 019).

Resolvers are called directly with a real unit of work; the propagation tests
through the HTTP API are in ``tests/functional/graphql``.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from styrmin_backend.api.definitions.step.model import RecordStepInput
from styrmin_backend.api.definitions.step.model import Step as StepType
from styrmin_backend.api.definitions.task.model import Task as TaskGraphQLType
from styrmin_backend.api.schema.mutation import Mutation
from styrmin_backend.api.schema.query import Query
from styrmin_backend.db.models import DeploymentStatus
from styrmin_backend.domain.models import (
    Step,
    StepError,
    StepEvent,
    StepKind,
    StepParent,
    StepStatus,
    Task,
    TaskResult,
    TaskType,
)
from styrmin_backend.services.steps.exceptions import StepNotFoundError
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork
from tests.unit.steps.conftest import Parents

T0 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def _info(uow: SqlModelUnitOfWork) -> Any:
    return SimpleNamespace(context={"uow": uow})


async def _save(uow: SqlModelUnitOfWork, step: Step) -> Step:
    await uow.steps.save(step)
    await uow.session.flush()
    return step


def _failed_step(parents: Parents) -> Step:
    return Step(
        id=uuid4(),
        parent=StepParent.of_task(parents.task.id),
        key="hook:upgrade:core",
        name="Run the upgrade hook",
        kind=StepKind.HOOK,
        status=StepStatus.FAILED,
        started_at=T0,
        ended_at=T0 + timedelta(seconds=90),
        attempt_count=2,
        errors=[
            StepError(attempt=1, message="first", occurred_at=T0),
            StepError(attempt=2, message="second", occurred_at=T0),
        ],
        detail="UpgradeFailed: timed out",
        rolled_back_at=T0 + timedelta(seconds=60),
        rollback_message="rolled back",
        output="Traceback\n",
        output_truncated=True,
        superseded_by_task_id=parents.other_task.id,
    )


async def test_query_step_returns_every_field(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    step = await _save(uow, _failed_step(parents))

    result = await Query().step(step_id=step.id, info=_info(uow))

    assert result is not None
    assert (result.id, result.key, result.name) == (step.id, step.key, step.name)
    assert result.kind is StepKind.HOOK
    assert result.status is StepStatus.FAILED
    assert (result.started_at, result.ended_at) == (step.started_at, step.ended_at)
    assert result.duration_seconds() == 90.0
    assert result.attempt_count == 2
    assert [(e.attempt, e.message) for e in result.errors] == [
        (1, "first"),
        (2, "second"),
    ]
    assert result.error() == "second"
    assert result.detail == "UpgradeFailed: timed out"
    assert result.rolled_back_at == step.rolled_back_at
    assert result.rollback_message == "rolled back"
    assert result.has_output() is True
    assert result.output == "Traceback\n"
    assert result.output_truncated is True
    assert (result.task_id, result.backup_id, result.restore_id) == (
        parents.task.id,
        None,
        None,
    )


async def test_query_step_raises_for_an_unknown_id(uow: SqlModelUnitOfWork) -> None:
    with pytest.raises(StepNotFoundError):
        await Query().step(step_id=uuid4(), info=_info(uow))


def test_derived_fields_of_a_step_without_end_errors_or_output() -> None:
    step = Step.create(
        StepParent.of_backup(uuid4()),
        "backup:component:db",
        "Back up db",
        StepKind.BACKUP_COMPONENT,
        StepStatus.RUNNING,
        T0,
    )

    result = StepType.from_instance(step)

    assert result.duration_seconds() is None
    assert result.error() is None
    assert result.has_output() is False
    assert result.backup_id == step.backup_id


async def test_record_step_records_the_event(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    started = await Mutation().record_step(
        input=RecordStepInput(
            task_id=parents.task.id,
            key="plan",
            name="Plan the changes",
            kind=StepKind.PLAN,
            event=StepEvent.STARTED,
            occurred_at=T0,
        ),
        info=_info(uow),
    )
    succeeded = await Mutation().record_step(
        input=RecordStepInput(
            step_id=started.id,
            event=StepEvent.SUCCEEDED,
            occurred_at=T0 + timedelta(seconds=2),
        ),
        info=_info(uow),
    )

    assert started.status is StepStatus.RUNNING
    assert succeeded.id == started.id
    assert succeeded.status is StepStatus.SUCCEEDED
    assert succeeded.duration_seconds() == 2.0
    stored = await uow.steps.get(started.id)
    assert stored is not None
    assert stored.status is StepStatus.SUCCEEDED


async def test_relations_are_queried_when_no_view_is_set(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    step = await _save(uow, _failed_step(parents))
    started = Task.create(
        type=TaskType.START_COMPONENTS,
        deployment_id=parents.deployment_id,
        started_by_step_id=step.id,
    )
    await uow.tasks.save(started)
    await uow.session.flush()
    result = StepType.from_instance(step)

    superseded_by = await result.superseded_by(_info(uow))
    started_tasks = await result.started_tasks(_info(uow))

    assert superseded_by is not None
    assert superseded_by.id == parents.other_task.id
    assert [task.id for task in started_tasks] == [started.id]
    assert await result.no_report_since(_info(uow)) is None


async def test_no_report_since_is_queried_for_a_running_operator_step(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    step = await _save(
        uow,
        Step.create(
            StepParent.of_task(parents.task.id),
            "operator:ready",
            "Wait for the deployment to be ready",
            StepKind.OPERATOR_PHASE,
            StepStatus.RUNNING,
            T0,
        ),
    )
    uow.session.add(
        DeploymentStatus(
            deployment_id=parents.deployment_id, phase="Ready", last_polled_at=T0
        )
    )
    await uow.session.flush()

    assert await StepType.from_instance(step).no_report_since(_info(uow)) == T0


async def test_views_are_returned_without_queries(parents: Parents) -> None:
    step = _failed_step(parents)
    superseding = Task.create(type=TaskType.UPDATE_INSTANCE, deployment_id=uuid4())
    started = Task.create(type=TaskType.STOP_COMPONENTS, deployment_id=uuid4())
    no_uow = SimpleNamespace(context={})
    result = StepType.from_instance(
        step,
        superseded_by=superseding,
        started_tasks=[started],
        no_report_since=T0,
    )

    superseded_by = await result.superseded_by(no_uow)
    started_tasks = await result.started_tasks(no_uow)

    assert superseded_by is not None
    assert superseded_by.id == superseding.id
    assert [task.id for task in started_tasks] == [started.id]
    assert await result.no_report_since(no_uow) == T0
    empty = StepType.from_instance(step, started_tasks=[], no_report_since=None)
    assert await empty.started_tasks(no_uow) == []
    assert await empty.no_report_since(no_uow) is None


async def test_task_views_and_linked_results_are_returned_without_queries(
    parents: Parents,
) -> None:
    starter = Task.create(type=TaskType.UPGRADE_INSTANCE, deployment_id=uuid4())
    started = Task.create(
        type=TaskType.STOP_COMPONENTS,
        deployment_id=starter.deployment_id,
        started_by_step_id=uuid4(),
    )
    no_uow = SimpleNamespace(context={})
    results = {
        starter.id: TaskResult.SUCCEEDED,
        started.id: TaskResult.SUPERSEDED,
        parents.other_task.id: TaskResult.RUNNING,
    }
    task = TaskGraphQLType.from_instance(
        started,
        result=TaskResult.SUPERSEDED,
        started_by=starter,
        started_tasks=[],
        task_results=results,
    )
    step = StepType.from_instance(
        _failed_step(parents),
        superseded_by=parents.other_task,
        started_tasks=[started],
        task_results=results,
    )

    starting = await task.started_by(no_uow)
    superseding = await step.superseded_by(no_uow)
    (linked,) = await step.started_tasks(no_uow)

    assert await task.result(no_uow) is TaskResult.SUPERSEDED
    assert await task.started_tasks(no_uow) == []
    assert starting is not None
    assert (starting.id, await starting.result(no_uow)) == (
        starter.id,
        TaskResult.SUCCEEDED,
    )
    assert superseding is not None
    assert await superseding.result(no_uow) is TaskResult.RUNNING
    assert (linked.id, await linked.result(no_uow)) == (
        started.id,
        TaskResult.SUPERSEDED,
    )
