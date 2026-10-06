"""The delete service records the steps of its task (spec 019, T034)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from styrmin_backend.db.models import Deployment as DeploymentModel
from styrmin_backend.db.models import DeploymentState
from styrmin_backend.domain.models import StepKind, StepStatus, TaskStatus, TaskType
from styrmin_backend.services.deployment import delete_deployment
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork
from tests.unit.steps import conftest as step_fixtures
from tests.unit.steps.conftest import Parents

# The real database fixtures of the step tests (SQLite and PostgreSQL).
database_url = step_fixtures.database_url
session = step_fixtures.session
uow = step_fixtures.uow
parents = step_fixtures.parents


@pytest.fixture
def patch_crd(mocker):
    return mocker.patch(
        "styrmin_backend.services.deployment.patch_custom_resource", autospec=True
    )


async def test_delete_records_the_request_and_a_pending_teardown(
    uow: SqlModelUnitOfWork, parents: Parents, patch_crd
) -> None:
    before = datetime.now(UTC)

    task = await delete_deployment(parents.deployment_id, uow)

    after = datetime.now(UTC)
    patch_crd.assert_awaited_once()
    assert (task.type, task.status) == (TaskType.DELETE_DEPLOYMENT, TaskStatus.SUCCESS)
    await uow.rollback()  # Only committed writes remain.
    listed = await uow.steps.list_by_task_ids([task.id])
    assert [(step.key, step.name, step.kind, step.status) for step in listed] == [
        (
            "resource:delete-request",
            "Request the deletion",
            StepKind.RESOURCE_WRITE,
            StepStatus.SUCCEEDED,
        ),
        (
            "operator:teardown",
            "Remove the deployment's resources and namespace",
            StepKind.OPERATOR_PHASE,
            StepStatus.PENDING,
        ),
    ]
    request, teardown = listed
    assert request.started_at is not None
    assert request.ended_at is not None
    assert before <= request.started_at <= request.ended_at <= after
    assert request.attempt_count == 1
    assert (teardown.started_at, teardown.attempt_count) == (None, 0)


async def test_failed_cr_patch_records_no_task_and_no_steps(
    uow: SqlModelUnitOfWork, parents: Parents, patch_crd
) -> None:
    await uow.commit()
    patch_crd.side_effect = RuntimeError("cluster unreachable")

    with pytest.raises(RuntimeError):
        await delete_deployment(parents.deployment_id, uow)

    tasks = await uow.tasks.find_by_deployment(parents.deployment_id)
    assert TaskType.DELETE_DEPLOYMENT not in {task.type for task in tasks}
    assert await uow.steps.list_by_task_ids([task.id for task in tasks]) == []


async def test_repeated_delete_returns_the_task_without_new_steps(
    uow: SqlModelUnitOfWork, parents: Parents, patch_crd
) -> None:
    first = await delete_deployment(parents.deployment_id, uow)
    deployment = await uow.session.get(DeploymentModel, parents.deployment_id)
    assert deployment is not None
    deployment.status = DeploymentState.DELETING
    uow.session.add(deployment)
    await uow.commit()
    steps_before = await uow.steps.list_by_task_ids([first.id])

    second = await delete_deployment(parents.deployment_id, uow)

    assert second.id == first.id
    patch_crd.assert_awaited_once()
    assert await uow.steps.list_by_task_ids([first.id]) == steps_before
