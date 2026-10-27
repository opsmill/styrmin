"""Failures, attempts, FluxCD details, rollbacks and pod reasons in the phase history.

Spec 019, T051; contracts/operator-status.md "Moving rollout steps forward",
"HelmRelease details" and "Pod reasons on failure".
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from styrmin_backend.db.models import PodPhase, PodStatus
from styrmin_backend.domain.models import Step, StepStatus
from styrmin_backend.services.steps.operator_history import apply_operator_report
from styrmin_backend.services.steps.recorder import ensure_operator_steps
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork
from tests.unit.steps.conftest import Parents

T0 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)

PENDING, RUNNING, SUCCEEDED, FAILED = (
    StepStatus.PENDING,
    StepStatus.RUNNING,
    StepStatus.SUCCEEDED,
    StepStatus.FAILED,
)
PREREQUISITES, HELMRELEASE, SERVICES, READY = (
    "operator:prerequisites",
    "operator:helmrelease",
    "operator:services",
    "operator:ready",
)

QUOTA_ERROR = (
    "Update failed: ['networkpolicies \"allow-dns\" is forbidden: exceeded quota']"
)
TIMEOUT = "Deployment did not reach Ready within 300s (phase: CreatingHelmRelease)"
UPGRADE_FAILED = "Helm upgrade failed for release app: context deadline exceeded"
ROLLBACK = "Helm rollback to previous release app.v1 with chart app@1.0.0 succeeded"


def _at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _condition(
    type_: str,
    at: datetime,
    status: str = "True",
    reason: str = "",
    message: str = "",
) -> dict[str, Any]:
    return {
        "type": type_,
        "status": status,
        "reason": reason,
        "message": message,
        "lastTransitionTime": at.isoformat(),
    }


def _restart(at: datetime) -> dict[str, Any]:
    """The operator's reset of ``HelmReleaseReady`` at the start of each handler run."""
    return _condition(
        "HelmReleaseReady",
        at,
        status="Unknown",
        reason="Progressing",
        message="Waiting for FluxCD to apply the HelmRelease",
    )


def _upgrade_failed(at: datetime, message: str = UPGRADE_FAILED) -> dict[str, Any]:
    return _condition(
        "HelmReleaseReady", at, status="False", reason="UpgradeFailed", message=message
    )


def _remediated(at: datetime, message: str = ROLLBACK) -> dict[str, Any]:
    return _condition(
        "HelmReleaseRemediated", at, reason="RollbackSucceeded", message=message
    )


def _report(
    parents: Parents,
    phase: str,
    *,
    display_state: str = "Deploying",
    message: str | None = None,
    conditions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A report as ``reportDeploymentStatuses`` hands it to the service."""
    return {
        "deployment_id": parents.deployment_id,
        "instance_id": parents.instance_id,
        "phase": phase,
        "display_state": display_state,
        "message": message,
        "conditions": conditions,
        "managed_resource_counts": None,
    }


def _failed(parents: Parents, message: str, *conditions: dict[str, Any]):
    return _report(
        parents,
        "Failed",
        display_state="Error",
        message=message,
        conditions=list(conditions),
    )


def _timed_out(parents: Parents, *conditions: dict[str, Any]) -> dict[str, Any]:
    return _report(
        parents,
        "CreatingHelmRelease",
        display_state="Error",
        message=TIMEOUT,
        conditions=list(conditions),
    )


async def _steps(uow: SqlModelUnitOfWork, task_id: UUID) -> dict[str, Step]:
    return {step.key: step for step in await uow.steps.list_by_task_ids([task_id])}


async def _step(uow: SqlModelUnitOfWork, parents: Parents, key: str) -> Step:
    return (await _steps(uow, parents.task.id))[key]


def _errors(step: Step) -> list[tuple[int, str, datetime]]:
    return [(error.attempt, error.message, error.occurred_at) for error in step.errors]


def _fields(task_steps: dict[str, Step]) -> dict[str, dict]:
    # ``updated_on`` is set by the database on each write.
    return {
        key: step.model_dump(exclude={"updated_on"}) for key, step in task_steps.items()
    }


def _spy_writes(monkeypatch: pytest.MonkeyPatch, uow: SqlModelUnitOfWork) -> list[str]:
    """Record every locked read and every save of a step."""
    calls: list[str] = []
    original_get = uow.steps.get

    async def get(step_id, for_update: bool = False):
        if for_update:
            calls.append("lock")
        return await original_get(step_id, for_update=for_update)

    original_save = uow.steps.save

    async def save(step: Step) -> None:
        calls.append(f"save:{step.key}")
        await original_save(step)

    monkeypatch.setattr(uow.steps, "get", get)
    monkeypatch.setattr(uow.steps, "save", save)
    return calls


async def _running_helmrelease(uow: SqlModelUnitOfWork, parents: Parents) -> None:
    """Prerequisites done at 10s; the HelmRelease step runs from 10s."""
    await ensure_operator_steps(parents.task, T0, uow=uow)
    await apply_operator_report(_report(parents, "CreatingHelmRelease"), _at(10), uow)


async def _seed_pod(
    uow: SqlModelUnitOfWork,
    parents: Parents,
    name: str,
    *states: tuple[str, str],
    phase: PodPhase = PodPhase.PENDING,
) -> None:
    """A stored pod status with one container per ``(container, state)``."""
    uow.session.add(
        PodStatus(
            pod_name=name,
            namespace="styrmin-steps",
            phase=phase,
            container_statuses=[
                {
                    "name": container,
                    "ready": False,
                    "state": state,
                    "restart_count": 0,
                    "image": "registry.example.com/app:missing",
                    "started_at": None,
                }
                for container, state in states
            ],
            deployment_id=parents.deployment_id,
            last_polled_at=T0,
        )
    )
    await uow.session.flush()


# --- Failed phase and Error display state --------------------------------------


async def test_failed_phase_fails_the_first_unfinished_step_with_the_cr_message(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await ensure_operator_steps(parents.task, T0, uow=uow)

    await apply_operator_report(
        _failed(parents, QUOTA_ERROR, _restart(_at(20))), _at(25), uow
    )

    by_key = await _steps(uow, parents.task.id)
    prerequisites = by_key[PREREQUISITES]
    assert prerequisites.status is FAILED
    assert (prerequisites.started_at, prerequisites.ended_at) == (T0, _at(20))
    assert prerequisites.attempt_count == 1
    assert _errors(prerequisites) == [(1, QUOTA_ERROR, _at(20))]
    assert [by_key[key].status for key in (HELMRELEASE, SERVICES, READY)] == [
        PENDING,
        PENDING,
        PENDING,
    ]


async def test_error_display_state_fails_the_step_of_the_reported_phase(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await ensure_operator_steps(parents.task, T0, uow=uow)

    # The readiness timeout keeps the phase and sets displayState Error.
    await apply_operator_report(_timed_out(parents), _at(300), uow)

    by_key = await _steps(uow, parents.task.id)
    assert by_key[PREREQUISITES].status is SUCCEEDED
    helmrelease = by_key[HELMRELEASE]
    assert helmrelease.status is FAILED
    assert (helmrelease.started_at, helmrelease.ended_at) == (_at(300), _at(300))
    assert _errors(helmrelease) == [(1, TIMEOUT, _at(300))]
    assert [by_key[key].status for key in (SERVICES, READY)] == [PENDING, PENDING]


async def test_failed_phase_fails_the_helmrelease_step_once_prerequisites_hold(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    # The handler created the prerequisites, then could not write the HelmRelease.
    await ensure_operator_steps(parents.task, T0, uow=uow)
    message = "HelmRelease update failed: ['the FluxCD API is unavailable']"

    await apply_operator_report(
        _failed(
            parents,
            message,
            _restart(_at(3)),
            _condition("NetworkPoliciesReady", _at(4)),
            _condition("SecretsReady", _at(5)),
        ),
        _at(10),
        uow,
    )

    by_key = await _steps(uow, parents.task.id)
    assert (by_key[PREREQUISITES].status, by_key[PREREQUISITES].ended_at) == (
        SUCCEEDED,
        _at(5),
    )
    helmrelease = by_key[HELMRELEASE]
    assert helmrelease.status is FAILED
    assert helmrelease.started_at == _at(5)
    assert _errors(helmrelease) == [(1, message, _at(5))]


async def test_failed_phase_ignores_prerequisite_conditions_of_an_earlier_rollout(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await ensure_operator_steps(parents.task, T0, uow=uow)
    earlier = T0 - timedelta(days=1)

    await apply_operator_report(
        _failed(
            parents,
            QUOTA_ERROR,
            _restart(_at(20)),
            _condition("NetworkPoliciesReady", earlier),
            _condition("SecretsReady", earlier),
        ),
        _at(25),
        uow,
    )

    by_key = await _steps(uow, parents.task.id)
    assert by_key[PREREQUISITES].status is FAILED
    assert by_key[HELMRELEASE].status is PENDING


async def test_repeated_failure_report_changes_nothing(
    uow: SqlModelUnitOfWork, parents: Parents, monkeypatch: pytest.MonkeyPatch
) -> None:
    await ensure_operator_steps(parents.task, T0, uow=uow)
    report = _failed(parents, QUOTA_ERROR, _restart(_at(20)))
    await apply_operator_report(report, _at(25), uow)
    before = _fields(await _steps(uow, parents.task.id))
    calls = _spy_writes(monkeypatch, uow)

    await apply_operator_report(report, _at(30), uow)

    assert calls == []
    assert _fields(await _steps(uow, parents.task.id)) == before


async def test_failure_report_without_a_message_names_the_operator(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await ensure_operator_steps(parents.task, T0, uow=uow)

    await apply_operator_report(
        _report(parents, "Failed", display_state="Error"), _at(25), uow
    )

    prerequisites = await _step(uow, parents, PREREQUISITES)
    assert _errors(prerequisites) == [(1, "The operator reported a failure", _at(25))]


# --- Attempts --------------------------------------------------------------------


async def test_operator_retry_adds_an_attempt_with_its_error(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await ensure_operator_steps(parents.task, T0, uow=uow)
    await apply_operator_report(
        _failed(parents, QUOTA_ERROR, _restart(_at(20))), _at(25), uow
    )

    # The operator retries 30 seconds later and fails the same way.
    await apply_operator_report(
        _failed(parents, QUOTA_ERROR, _restart(_at(55))), _at(60), uow
    )

    prerequisites = await _step(uow, parents, PREREQUISITES)
    assert prerequisites.status is FAILED
    assert prerequisites.attempt_count == 2
    assert (prerequisites.started_at, prerequisites.ended_at) == (T0, _at(55))
    assert _errors(prerequisites) == [
        (1, QUOTA_ERROR, _at(20)),
        (2, QUOTA_ERROR, _at(55)),
    ]


async def test_new_failure_message_without_a_retry_joins_the_current_attempt(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)
    await apply_operator_report(_timed_out(parents), _at(300), uow)
    stalled = f"Failed to upgrade after 4 attempt(s): {UPGRADE_FAILED}"

    # FluxCD used its retries: no operator retry, a new CR message.
    await apply_operator_report(
        _failed(parents, stalled, _condition("Ready", _at(900), status="False")),
        _at(905),
        uow,
    )

    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert helmrelease.status is FAILED
    assert helmrelease.attempt_count == 1
    assert _errors(helmrelease) == [(1, TIMEOUT, _at(300)), (1, stalled, _at(900))]


async def test_failed_step_runs_again_when_the_operator_works_on_it(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await ensure_operator_steps(parents.task, T0, uow=uow)
    await apply_operator_report(
        _failed(parents, QUOTA_ERROR, _restart(_at(20))), _at(25), uow
    )

    await apply_operator_report(_report(parents, "CreatingPrerequisites"), _at(60), uow)

    prerequisites = await _step(uow, parents, PREREQUISITES)
    assert prerequisites.status is RUNNING
    assert prerequisites.attempt_count == 2
    assert (prerequisites.started_at, prerequisites.ended_at) == (T0, None)
    assert _errors(prerequisites) == [(1, QUOTA_ERROR, _at(20))]


async def test_later_phase_succeeds_a_failed_helmrelease_step_with_a_new_attempt(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)
    await apply_operator_report(_timed_out(parents), _at(300), uow)

    # A later FluxCD attempt succeeded after the readiness timeout.
    await apply_operator_report(
        _report(
            parents,
            "Ready",
            display_state="Running",
            conditions=[
                _condition("HelmReleaseReady", _at(400), reason="FluxReady"),
                _condition("ServicesReady", _at(405)),
                _condition("Ready", _at(406)),
            ],
        ),
        _at(410),
        uow,
    )

    by_key = await _steps(uow, parents.task.id)
    helmrelease = by_key[HELMRELEASE]
    assert helmrelease.status is SUCCEEDED
    assert helmrelease.attempt_count == 2
    assert (helmrelease.started_at, helmrelease.ended_at) == (_at(10), _at(400))
    assert _errors(helmrelease) == [(1, TIMEOUT, _at(300))]
    assert {by_key[key].status for key in (SERVICES, READY)} == {SUCCEEDED}


# --- HelmRelease details: FluxCD's reason ----------------------------------------


async def test_detail_holds_fluxcds_reason_and_message(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)
    progressing = "Running 'upgrade' action with timeout of 5m0s"

    await apply_operator_report(
        _report(
            parents,
            "CreatingHelmRelease",
            conditions=[
                _condition(
                    "HelmReleaseReady",
                    _at(20),
                    status="Unknown",
                    reason="Progressing",
                    message=progressing,
                )
            ],
        ),
        _at(25),
        uow,
    )

    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert helmrelease.detail == f"Progressing: {progressing}"
    assert (helmrelease.status, helmrelease.attempt_count) == (RUNNING, 1)
    assert helmrelease.errors == []


async def test_detail_follows_fluxcd_while_the_step_is_failed(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)
    await apply_operator_report(_timed_out(parents), _at(300), uow)

    await apply_operator_report(
        _timed_out(parents, _upgrade_failed(_at(310))), _at(315), uow
    )

    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert helmrelease.detail == f"UpgradeFailed: {UPGRADE_FAILED}"


async def test_ready_helmrelease_keeps_the_previous_detail(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)
    await apply_operator_report(
        _report(
            parents,
            "CreatingHelmRelease",
            conditions=[_upgrade_failed(_at(320))],
        ),
        _at(325),
        uow,
    )

    await apply_operator_report(
        _report(
            parents,
            "CreatingServices",
            conditions=[_condition("HelmReleaseReady", _at(600), reason="FluxReady")],
        ),
        _at(605),
        uow,
    )

    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert helmrelease.status is SUCCEEDED
    assert helmrelease.detail == f"UpgradeFailed: {UPGRADE_FAILED}"


# --- HelmRelease details: FluxCD failures count as attempts -----------------------


async def test_fluxcd_failure_adds_an_attempt_while_the_phase_stays(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)

    await apply_operator_report(
        _report(parents, "CreatingHelmRelease", conditions=[_upgrade_failed(_at(320))]),
        _at(325),
        uow,
    )

    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert helmrelease.status is RUNNING
    assert (helmrelease.attempt_count, helmrelease.ended_at) == (2, None)
    assert _errors(helmrelease) == [(1, f"UpgradeFailed: {UPGRADE_FAILED}", _at(320))]


async def test_same_fluxcd_failure_reported_again_changes_nothing(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)
    report = _report(
        parents, "CreatingHelmRelease", conditions=[_upgrade_failed(_at(320))]
    )
    await apply_operator_report(report, _at(325), uow)
    before = _fields(await _steps(uow, parents.task.id))

    await apply_operator_report(report, _at(330), uow)

    assert _fields(await _steps(uow, parents.task.id)) == before


@pytest.mark.parametrize(
    ("condition", "expected_error"),
    [
        (
            _upgrade_failed(_at(650)),
            (2, f"UpgradeFailed: {UPGRADE_FAILED}", _at(650)),
        ),
        (
            _upgrade_failed(_at(320), message="Helm upgrade failed: hook timed out"),
            (2, "UpgradeFailed: Helm upgrade failed: hook timed out", _at(320)),
        ),
    ],
    ids=["new-time", "new-message"],
)
async def test_fluxcd_failure_with_a_new_time_or_message_adds_an_attempt(
    uow: SqlModelUnitOfWork,
    parents: Parents,
    condition: dict[str, Any],
    expected_error: tuple[int, str, datetime],
) -> None:
    await _running_helmrelease(uow, parents)
    await apply_operator_report(
        _report(parents, "CreatingHelmRelease", conditions=[_upgrade_failed(_at(320))]),
        _at(325),
        uow,
    )

    await apply_operator_report(
        _report(parents, "CreatingHelmRelease", conditions=[condition]), _at(660), uow
    )

    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert (helmrelease.status, helmrelease.attempt_count) == (RUNNING, 3)
    assert _errors(helmrelease)[-1] == expected_error
    assert len(helmrelease.errors) == 2


@pytest.mark.parametrize("reason", ["InstallFailed", "UpgradeFailed", "TestFailed"])
async def test_each_fluxcd_failed_reason_adds_an_attempt(
    uow: SqlModelUnitOfWork, parents: Parents, reason: str
) -> None:
    await _running_helmrelease(uow, parents)

    await apply_operator_report(
        _report(
            parents,
            "CreatingHelmRelease",
            conditions=[
                _condition(
                    "HelmReleaseReady",
                    _at(320),
                    status="False",
                    reason=reason,
                    message="it failed",
                )
            ],
        ),
        _at(325),
        uow,
    )

    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert helmrelease.attempt_count == 2
    assert _errors(helmrelease) == [(1, f"{reason}: it failed", _at(320))]


async def test_fluxcd_reason_without_failed_adds_no_attempt(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)

    await apply_operator_report(
        _report(
            parents,
            "CreatingHelmRelease",
            conditions=[
                _condition(
                    "HelmReleaseReady",
                    _at(20),
                    status="False",
                    reason="DependencyNotReady",
                    message="dependency 'db' is not ready",
                )
            ],
        ),
        _at(25),
        uow,
    )

    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert (helmrelease.status, helmrelease.attempt_count) == (RUNNING, 1)
    assert helmrelease.errors == []
    assert helmrelease.detail == "DependencyNotReady: dependency 'db' is not ready"


async def test_fluxcd_failure_after_the_timeout_joins_the_failed_attempt(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)
    await apply_operator_report(_timed_out(parents), _at(300), uow)

    # FluxCD's Helm wait ends in the same minute, then FluxCD rolls back.
    await apply_operator_report(
        _timed_out(parents, _upgrade_failed(_at(305)), _remediated(_at(310))),
        _at(320),
        uow,
    )

    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert (helmrelease.status, helmrelease.attempt_count) == (FAILED, 1)
    assert _errors(helmrelease) == [
        (1, TIMEOUT, _at(300)),
        (1, f"UpgradeFailed: {UPGRADE_FAILED}", _at(305)),
    ]
    assert helmrelease.rolled_back_at == _at(310)


async def test_fluxcd_failure_after_a_rollback_of_a_failed_step_adds_an_attempt(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)
    await apply_operator_report(_timed_out(parents), _at(300), uow)
    await apply_operator_report(
        _timed_out(parents, _upgrade_failed(_at(305)), _remediated(_at(310))),
        _at(320),
        uow,
    )

    # FluxCD's next attempt fails too and is rolled back.
    await apply_operator_report(
        _timed_out(parents, _upgrade_failed(_at(640)), _remediated(_at(645))),
        _at(650),
        uow,
    )

    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert (helmrelease.status, helmrelease.attempt_count) == (FAILED, 2)
    assert _errors(helmrelease)[-1] == (
        2,
        f"UpgradeFailed: {UPGRADE_FAILED}",
        _at(640),
    )
    assert (helmrelease.ended_at, helmrelease.rolled_back_at) == (_at(640), _at(645))


# --- HelmRelease details: rollbacks ----------------------------------------------


async def test_rollback_sets_rolled_back_at_and_message(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)

    await apply_operator_report(
        _report(
            parents,
            "CreatingHelmRelease",
            conditions=[_upgrade_failed(_at(320)), _remediated(_at(325))],
        ),
        _at(330),
        uow,
    )

    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert (helmrelease.rolled_back_at, helmrelease.rollback_message) == (
        _at(325),
        ROLLBACK,
    )
    # The FluxCD failure already ended the attempt that FluxCD rolled back.
    assert (helmrelease.status, helmrelease.attempt_count) == (RUNNING, 2)
    assert len(helmrelease.errors) == 1


async def test_rollback_without_a_reported_failure_ends_the_attempt(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)

    # The operator missed FluxCD's failure: FluxCD already runs its next attempt.
    await apply_operator_report(
        _report(
            parents,
            "CreatingHelmRelease",
            conditions=[
                _condition(
                    "HelmReleaseReady",
                    _at(330),
                    status="Unknown",
                    reason="Progressing",
                    message="Running 'upgrade' action with timeout of 5m0s",
                ),
                _remediated(_at(325)),
            ],
        ),
        _at(335),
        uow,
    )

    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert (helmrelease.status, helmrelease.attempt_count) == (RUNNING, 2)
    assert helmrelease.errors == []
    assert helmrelease.rolled_back_at == _at(325)


async def test_newer_rollback_replaces_the_older_one(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)
    await apply_operator_report(
        _report(
            parents,
            "CreatingHelmRelease",
            conditions=[_upgrade_failed(_at(320)), _remediated(_at(325))],
        ),
        _at(330),
        uow,
    )
    newer = _report(
        parents,
        "CreatingHelmRelease",
        conditions=[
            _upgrade_failed(_at(640)),
            _remediated(_at(645), message="Helm rollback to app.v1 succeeded"),
        ],
    )

    await apply_operator_report(newer, _at(650), uow)
    await apply_operator_report(newer, _at(655), uow)

    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert (helmrelease.rolled_back_at, helmrelease.rollback_message) == (
        _at(645),
        "Helm rollback to app.v1 succeeded",
    )
    assert (helmrelease.status, helmrelease.attempt_count) == (RUNNING, 3)
    assert [error.attempt for error in helmrelease.errors] == [1, 2]


async def test_rollback_before_the_step_started_is_ignored(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)

    await apply_operator_report(
        _report(
            parents,
            "CreatingHelmRelease",
            conditions=[_remediated(T0 - timedelta(days=1))],
        ),
        _at(30),
        uow,
    )

    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert (helmrelease.rolled_back_at, helmrelease.rollback_message) == (None, None)
    assert helmrelease.attempt_count == 1


async def test_rollback_reported_with_the_ready_release_is_kept(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    # FluxCD's second attempt succeeded between two operator ticks.
    await _running_helmrelease(uow, parents)

    await apply_operator_report(
        _report(
            parents,
            "Ready",
            display_state="Running",
            conditions=[
                _remediated(_at(325)),
                _condition("HelmReleaseReady", _at(600), reason="FluxReady"),
                _condition("ServicesReady", _at(605)),
                _condition("Ready", _at(606)),
            ],
        ),
        _at(610),
        uow,
    )

    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert (helmrelease.status, helmrelease.attempt_count) == (SUCCEEDED, 2)
    assert (helmrelease.rolled_back_at, helmrelease.rollback_message) == (
        _at(325),
        ROLLBACK,
    )


async def test_stalled_release_fails_the_attempt_fluxcd_failed(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)
    stalled = f"Failed to upgrade after 1 attempt(s): {UPGRADE_FAILED}"

    await apply_operator_report(
        _failed(
            parents,
            stalled,
            _upgrade_failed(_at(320)),
            _remediated(_at(325)),
            _condition("Ready", _at(330), status="False", reason="RetriesExceeded"),
        ),
        _at(335),
        uow,
    )

    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert (helmrelease.status, helmrelease.attempt_count) == (FAILED, 1)
    assert helmrelease.ended_at == _at(330)
    assert _errors(helmrelease) == [
        (1, f"UpgradeFailed: {UPGRADE_FAILED}", _at(320)),
        (1, stalled, _at(330)),
    ]
    assert helmrelease.rolled_back_at == _at(325)


async def test_rollback_failure_keeps_the_helmrelease_step_failed(
    uow: SqlModelUnitOfWork, parents: Parents, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H1: the operator fails the rollout when FluxCD reports its rollback Ready."""
    await _running_helmrelease(uow, parents)
    await apply_operator_report(_timed_out(parents), _at(300), uow)
    copied = [_upgrade_failed(_at(305)), _remediated(_at(305))]
    await apply_operator_report(_timed_out(parents, *copied), _at(310), uow)
    rolled_back = (
        f"FluxCD rolled the release back after release v3 failed: {UPGRADE_FAILED}"
    )
    report = _failed(
        parents,
        rolled_back,
        *copied,
        _condition(
            "Ready", _at(316), status="False", reason="RolledBack", message=rolled_back
        ),
    )

    await apply_operator_report(report, _at(320), uow)
    before = _fields(await _steps(uow, parents.task.id))
    calls = _spy_writes(monkeypatch, uow)
    await apply_operator_report(report, _at(330), uow)

    by_key = await _steps(uow, parents.task.id)
    helmrelease = by_key[HELMRELEASE]
    assert (helmrelease.status, helmrelease.attempt_count) == (FAILED, 1)
    assert _errors(helmrelease) == [
        (1, TIMEOUT, _at(300)),
        (1, f"UpgradeFailed: {UPGRADE_FAILED}", _at(305)),
        (1, rolled_back, _at(316)),
    ]
    assert (helmrelease.rolled_back_at, helmrelease.rollback_message) == (
        _at(305),
        ROLLBACK,
    )
    assert {by_key[key].status for key in (SERVICES, READY)} == {PENDING}
    # The failed phase stays until the next rollout, so its reports change nothing.
    assert calls == []
    assert _fields(by_key) == before


# --- Pod reasons on failure --------------------------------------------------------


async def test_pod_reasons_are_appended_when_the_helmrelease_step_fails(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)
    for index in range(7, 0, -1):
        await _seed_pod(
            uow, parents, f"app-{index}", ("app", "waiting:ImagePullBackOff")
        )
    await _seed_pod(uow, parents, "db-0", ("db", "running"))
    await _seed_pod(uow, parents, "job-0", ("job", "terminated:Completed"))
    await _seed_pod(uow, parents, "web-0", ("web", "waiting:ContainerCreating"))

    await apply_operator_report(_timed_out(parents), _at(300), uow)

    helmrelease = await _step(uow, parents, HELMRELEASE)
    pods = ", ".join(f"app-{index} (app: ImagePullBackOff)" for index in range(1, 6))
    assert _errors(helmrelease) == [(1, f"{TIMEOUT}\nPods not ready: {pods}", _at(300))]


@pytest.mark.parametrize(
    "state",
    [
        "waiting:ImagePullBackOff",
        "waiting:ErrImagePull",
        "waiting:InvalidImageName",
        "waiting:CrashLoopBackOff",
        "waiting:CreateContainerConfigError",
        "waiting:CreateContainerError",
        "terminated:Error",
        "terminated:OOMKilled",
    ],
)
async def test_each_listed_container_reason_is_appended(
    uow: SqlModelUnitOfWork, parents: Parents, state: str
) -> None:
    await _running_helmrelease(uow, parents)
    await _seed_pod(uow, parents, "app-0", ("app", state))

    await apply_operator_report(_timed_out(parents), _at(300), uow)

    reason = state.split(":", 1)[1]
    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert helmrelease.errors[0].message == (
        f"{TIMEOUT}\nPods not ready: app-0 (app: {reason})"
    )


async def test_pod_reasons_skip_finished_pods(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    # The pods of a failed Job sort first and would fill the five places.
    await _running_helmrelease(uow, parents)
    for index in range(5):
        await _seed_pod(
            uow,
            parents,
            f"app-job-{index}",
            ("user-job", "terminated:Error"),
            phase=PodPhase.FAILED,
        )
    await _seed_pod(
        uow,
        parents,
        "app-migrate",
        ("job", "terminated:Error"),
        phase=PodPhase.SUCCEEDED,
    )
    await _seed_pod(uow, parents, "app-server", ("app", "waiting:ImagePullBackOff"))

    await apply_operator_report(_timed_out(parents), _at(300), uow)

    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert helmrelease.errors[0].message == (
        f"{TIMEOUT}\nPods not ready: app-server (app: ImagePullBackOff)"
    )


async def test_pod_reasons_list_every_container_with_a_listed_reason(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)
    await _seed_pod(
        uow,
        parents,
        "api-0",
        ("api", "terminated:OOMKilled"),
        ("proxy", "running"),
        ("sidecar", "waiting:CrashLoopBackOff"),
    )

    await apply_operator_report(_timed_out(parents), _at(300), uow)

    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert helmrelease.errors[0].message == (
        f"{TIMEOUT}\nPods not ready: api-0 (api: OOMKilled; sidecar: CrashLoopBackOff)"
    )


async def test_pod_reasons_are_appended_when_the_ready_step_fails(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await ensure_operator_steps(parents.task, T0, uow=uow)
    await apply_operator_report(_report(parents, "CreatingServices"), _at(20), uow)
    await _seed_pod(uow, parents, "app-0", ("app", "waiting:CrashLoopBackOff"))
    guard = "Component 'app' has no container 'worker'"

    await apply_operator_report(
        _failed(
            parents,
            guard,
            _condition("ServicesReady", _at(30)),
            _condition("Ready", _at(35), status="False"),
        ),
        _at(40),
        uow,
    )

    by_key = await _steps(uow, parents.task.id)
    assert (by_key[SERVICES].status, by_key[SERVICES].ended_at) == (SUCCEEDED, _at(30))
    assert _errors(by_key[READY]) == [
        (1, f"{guard}\nPods not ready: app-0 (app: CrashLoopBackOff)", _at(35))
    ]


async def test_prerequisites_failure_lists_no_pods(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await ensure_operator_steps(parents.task, T0, uow=uow)
    await _seed_pod(uow, parents, "app-0", ("app", "waiting:ImagePullBackOff"))

    await apply_operator_report(
        _failed(parents, QUOTA_ERROR, _restart(_at(20))), _at(25), uow
    )

    prerequisites = await _step(uow, parents, PREREQUISITES)
    assert _errors(prerequisites) == [(1, QUOTA_ERROR, _at(20))]


async def test_failure_without_pod_reasons_keeps_the_cr_message(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)
    await _seed_pod(uow, parents, "app-0", ("app", "running"))

    await apply_operator_report(_timed_out(parents), _at(300), uow)

    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert _errors(helmrelease) == [(1, TIMEOUT, _at(300))]


# --- Pod reasons: scheduling, init containers and messages (#574) ------------------

UNSCHEDULABLE = (
    "0/2 nodes are available: pod has unbound immediate PersistentVolumeClaims. "
    "not found"
)


def _entry(
    name: str,
    state: str,
    *,
    kind: str = "container",
    message: str | None = None,
    restart_count: int = 0,
    ready: bool = False,
) -> dict[str, Any]:
    """One ``containerStatuses`` entry as the agent reports it (ADR-088)."""
    return {
        "name": name,
        "kind": kind,
        "ready": ready,
        "state": state,
        "message": message,
        "restart_count": restart_count,
        "image": "" if kind == "pod" else "registry.example.com/app:1.0",
        "started_at": None,
    }


async def _seed_entries(
    uow: SqlModelUnitOfWork,
    parents: Parents,
    name: str,
    *entries: dict[str, Any],
    phase: PodPhase = PodPhase.PENDING,
) -> None:
    uow.session.add(
        PodStatus(
            pod_name=name,
            namespace="styrmin-steps",
            phase=phase,
            container_statuses=list(entries),
            deployment_id=parents.deployment_id,
            last_polled_at=T0,
        )
    )
    await uow.session.flush()


async def _timed_out_error(uow: SqlModelUnitOfWork, parents: Parents) -> str:
    await apply_operator_report(_timed_out(parents), _at(300), uow)
    helmrelease = await _step(uow, parents, HELMRELEASE)
    return helmrelease.errors[0].message


async def test_pod_reasons_name_a_pod_that_is_not_scheduled(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)
    await _seed_entries(
        uow,
        parents,
        "app-0",
        _entry(
            "PodScheduled", "waiting:Unschedulable", kind="pod", message=UNSCHEDULABLE
        ),
    )

    assert await _timed_out_error(uow, parents) == (
        f"{TIMEOUT}\nPods not ready: app-0 (Unschedulable: {UNSCHEDULABLE})"
    )


async def test_pod_reasons_name_a_failing_init_container(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    # The back-off message of CrashLoopBackOff only gives the delay, so it is left out.
    await _running_helmrelease(uow, parents)
    await _seed_entries(
        uow,
        parents,
        "semaphore-0",
        _entry(
            "admin",
            "waiting:CrashLoopBackOff",
            kind="init",
            message="back-off 2m40s restarting failed container=admin",
            restart_count=5,
        ),
        _entry("semaphore", "waiting:PodInitializing"),
    )

    assert await _timed_out_error(uow, parents) == (
        f"{TIMEOUT}\nPods not ready: semaphore-0 (init container admin: CrashLoopBackOff)"
    )


@pytest.mark.parametrize(
    ("restarts", "text"),
    [
        (0, "still running"),
        (1, "running after 1 restart"),
        (5, "running after 5 restarts"),
    ],
)
async def test_pod_reasons_name_an_init_container_that_runs_again(
    uow: SqlModelUnitOfWork, parents: Parents, restarts: int, text: str
) -> None:
    # Between two back-offs the init container runs again, with no reason to read.
    # Without a restart, it may wait for a service that does not answer (0 restarts).
    await _running_helmrelease(uow, parents)
    await _seed_entries(
        uow,
        parents,
        "semaphore-0",
        _entry("admin", "running", kind="init", restart_count=restarts),
        _entry("semaphore", "waiting:PodInitializing"),
    )

    assert await _timed_out_error(uow, parents) == (
        f"{TIMEOUT}\nPods not ready: semaphore-0 (init container admin: {text})"
    )


async def test_pod_reasons_keep_the_kubelet_message_on_one_line(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)
    await _seed_entries(
        uow,
        parents,
        "app-0",
        _entry(
            "app",
            "waiting:CreateContainerConfigError",
            message='secret "db-credentials"\n  not found',
        ),
    )

    assert await _timed_out_error(uow, parents) == (
        f"{TIMEOUT}\nPods not ready: app-0 "
        '(app: CreateContainerConfigError: secret "db-credentials" not found)'
    )


async def test_pod_reasons_cut_a_long_message(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)
    await _seed_entries(
        uow, parents, "app-0", _entry("app", "waiting:ErrImagePull", message="x" * 400)
    )

    assert await _timed_out_error(uow, parents) == (
        f"{TIMEOUT}\nPods not ready: app-0 (app: ErrImagePull: {'x' * 299}…)"
    )


@pytest.mark.parametrize(
    "reason", ["RunContainerError", "CreatePodSandboxError", "ErrImageNeverPull"]
)
async def test_pod_reasons_name_any_reason_that_is_not_a_starting_one(
    uow: SqlModelUnitOfWork, parents: Parents, reason: str
) -> None:
    await _running_helmrelease(uow, parents)
    await _seed_entries(uow, parents, "app-0", _entry("app", f"waiting:{reason}"))

    assert await _timed_out_error(uow, parents) == (
        f"{TIMEOUT}\nPods not ready: app-0 (app: {reason})"
    )


async def test_pod_reasons_skip_starting_and_ready_containers(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    await _running_helmrelease(uow, parents)
    await _seed_entries(
        uow,
        parents,
        "app-0",
        _entry("migrate", "terminated:Completed", kind="init", restart_count=2),
        _entry("app", "waiting:PodInitializing"),
    )
    await _seed_entries(
        uow,
        parents,
        "app-1",
        _entry("proxy", "running", kind="init", ready=True),
        _entry("app", "running", restart_count=3, ready=True),
        _entry("worker", "waiting:ContainerCreating"),
        # Not ready without a restart, as when its readiness probe fails: not named.
        _entry("web", "running"),
    )

    await apply_operator_report(_timed_out(parents), _at(300), uow)

    helmrelease = await _step(uow, parents, HELMRELEASE)
    assert _errors(helmrelease) == [(1, TIMEOUT, _at(300))]
