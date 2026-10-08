"""Operator-phase steps and the phase history (spec 019, T022; contracts/operator-status.md)."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from styrmin_backend.db.models import Deployment as DeploymentModel
from styrmin_backend.db.models import Task as TaskModel
from styrmin_backend.domain import steps
from styrmin_backend.domain.models import (
    Step,
    StepEvent,
    StepKind,
    StepParent,
    StepStatus,
    Task,
    TaskStatus,
    TaskType,
)
from styrmin_backend.services import deployment_status as deployment_status_module
from styrmin_backend.services.deployment_status import report_deployment_statuses
from styrmin_backend.services.steps.operator_history import apply_operator_report
from styrmin_backend.services.steps.recorder import (
    StepRecord,
    add_pending_steps,
    ensure_operator_steps,
    open_step,
    record_event,
    succeed_step,
)
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork
from tests.unit.steps.conftest import Parents

T0 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)

ROLLOUT_KEYS = [
    "operator:prerequisites",
    "operator:helmrelease",
    "operator:services",
    "operator:ready",
]
PENDING, RUNNING, SUCCEEDED = (
    StepStatus.PENDING,
    StepStatus.RUNNING,
    StepStatus.SUCCEEDED,
)


def _at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _condition(type_: str, at: datetime, status: str = "True") -> dict[str, Any]:
    return {
        "type": type_,
        "status": status,
        "reason": "",
        "message": "",
        "lastTransitionTime": at.isoformat(),
    }


def _report(
    phase: str,
    *,
    deployment_id: UUID,
    instance_id: UUID | None,
    conditions: list[dict[str, Any]] | None = None,
    display_state: str = "Deploying",
) -> dict[str, Any]:
    """A report as ``reportDeploymentStatuses`` hands it to the service."""
    return {
        "deployment_id": deployment_id,
        "instance_id": instance_id,
        "phase": phase,
        "display_state": display_state,
        "message": None,
        "conditions": conditions,
        "managed_resource_counts": None,
    }


def _rollout_report(parents: Parents, phase: str, **extra: Any) -> dict[str, Any]:
    return _report(
        phase,
        deployment_id=parents.deployment_id,
        instance_id=parents.instance_id,
        **extra,
    )


async def _steps(uow: SqlModelUnitOfWork, task_id: UUID) -> dict[str, Step]:
    return {step.key: step for step in await uow.steps.list_by_task_ids([task_id])}


async def _rollout_statuses(
    uow: SqlModelUnitOfWork, task_id: UUID
) -> list[StepStatus | None]:
    by_key = await _steps(uow, task_id)
    return [by_key[key].status if key in by_key else None for key in ROLLOUT_KEYS]


def _fields(task_steps: dict[str, Step]) -> dict[str, dict]:
    # ``updated_on`` is set by the database on each write.
    return {
        key: step.model_dump(exclude={"updated_on"}) for key, step in task_steps.items()
    }


def _spy_writes(monkeypatch: pytest.MonkeyPatch, uow: SqlModelUnitOfWork) -> list[str]:
    """Record every locked read and every save of a step."""
    calls: list[str] = []
    for name in ("get", "find_by_key", "list_open_operator_steps_of_older_tasks"):
        original = getattr(uow.steps, name)

        async def locked(*args, _original=original, _name=name, **kwargs):
            if kwargs.get("for_update"):
                calls.append(f"lock:{_name}")
            return await _original(*args, **kwargs)

        monkeypatch.setattr(uow.steps, name, locked)
    original_save = uow.steps.save

    async def save(step: Step) -> None:
        calls.append(f"save:{step.key}")
        await original_save(step)

    monkeypatch.setattr(uow.steps, "save", save)
    return calls


async def _record(uow: SqlModelUnitOfWork, task: Task, event: StepEvent, at: datetime):
    definition = steps.STYRMIN_DEPLOYMENT_WRITE
    return await record_event(
        StepRecord(
            event=event,
            task_id=task.id,
            key=definition.key,
            name=definition.name,
            kind=definition.kind,
            error="CR write failed" if event is StepEvent.FAILED else None,
            occurred_at=at,
        ),
        uow,
    )


async def _set_internal(uow: SqlModelUnitOfWork, deployment_id: UUID) -> None:
    deployment = await uow.session.get(DeploymentModel, deployment_id)
    assert deployment is not None
    deployment.internal = True
    uow.session.add(deployment)
    await uow.session.flush()


# --- Creation when the CR write succeeds -------------------------------------


async def test_cr_write_success_creates_the_operator_steps(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _record(uow, parents.task, StepEvent.STARTED, T0)
    write = await _record(uow, parents.task, StepEvent.SUCCEEDED, _at(5))

    listed = await uow.steps.list_by_task_ids([parents.task.id])

    assert [step.key for step in listed] == [write.key, *ROLLOUT_KEYS]
    by_key = {step.key: step for step in listed}
    prerequisites = by_key["operator:prerequisites"]
    assert (prerequisites.status, prerequisites.started_at) == (RUNNING, _at(5))
    assert prerequisites.attempt_count == 1
    assert prerequisites.name == "Create network policies and secrets"
    expected_names = {
        "operator:helmrelease": "Install or upgrade the HelmRelease",
        "operator:services": "Create services and middlewares",
        "operator:ready": "Wait for the deployment to be ready",
    }
    for key, name in expected_names.items():
        step = by_key[key]
        assert (step.name, step.kind, step.status) == (
            name,
            StepKind.OPERATOR_PHASE,
            PENDING,
        )
        assert (step.started_at, step.attempt_count) == (None, 0)


async def test_cr_write_success_creates_no_operator_steps_for_an_internal_deployment(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _set_internal(uow, parents.deployment_id)

    await _record(uow, parents.task, StepEvent.STARTED, T0)
    await _record(uow, parents.task, StepEvent.SUCCEEDED, _at(5))

    assert list(await _steps(uow, parents.task.id)) == [
        steps.STYRMIN_DEPLOYMENT_WRITE.key
    ]


async def test_failed_cr_write_creates_no_operator_steps(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _record(uow, parents.task, StepEvent.STARTED, T0)
    await _record(uow, parents.task, StepEvent.FAILED, _at(5))

    assert list(await _steps(uow, parents.task.id)) == [
        steps.STYRMIN_DEPLOYMENT_WRITE.key
    ]


async def test_success_of_another_step_creates_no_operator_steps(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    hook = await open_step(
        StepParent.of_task(parents.task.id), *steps.UPGRADE_CORE_HOOK, T0, uow=uow
    )
    await uow.commit()

    await record_event(
        StepRecord(event=StepEvent.SUCCEEDED, step_id=hook.id, occurred_at=_at(5)),
        uow,
    )

    assert list(await _steps(uow, parents.task.id)) == [steps.UPGRADE_CORE_HOOK.key]


async def test_repeated_creation_keeps_the_operator_steps(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await ensure_operator_steps(parents.task, T0, uow=uow)
    await apply_operator_report(
        _rollout_report(parents, "CreatingHelmRelease"), _at(10), uow
    )
    before = _fields(await _steps(uow, parents.task.id))

    await ensure_operator_steps(parents.task, _at(20), uow=uow)

    assert _fields(await _steps(uow, parents.task.id)) == before


# --- Moving rollout steps forward --------------------------------------------


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        ("Pending", [RUNNING, PENDING, PENDING, PENDING]),
        ("CreatingPrerequisites", [RUNNING, PENDING, PENDING, PENDING]),
        ("CreatingHelmRelease", [SUCCEEDED, RUNNING, PENDING, PENDING]),
        ("CreatingServices", [SUCCEEDED, SUCCEEDED, RUNNING, PENDING]),
        ("Ready", [SUCCEEDED, SUCCEEDED, SUCCEEDED, SUCCEEDED]),
        ("Restoring", [RUNNING, PENDING, PENDING, PENDING]),
    ],
)
async def test_each_phase_moves_the_rollout_steps(
    uow: SqlModelUnitOfWork,
    parents: Parents,
    phase: str,
    expected: list[StepStatus],
) -> None:
    await ensure_operator_steps(parents.task, T0, uow=uow)

    await apply_operator_report(_rollout_report(parents, phase), _at(30), uow)

    assert await _rollout_statuses(uow, parents.task.id) == expected


async def test_reports_end_the_steps_at_their_condition_times(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await ensure_operator_steps(parents.task, T0, uow=uow)
    prerequisites = [
        _condition("NetworkPoliciesReady", _at(10)),
        _condition("SecretsReady", _at(12)),
    ]
    helmrelease = [*prerequisites, _condition("HelmReleaseReady", _at(80))]
    ready = [
        *helmrelease,
        _condition("ServicesReady", _at(95)),
        _condition("Ready", _at(96)),
    ]

    await apply_operator_report(
        _rollout_report(parents, "CreatingHelmRelease", conditions=prerequisites),
        _at(20),
        uow,
    )
    await apply_operator_report(
        _rollout_report(parents, "CreatingServices", conditions=helmrelease),
        _at(90),
        uow,
    )
    await apply_operator_report(
        _rollout_report(parents, "Ready", conditions=ready, display_state="Running"),
        _at(100),
        uow,
    )

    by_key = await _steps(uow, parents.task.id)
    times = {
        key: (by_key[key].started_at, by_key[key].ended_at) for key in ROLLOUT_KEYS
    }
    assert times == {
        "operator:prerequisites": (T0, _at(12)),
        "operator:helmrelease": (_at(12), _at(80)),
        "operator:services": (_at(80), _at(95)),
        "operator:ready": (_at(95), _at(96)),
    }
    assert {by_key[key].attempt_count for key in ROLLOUT_KEYS} == {1}
    assert {by_key[key].status for key in ROLLOUT_KEYS} == {SUCCEEDED}


async def test_skipped_phases_succeed_every_earlier_step_at_the_report_time(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await ensure_operator_steps(parents.task, T0, uow=uow)

    await apply_operator_report(
        _rollout_report(parents, "Ready", display_state="Running"), _at(40), uow
    )

    by_key = await _steps(uow, parents.task.id)
    times = {
        key: (by_key[key].started_at, by_key[key].ended_at) for key in ROLLOUT_KEYS
    }
    assert times == {
        "operator:prerequisites": (T0, _at(40)),
        "operator:helmrelease": (_at(40), _at(40)),
        "operator:services": (_at(40), _at(40)),
        "operator:ready": (_at(40), _at(40)),
    }
    assert {by_key[key].attempt_count for key in ROLLOUT_KEYS} == {1}


@pytest.mark.parametrize(
    "condition",
    [
        _condition("HelmReleaseReady", T0 - timedelta(days=3)),
        _condition("HelmReleaseReady", _at(50), status="False"),
    ],
    ids=["earlier-rollout", "not-true"],
)
async def test_condition_that_does_not_end_the_step_falls_back_to_the_report_time(
    uow: SqlModelUnitOfWork, parents: Parents, condition: dict[str, Any]
) -> None:
    await ensure_operator_steps(parents.task, T0, uow=uow)
    await apply_operator_report(
        _rollout_report(parents, "CreatingHelmRelease"), _at(10), uow
    )

    await apply_operator_report(
        _rollout_report(parents, "CreatingServices", conditions=[condition]),
        _at(60),
        uow,
    )

    helmrelease = (await _steps(uow, parents.task.id))["operator:helmrelease"]
    assert (helmrelease.status, helmrelease.ended_at) == (SUCCEEDED, _at(60))


# --- Reports that change nothing ---------------------------------------------


@pytest.mark.parametrize(
    "report_for",
    ["unknown-instance", "legacy-cr", "other-deployment"],
)
async def test_report_without_a_matching_task_changes_nothing(
    uow: SqlModelUnitOfWork, parents: Parents, report_for: str
) -> None:
    await ensure_operator_steps(parents.task, T0, uow=uow)
    before = _fields(await _steps(uow, parents.task.id))
    report = {
        "unknown-instance": _report(
            "Ready", deployment_id=parents.deployment_id, instance_id=uuid4()
        ),
        # A CR from before ``instanceId`` existed reports no instance.
        "legacy-cr": _report(
            "Ready", deployment_id=parents.deployment_id, instance_id=None
        ),
        "other-deployment": _report(
            "Ready", deployment_id=uuid4(), instance_id=parents.instance_id
        ),
    }[report_for]

    await apply_operator_report(report, _at(30), uow)

    assert _fields(await _steps(uow, parents.task.id)) == before


async def test_report_for_a_task_without_operator_steps_changes_nothing(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    # A task from before the feature, or of an internal deployment.
    await apply_operator_report(_rollout_report(parents, "Ready"), _at(30), uow)

    assert await _steps(uow, parents.task.id) == {}


async def test_report_returns_before_any_lock_when_every_step_is_final(
    uow: SqlModelUnitOfWork, parents: Parents, monkeypatch: pytest.MonkeyPatch
) -> None:
    await ensure_operator_steps(parents.task, T0, uow=uow)
    await apply_operator_report(
        _rollout_report(parents, "CreatingServices"), _at(30), uow
    )
    services = (await _steps(uow, parents.task.id))["operator:services"]
    await uow.steps.save(
        services.model_copy(
            update={"status": StepStatus.SUPERSEDED, "ended_at": _at(31)}
        )
    )
    ready = (await _steps(uow, parents.task.id))["operator:ready"]
    await uow.steps.save(
        ready.model_copy(update={"status": StepStatus.SUPERSEDED, "ended_at": _at(31)})
    )
    before = _fields(await _steps(uow, parents.task.id))
    calls = _spy_writes(monkeypatch, uow)

    await apply_operator_report(
        _rollout_report(parents, "Ready", display_state="Running"), _at(60), uow
    )

    assert calls == []
    assert _fields(await _steps(uow, parents.task.id)) == before


async def test_report_that_changes_steps_locks_them(
    uow: SqlModelUnitOfWork, parents: Parents, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The spy of the early-return test does see the phase history's writes.
    await ensure_operator_steps(parents.task, T0, uow=uow)
    calls = _spy_writes(monkeypatch, uow)

    await apply_operator_report(
        _rollout_report(parents, "CreatingHelmRelease"), _at(30), uow
    )

    assert "lock:get" in calls
    assert "save:operator:helmrelease" in calls


# --- Delete routing ------------------------------------------------------------


async def _delete_task(
    uow: SqlModelUnitOfWork, parents: Parents, created_on: datetime
) -> Task:
    """A delete task with its "Request the deletion" step ended at ``created_on`` + 1s."""
    task = Task.create(
        type=TaskType.DELETE_DEPLOYMENT,
        deployment_id=parents.deployment_id,
        status=TaskStatus.SUCCESS,
    )
    await uow.tasks.save(task)
    await uow.session.flush()
    model = await uow.session.get(TaskModel, task.id)
    assert model is not None
    model.created_on = created_on
    uow.session.add(model)
    await uow.session.flush()
    parent = StepParent.of_task(task.id)
    request = await open_step(parent, *steps.DELETE_REQUEST, created_on, uow=uow)
    ended = created_on + timedelta(seconds=1)
    await succeed_step(request, ended, uow=uow)
    await add_pending_steps(parent, [steps.OPERATOR_TEARDOWN], ended, uow=uow)
    return task


def _delete_report(parents: Parents, phase: str, **extra: Any) -> dict[str, Any]:
    # A live CR still names its instance; the synthetic Deleted report does not.
    return _report(
        phase,
        deployment_id=parents.deployment_id,
        instance_id=parents.instance_id,
        display_state=phase,
        **extra,
    )


async def test_deleting_report_starts_the_teardown_of_the_newest_delete_task(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await ensure_operator_steps(parents.task, T0, uow=uow)
    rollout_before = _fields(await _steps(uow, parents.task.id))
    older = await _delete_task(uow, parents, _at(100))
    newer = await _delete_task(uow, parents, _at(200))
    older_before = _fields(await _steps(uow, older.id))

    await apply_operator_report(_delete_report(parents, "Deleting"), _at(210), uow)

    teardown = (await _steps(uow, newer.id))["operator:teardown"]
    assert (teardown.status, teardown.started_at) == (RUNNING, _at(201))
    assert teardown.attempt_count == 1
    assert _fields(await _steps(uow, older.id)) == older_before
    assert _fields(await _steps(uow, parents.task.id)) == rollout_before


async def test_deleted_report_ends_the_teardown_at_the_deleted_condition_time(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    task = await _delete_task(uow, parents, _at(100))
    await apply_operator_report(_delete_report(parents, "Deleting"), _at(110), uow)

    await apply_operator_report(
        _delete_report(
            parents, "Deleted", conditions=[_condition("Deleted", _at(150))]
        ),
        _at(160),
        uow,
    )

    teardown = (await _steps(uow, task.id))["operator:teardown"]
    assert (teardown.status, teardown.started_at, teardown.ended_at) == (
        SUCCEEDED,
        _at(101),
        _at(150),
    )


async def test_synthetic_deleted_report_ends_a_teardown_that_never_reported_deleting(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    task = await _delete_task(uow, parents, _at(100))

    # The agent sends this report once the namespace took the CR with it.
    await apply_operator_report(
        _report(
            "Deleted",
            deployment_id=parents.deployment_id,
            instance_id=None,
            display_state="Deleted",
        ),
        _at(160),
        uow,
    )

    teardown = (await _steps(uow, task.id))["operator:teardown"]
    assert (teardown.status, teardown.started_at, teardown.ended_at) == (
        SUCCEEDED,
        _at(101),
        _at(160),
    )
    assert teardown.attempt_count == 1


async def test_deleting_report_without_a_delete_task_changes_nothing(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await ensure_operator_steps(parents.task, T0, uow=uow)
    before = _fields(await _steps(uow, parents.task.id))

    await apply_operator_report(_delete_report(parents, "Deleting"), _at(30), uow)

    assert _fields(await _steps(uow, parents.task.id)) == before


# --- Called by reportDeploymentStatuses --------------------------------------


async def test_status_report_moves_the_steps_with_the_snapshot(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await ensure_operator_steps(parents.task, T0, uow=uow)
    await uow.commit()

    await report_deployment_statuses(
        [_rollout_report(parents, "CreatingHelmRelease")], uow
    )

    await uow.rollback()  # Only committed writes remain.
    snapshot = await uow.deployment_statuses.find_by_deployment(parents.deployment_id)
    assert snapshot is not None
    assert snapshot.phase == "CreatingHelmRelease"
    assert await _rollout_statuses(uow, parents.task.id) == [
        SUCCEEDED,
        RUNNING,
        PENDING,
        PENDING,
    ]


async def test_failed_phase_history_keeps_the_snapshot_and_the_deployment_state(
    uow: SqlModelUnitOfWork, parents: Parents, monkeypatch: pytest.MonkeyPatch
) -> None:
    await ensure_operator_steps(parents.task, T0, uow=uow)
    await uow.commit()

    async def apply_then_fail(report, now, uow) -> None:
        # The phase history's own writes must be undone with it.
        await apply_operator_report(report, now, uow)
        raise RuntimeError("phase history broke")

    monkeypatch.setattr(
        deployment_status_module, "apply_operator_report", apply_then_fail
    )

    statuses_updated, deployments_updated = await report_deployment_statuses(
        [_rollout_report(parents, "CreatingHelmRelease")], uow
    )

    assert (statuses_updated, deployments_updated) == (1, 1)
    await uow.rollback()  # Only committed writes remain.
    snapshot = await uow.deployment_statuses.find_by_deployment(parents.deployment_id)
    assert snapshot is not None
    assert snapshot.phase == "CreatingHelmRelease"
    deployment = await uow.deployments.find(parents.deployment_id)
    assert deployment is not None
    assert deployment.status.value == "deploying"
    assert await _rollout_statuses(uow, parents.task.id) == [
        RUNNING,
        PENDING,
        PENDING,
        PENDING,
    ]
