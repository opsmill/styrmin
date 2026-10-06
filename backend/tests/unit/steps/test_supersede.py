"""A rollout or a deletion request supersedes earlier rollouts (spec 019, T066; research D7)."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from styrmin_backend.db.models import Deployment as DeploymentModel
from styrmin_backend.domain import steps
from styrmin_backend.domain.models import (
    Step,
    StepEvent,
    StepParent,
    StepStatus,
    Task,
    TaskType,
)
from styrmin_backend.services.deployment import delete_deployment
from styrmin_backend.services.steps.operator_history import apply_operator_report
from styrmin_backend.services.steps.recorder import (
    StepRecord,
    add_attempt_error,
    ensure_operator_steps,
    fail_step,
    open_step,
    record_detail,
    record_event,
    record_rollback,
    start_step,
    succeed_step,
    supersede_operator_steps,
)
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork
from tests.unit.steps.conftest import Parents

# Before the server's clock, which ends the deletion request.
T0 = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)

PENDING, RUNNING, SUCCEEDED, FAILED, SUPERSEDED = (
    StepStatus.PENDING,
    StepStatus.RUNNING,
    StepStatus.SUCCEEDED,
    StepStatus.FAILED,
    StepStatus.SUPERSEDED,
)
ROLLOUT_KEYS = [definition.key for definition in steps.ROLLOUT_OPERATOR_STEPS]


def _at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


async def _steps(uow: SqlModelUnitOfWork, task_id: UUID) -> dict[str, Step]:
    return {step.key: step for step in await uow.steps.list_by_task_ids([task_id])}


def _fields(task_steps: dict[str, Step]) -> dict[str, dict]:
    # ``updated_on`` is set by the database on each write.
    return {
        key: step.model_dump(exclude={"updated_on"}) for key, step in task_steps.items()
    }


async def _record_write(
    uow: SqlModelUnitOfWork, task: Task, event: StepEvent, at: datetime
) -> Step:
    definition = steps.STYRMIN_DEPLOYMENT_WRITE
    return await record_event(
        StepRecord(
            event=event,
            task_id=task.id,
            key=definition.key,
            name=definition.name,
            kind=definition.kind,
            occurred_at=at,
        ),
        uow,
    )


async def _write_cr(uow: SqlModelUnitOfWork, task: Task, at: datetime) -> Step:
    """The remediation flow writes the CR: STARTED, then SUCCEEDED through ``recordStep``."""
    await _record_write(uow, task, StepEvent.STARTED, at - timedelta(seconds=1))
    return await _record_write(uow, task, StepEvent.SUCCEEDED, at)


def _report(parents: Parents, phase: str, **extra: Any) -> dict[str, Any]:
    """A ``reportDeploymentStatuses`` entry for the instance of ``parents.task``."""
    return {
        "deployment_id": parents.deployment_id,
        "instance_id": parents.instance_id,
        "phase": phase,
        "display_state": "Deploying",
        "message": None,
        "conditions": None,
        "managed_resource_counts": None,
    } | extra


async def _task_of_another_deployment(
    uow: SqlModelUnitOfWork, parents: Parents
) -> Task:
    source = await uow.session.get(DeploymentModel, parents.deployment_id)
    assert source is not None
    deployment = DeploymentModel(
        name="other-deployment",
        application_version=source.application_version,
        status=source.status,
        application_driver_version_id=source.application_driver_version_id,
        environment_id=source.environment_id,
        created_by_user_id=source.created_by_user_id,
    )
    uow.session.add(deployment)
    await uow.session.flush()
    task = Task.create(TaskType.UPDATE_INSTANCE, deployment.id)
    await uow.tasks.save(task)
    await uow.session.flush()
    return task


# --- Superseding on a CR write ------------------------------------------------------


async def test_cr_write_success_supersedes_open_operator_steps_of_other_tasks(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _write_cr(uow, parents.task, _at(0))
    await apply_operator_report(_report(parents, "CreatingHelmRelease"), _at(10), uow)
    hook = await open_step(
        StepParent.of_task(parents.task.id), *steps.UPGRADE_POST_HOOK, _at(12), uow=uow
    )
    await uow.commit()

    await _write_cr(uow, parents.other_task, _at(30))

    interrupted = await _steps(uow, parents.task.id)
    statuses = {key: interrupted[key].status for key in ROLLOUT_KEYS}
    assert statuses == {
        "operator:prerequisites": SUCCEEDED,
        "operator:helmrelease": SUPERSEDED,
        "operator:services": SUPERSEDED,
        "operator:ready": SUPERSEDED,
    }
    assert interrupted["operator:prerequisites"].superseded_by_task_id is None
    for key in ROLLOUT_KEYS[1:]:
        assert interrupted[key].superseded_by_task_id == parents.other_task.id
        assert interrupted[key].ended_at == _at(30)
    assert interrupted["operator:helmrelease"].started_at == _at(10)
    assert interrupted["operator:services"].started_at is None
    # Flow-kind steps belong to the flow, which is still running.
    assert interrupted[hook.key].status is RUNNING
    assert interrupted[steps.STYRMIN_DEPLOYMENT_WRITE.key].status is SUCCEEDED

    own = await _steps(uow, parents.other_task.id)
    assert [own[key].status for key in ROLLOUT_KEYS] == [
        RUNNING,
        PENDING,
        PENDING,
        PENDING,
    ]
    assert {own[key].superseded_by_task_id for key in ROLLOUT_KEYS} == {None}


async def test_failed_operator_steps_are_not_superseded(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await ensure_operator_steps(parents.task, _at(0), uow=uow)
    prerequisites = (await _steps(uow, parents.task.id))["operator:prerequisites"]
    await fail_step(prerequisites, "quota exceeded", _at(5), uow=uow)
    await uow.commit()

    await _write_cr(uow, parents.other_task, _at(30))

    interrupted = await _steps(uow, parents.task.id)
    assert [interrupted[key].status for key in ROLLOUT_KEYS] == [
        FAILED,
        SUPERSEDED,
        SUPERSEDED,
        SUPERSEDED,
    ]
    assert interrupted["operator:prerequisites"].superseded_by_task_id is None


async def test_cr_write_leaves_the_steps_of_other_deployments(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    elsewhere = await _task_of_another_deployment(uow, parents)
    await ensure_operator_steps(elsewhere, _at(0), uow=uow)
    await uow.commit()
    before = _fields(await _steps(uow, elsewhere.id))

    await _write_cr(uow, parents.other_task, _at(30))

    assert _fields(await _steps(uow, elsewhere.id)) == before


async def test_repeated_cr_write_success_supersedes_nothing(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _write_cr(uow, parents.task, _at(0))
    await _write_cr(uow, parents.other_task, _at(30))
    before = _fields(await _steps(uow, parents.other_task.id))

    # A late copy of the first task's event does not interrupt the newer rollout.
    await _record_write(uow, parents.task, StepEvent.SUCCEEDED, _at(40))

    assert _fields(await _steps(uow, parents.other_task.id)) == before


async def test_supersede_returns_the_steps_and_never_ends_before_their_start(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await ensure_operator_steps(parents.task, _at(10), uow=uow)

    superseded = await supersede_operator_steps(
        parents.deployment_id, parents.other_task.id, _at(5), uow=uow
    )

    assert [step.key for step in superseded] == ROLLOUT_KEYS
    stored = await _steps(uow, parents.task.id)
    assert _fields({step.key: step for step in superseded}) == _fields(stored)
    assert stored["operator:prerequisites"].ended_at == _at(10)
    assert stored["operator:ready"].ended_at == _at(5)
    assert (
        await supersede_operator_steps(
            parents.deployment_id, parents.other_task.id, _at(6), uow=uow
        )
        == []
    )


# --- Superseding on a deletion request ------------------------------------------------


@pytest.fixture
def patch_crd(mocker):
    return mocker.patch(
        "styrmin_backend.services.deployment.patch_custom_resource", autospec=True
    )


async def test_delete_request_supersedes_open_operator_steps(
    uow: SqlModelUnitOfWork, parents: Parents, patch_crd
) -> None:
    await ensure_operator_steps(parents.task, _at(0), uow=uow)

    delete_task = await delete_deployment(parents.deployment_id, uow)

    patch_crd.assert_awaited_once()
    request = (await _steps(uow, delete_task.id))[steps.DELETE_REQUEST.key]
    interrupted = await _steps(uow, parents.task.id)
    assert {interrupted[key].status for key in ROLLOUT_KEYS} == {SUPERSEDED}
    assert {interrupted[key].superseded_by_task_id for key in ROLLOUT_KEYS} == {
        delete_task.id
    }
    assert {interrupted[key].ended_at for key in ROLLOUT_KEYS} == {request.ended_at}
    teardown = (await _steps(uow, delete_task.id))[steps.OPERATOR_TEARDOWN.key]
    assert (teardown.status, teardown.superseded_by_task_id) == (PENDING, None)


# --- Superseded steps are final ------------------------------------------------------


async def _supersede_after_failed_prerequisites(
    uow: SqlModelUnitOfWork, parents: Parents
) -> dict[str, Step]:
    """Failed prerequisites keep the phase history working on the task's other steps."""
    await ensure_operator_steps(parents.task, _at(0), uow=uow)
    prerequisites = (await _steps(uow, parents.task.id))["operator:prerequisites"]
    await fail_step(prerequisites, "quota exceeded", _at(5), uow=uow)
    await uow.commit()
    await _write_cr(uow, parents.other_task, _at(30))
    return await _steps(uow, parents.task.id)


@pytest.mark.parametrize(
    "report",
    [
        {"phase": "CreatingHelmRelease"},
        {"phase": "CreatingServices"},
        {"phase": "Ready", "display_state": "Running"},
        {"phase": "Failed", "display_state": "Error", "message": "boom"},
    ],
    ids=["helmrelease", "services", "ready", "failed"],
)
async def test_reports_do_not_change_superseded_steps(
    uow: SqlModelUnitOfWork, parents: Parents, report: dict[str, Any]
) -> None:
    before = await _supersede_after_failed_prerequisites(uow, parents)

    await apply_operator_report(_report(parents, **report), _at(60), uow)

    after = await _steps(uow, parents.task.id)
    superseded = ROLLOUT_KEYS[1:]
    assert _fields({key: after[key] for key in superseded}) == _fields(
        {key: before[key] for key in superseded}
    )


async def test_recorder_does_not_change_superseded_steps(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    before = await _supersede_after_failed_prerequisites(uow, parents)
    helmrelease = before["operator:helmrelease"]

    await start_step(helmrelease, _at(40), uow=uow)
    await succeed_step(helmrelease, _at(41), uow=uow)
    await fail_step(helmrelease, "late failure", _at(42), uow=uow)
    await add_attempt_error(helmrelease, "late error", _at(43), uow=uow)
    await record_detail(helmrelease, "UpgradeFailed: late", uow=uow)
    await record_rollback(helmrelease, _at(44), "rolled back", uow=uow)
    third = Task.create(TaskType.UPDATE_INSTANCE, parents.deployment_id)
    await uow.tasks.save(third)
    await uow.session.flush()
    await supersede_operator_steps(parents.deployment_id, third.id, _at(45), uow=uow)

    after = await _steps(uow, parents.task.id)
    assert _fields({"step": after[helmrelease.key]}) == _fields({"step": helmrelease})
