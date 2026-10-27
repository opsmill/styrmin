"""Failure fields of steps reach the database and a ``READ_ONLY`` caller (spec 019, T059).

The status reports of the agent (``reportPodStatuses``, ``reportDeploymentStatuses``)
fail operator-phase steps through the phase history; seeded failed steps reach
``Query.step``, ``Task.steps`` and ``Query.deploymentTimeline``; ``recordStep``
stores the output of ``OUTPUT`` and ``FAILED`` events.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.agent.status.reporter import _extract_pod_data
from styrmin_backend.db.models import (
    Role,
    Step as StepRow,
    StepKind,
    StepStatus,
    Task as TaskRow,
    TaskStatus,
    TaskType,
)
from styrmin_backend.domain.steps import MAX_OUTPUT_LINES
from styrmin_backend.services.auth.bootstrap import ensure_actions_service_account
from styrmin_backend.services.auth.session import create_session

from tests.helpers.pods import load_pod

from ._queries import load_query
from .seeds import seed_application_instance, seed_deployment, seed_task, seed_user

T0 = datetime(2026, 10, 6, 10, 0, tzinfo=UTC)

UPGRADE_FAILED = "Helm upgrade failed for release app: context deadline exceeded"
STALLED = f"Failed to upgrade after 1 attempt(s): {UPGRADE_FAILED}"
ROLLBACK = "Helm rollback to previous release app.v1 with chart app@1.0.0 succeeded"
QUOTA_ERROR = "Update failed: ['networkpolicies is forbidden: exceeded quota']"


def _at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _utc(value: datetime | None) -> datetime | None:
    # SQLite drops the time zone; PostgreSQL keeps it.
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


async def _token(session: AsyncSession, role: Role) -> str:
    user = await seed_user(session, role=role)
    _row, token = await create_session(session, user.id)
    return token


async def _post(
    client: AsyncClient, operation: str, variables: dict[str, Any], token: str
) -> dict[str, Any]:
    response = await client.post(
        "/graphql",
        json={"query": load_query(operation), "variables": variables},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    return payload["data"]


def _condition(
    type_: str, at: datetime, status: str = "True", reason: str = "", message: str = ""
) -> dict[str, Any]:
    return {
        "type": type_,
        "status": status,
        "reason": reason,
        "message": message,
        "lastTransitionTime": at.isoformat(),
    }


def _stored_errors(row: StepRow) -> list[tuple[int, str, datetime]]:
    return [
        (
            error["attempt"],
            error["message"],
            datetime.fromisoformat(error["occurred_at"]),
        )
        for error in row.errors or []
    ]


def _returned_errors(step: dict[str, Any]) -> list[tuple[int, str, datetime]]:
    return [
        (
            error["attempt"],
            error["message"],
            datetime.fromisoformat(error["occurredAt"]),
        )
        for error in step["errors"]
    ]


async def _stored(session: AsyncSession, step_id: UUID) -> StepRow:
    session.expire_all()
    row = await session.get(StepRow, step_id)
    assert row is not None
    return row


@dataclass(frozen=True)
class Rollout:
    deployment_id: UUID
    instance_id: UUID
    task_id: UUID
    step_ids: dict[str, UUID]


async def _seed_rollout(session: AsyncSession, *, helmrelease_running: bool) -> Rollout:
    """An upgrade task of an instance with its four operator-phase steps."""
    deployment = await seed_deployment(session)
    instance = await seed_application_instance(session, deployment=deployment)
    task = TaskRow(
        type=TaskType.UPGRADE_INSTANCE,
        status=TaskStatus.SUCCESS,
        deployment_id=deployment.id,
        instance_id=instance.id,
    )
    session.add(task)
    await session.commit()
    prerequisites = (
        {"status": StepStatus.SUCCEEDED, "started_at": T0, "ended_at": _at(10)}
        if helmrelease_running
        else {"status": StepStatus.RUNNING, "started_at": T0}
    )
    helmrelease = (
        {"status": StepStatus.RUNNING, "started_at": _at(10)}
        if helmrelease_running
        else {"status": StepStatus.PENDING, "attempt_count": 0}
    )
    rows = [
        StepRow(
            task_id=task.id,
            key=key,
            name=name,
            kind=StepKind.OPERATOR_PHASE,
            **({"attempt_count": 1} | fields),
        )
        for key, name, fields in (
            (
                "operator:prerequisites",
                "Create network policies and secrets",
                prerequisites,
            ),
            ("operator:helmrelease", "Install or upgrade the HelmRelease", helmrelease),
            (
                "operator:services",
                "Create services and middlewares",
                {"status": StepStatus.PENDING, "attempt_count": 0},
            ),
            (
                "operator:ready",
                "Wait for the deployment to be ready",
                {"status": StepStatus.PENDING, "attempt_count": 0},
            ),
        )
    ]
    session.add_all(rows)
    await session.commit()
    return Rollout(
        deployment_id=deployment.id,
        instance_id=instance.id,
        task_id=task.id,
        step_ids={row.key: row.id for row in rows},
    )


async def _report_status(
    client: AsyncClient,
    token: str,
    rollout: Rollout,
    *,
    message: str,
    conditions: list[dict[str, Any]],
) -> None:
    data = await _post(
        client,
        "report_deployment_statuses",
        {
            "reports": [
                {
                    "deploymentId": str(rollout.deployment_id),
                    "instanceId": str(rollout.instance_id),
                    "phase": "Failed",
                    "displayState": "Error",
                    "message": message,
                    "conditions": conditions,
                }
            ]
        },
        token,
    )
    assert data["reportDeploymentStatuses"]["success"] is True


# The agent's status reports fail operator-phase steps; a READ_ONLY caller reads them.


@pytest.mark.asyncio
async def test_failed_helmrelease_report_reaches_the_database_and_read_only(
    unauth_client: AsyncClient, session: AsyncSession, admin_token: str
) -> None:
    rollout = await _seed_rollout(session, helmrelease_running=True)
    await _post(
        unauth_client,
        "report_pod_statuses",
        {
            "reports": [
                {
                    "deploymentId": str(rollout.deployment_id),
                    "pods": [
                        {
                            "podName": "app-0",
                            "namespace": "styrmin-app",
                            "phase": "PENDING",
                            "ready": False,
                            "restartCount": 0,
                            "containerStatuses": [
                                {
                                    "name": "app",
                                    "ready": False,
                                    "state": "waiting:ImagePullBackOff",
                                    "restart_count": 0,
                                    "image": "registry.example.com/app:missing",
                                    "started_at": None,
                                }
                            ],
                        }
                    ],
                }
            ]
        },
        admin_token,
    )

    await _report_status(
        unauth_client,
        admin_token,
        rollout,
        message=STALLED,
        conditions=[
            _condition(
                "HelmReleaseReady",
                _at(320),
                status="False",
                reason="UpgradeFailed",
                message=UPGRADE_FAILED,
            ),
            _condition(
                "HelmReleaseRemediated",
                _at(325),
                reason="RollbackSucceeded",
                message=ROLLBACK,
            ),
            _condition("Ready", _at(330), status="False", reason="RetriesExceeded"),
        ],
    )

    stalled_error = f"{STALLED}\nPods not ready: app-0 (app: ImagePullBackOff)"
    expected_errors = [
        (1, f"UpgradeFailed: {UPGRADE_FAILED}", _at(320)),
        (1, stalled_error, _at(330)),
    ]
    row = await _stored(session, rollout.step_ids["operator:helmrelease"])
    assert row.status is StepStatus.FAILED
    assert (row.attempt_count, _utc(row.ended_at)) == (1, _at(330))
    assert _stored_errors(row) == expected_errors
    assert row.detail == f"UpgradeFailed: {UPGRADE_FAILED}"
    assert (_utc(row.rolled_back_at), row.rollback_message) == (_at(325), ROLLBACK)

    read_only = await _token(session, Role.READ_ONLY)
    data = await _post(
        unauth_client, "get_task_steps", {"taskId": str(rollout.task_id)}, read_only
    )
    returned = {step["key"]: step for step in data["task"]["steps"]}
    step = returned["operator:helmrelease"]
    assert step["status"] == "FAILED"
    assert step["attemptCount"] == 1
    assert _returned_errors(step) == expected_errors
    assert step["error"] == stalled_error
    assert step["detail"] == f"UpgradeFailed: {UPGRADE_FAILED}"
    assert datetime.fromisoformat(step["rolledBackAt"]) == _at(325)
    assert step["rollbackMessage"] == ROLLBACK
    assert (step["hasOutput"], step["output"], step["outputTruncated"]) == (
        False,
        None,
        False,
    )
    assert returned["operator:prerequisites"]["status"] == "SUCCEEDED"


@pytest.mark.asyncio
async def test_failure_causes_of_kind_pods_reach_the_step_and_read_only(
    unauth_client: AsyncClient, session: AsyncSession, admin_token: str
) -> None:
    """#574: the agent's report of three pods from kind names each cause in the step error."""
    rollout = await _seed_rollout(session, helmrelease_running=True)
    pods = [
        _extract_pod_data(await load_pod(name)).model_dump(mode="json", by_alias=True)
        for name in (
            "pod_image_pull_failing",
            "pod_init_container_failing",
            "pod_not_scheduled",
        )
    ]
    await _post(
        unauth_client,
        "report_pod_statuses",
        {"reports": [{"deploymentId": str(rollout.deployment_id), "pods": pods}]},
        admin_token,
    )
    timeout = "Deployment did not reach Ready within 270s (phase: CreatingHelmRelease)"
    await _report_status(
        unauth_client, admin_token, rollout, message=timeout, conditions=[]
    )

    image_message = (
        'Back-off pulling image "traefik/whoami:v1.99.99": ErrImagePull: rpc error: '
        "code = NotFound desc = failed to pull and unpack image "
        '"docker.io/traefik/whoami:v1.99.99": failed to resolve reference '
        '"docker.io/traefik/whoami:v1.99.99": docker.io/traefik/whoami:v1.99.99: not found'
    )
    expected = (
        f"{timeout}\nPods not ready: "
        f"styrmin-app-5c88845fb4-4ggxf (Unschedulable: 0/2 nodes are available: "
        "pod has unbound immediate PersistentVolumeClaims. not found), "
        f"styrmin-app-7dd9b47888-7l7n2 (app: ImagePullBackOff: {image_message}), "
        "styrmin-semaphore-cfc7bb7b9-v9l2d (init container admin: running after 7 restarts)"
    )
    row = await _stored(session, rollout.step_ids["operator:helmrelease"])
    assert row.status is StepStatus.FAILED
    assert [message for _attempt, message, _at in _stored_errors(row)] == [expected]

    read_only = await _token(session, Role.READ_ONLY)
    data = await _post(
        unauth_client, "get_task_steps", {"taskId": str(rollout.task_id)}, read_only
    )
    step = {s["key"]: s for s in data["task"]["steps"]}["operator:helmrelease"]
    assert step["error"] == expected
    data = await _post(
        unauth_client,
        "list_pod_statuses",
        {"deploymentId": str(rollout.deployment_id)},
        read_only,
    )
    returned = {pod["podName"]: pod for pod in data["podStatuses"]}
    assert returned["styrmin-semaphore-cfc7bb7b9-v9l2d"]["restartCount"] == 7
    assert [
        (entry["kind"], entry["name"], entry["state"], entry["message"])
        for entry in returned["styrmin-app-5c88845fb4-4ggxf"]["containerStatuses"]
    ] == [
        (
            "pod",
            "PodScheduled",
            "waiting:Unschedulable",
            "0/2 nodes are available: pod has unbound immediate PersistentVolumeClaims. "
            "not found",
        )
    ]


@pytest.mark.asyncio
async def test_operator_retries_reach_read_only_as_attempts(
    unauth_client: AsyncClient, session: AsyncSession, admin_token: str
) -> None:
    rollout = await _seed_rollout(session, helmrelease_running=False)

    # The operator's handler fails, then retries 30 seconds later.
    for seconds in (20, 55):
        await _report_status(
            unauth_client,
            admin_token,
            rollout,
            message=QUOTA_ERROR,
            conditions=[
                _condition(
                    "HelmReleaseReady",
                    _at(seconds),
                    status="Unknown",
                    reason="Progressing",
                    message="Waiting for FluxCD to apply the HelmRelease",
                )
            ],
        )

    expected_errors = [(1, QUOTA_ERROR, _at(20)), (2, QUOTA_ERROR, _at(55))]
    row = await _stored(session, rollout.step_ids["operator:prerequisites"])
    assert (row.status, row.attempt_count) == (StepStatus.FAILED, 2)
    assert _stored_errors(row) == expected_errors

    read_only = await _token(session, Role.READ_ONLY)
    data = await _post(
        unauth_client,
        "get_deployment_timeline_steps",
        {"deploymentId": str(rollout.deployment_id)},
        read_only,
    )
    (task,) = [
        entry["task"]
        for entry in data["deploymentTimeline"]
        if entry["task"]["id"] == str(rollout.task_id)
    ]
    step = {step["key"]: step for step in task["steps"]}["operator:prerequisites"]
    assert (step["status"], step["attemptCount"]) == ("FAILED", 2)
    assert _returned_errors(step) == expected_errors
    assert step["error"] == QUOTA_ERROR


# Seeded failed steps reach a READ_ONLY caller through every read path.


@dataclass(frozen=True)
class SeededFailures:
    deployment_id: UUID
    task_id: UUID
    command_step_id: UUID
    helmrelease_step_id: UUID


@pytest.fixture
async def failures(session: AsyncSession) -> SeededFailures:
    deployment = await seed_deployment(session)
    task = await seed_task(
        session,
        deployment=deployment,
        task_type=TaskType.RUN_JOB,
        status=TaskStatus.FAILED,
    )
    command = StepRow(
        task_id=task.id,
        key="command",
        name="Run the job's command",
        kind=StepKind.COMMAND,
        status=StepStatus.FAILED,
        started_at=_at(0),
        ended_at=_at(40),
        attempt_count=1,
        errors=[
            {
                "attempt": 1,
                "message": "Job failed: exit code 3",
                "occurred_at": _at(40).isoformat(),
            }
        ],
        output="step-output-1\nstep-output-2\n",
        output_truncated=True,
    )
    helmrelease = StepRow(
        task_id=task.id,
        key="operator:helmrelease",
        name="Install or upgrade the HelmRelease",
        kind=StepKind.OPERATOR_PHASE,
        status=StepStatus.FAILED,
        started_at=_at(50),
        ended_at=_at(400),
        attempt_count=2,
        errors=[
            {
                "attempt": 1,
                "message": f"UpgradeFailed: {UPGRADE_FAILED}",
                "occurred_at": _at(350).isoformat(),
            },
            {
                "attempt": 2,
                "message": "Deployment did not reach Ready within 300s",
                "occurred_at": _at(400).isoformat(),
            },
        ],
        detail=f"UpgradeFailed: {UPGRADE_FAILED}",
        rolled_back_at=_at(355),
        rollback_message=ROLLBACK,
    )
    session.add_all([command, helmrelease])
    await session.commit()
    return SeededFailures(
        deployment_id=deployment.id,
        task_id=task.id,
        command_step_id=command.id,
        helmrelease_step_id=helmrelease.id,
    )


EXPECTED_FAILURE_FIELDS = {
    "command": {
        "errors": [(1, "Job failed: exit code 3", _at(40))],
        "error": "Job failed: exit code 3",
        "detail": None,
        "rolledBackAt": None,
        "rollbackMessage": None,
        "hasOutput": True,
        "output": "step-output-1\nstep-output-2\n",
        "outputTruncated": True,
    },
    "operator:helmrelease": {
        "errors": [
            (1, f"UpgradeFailed: {UPGRADE_FAILED}", _at(350)),
            (2, "Deployment did not reach Ready within 300s", _at(400)),
        ],
        "error": "Deployment did not reach Ready within 300s",
        "detail": f"UpgradeFailed: {UPGRADE_FAILED}",
        "rolledBackAt": _at(355),
        "rollbackMessage": ROLLBACK,
        "hasOutput": False,
        "output": None,
        "outputTruncated": False,
    },
}


def _failure_fields(step: dict[str, Any]) -> dict[str, Any]:
    rolled_back_at = step["rolledBackAt"]
    return {
        "errors": _returned_errors(step),
        "error": step["error"],
        "detail": step["detail"],
        "rolledBackAt": datetime.fromisoformat(rolled_back_at)
        if rolled_back_at
        else None,
        "rollbackMessage": step["rollbackMessage"],
        "hasOutput": step["hasOutput"],
        "output": step["output"],
        "outputTruncated": step["outputTruncated"],
    }


async def _read_steps(
    client: AsyncClient, failures: SeededFailures, operation: str, token: str
) -> dict[str, dict[str, Any]]:
    if operation == "get_step":
        steps = [
            (await _post(client, operation, {"stepId": str(step_id)}, token))["step"]
            for step_id in (failures.command_step_id, failures.helmrelease_step_id)
        ]
    elif operation == "get_task_steps":
        data = await _post(client, operation, {"taskId": str(failures.task_id)}, token)
        steps = data["task"]["steps"]
    else:
        data = await _post(
            client, operation, {"deploymentId": str(failures.deployment_id)}, token
        )
        (steps,) = [
            entry["task"]["steps"]
            for entry in data["deploymentTimeline"]
            if entry["task"]["id"] == str(failures.task_id)
        ]
    return {step["key"]: step for step in steps}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation", ["get_step", "get_task_steps", "get_deployment_timeline_steps"]
)
async def test_failure_fields_reach_read_only(
    unauth_client: AsyncClient,
    session: AsyncSession,
    failures: SeededFailures,
    operation: str,
) -> None:
    token = await _token(session, Role.READ_ONLY)

    steps = await _read_steps(unauth_client, failures, operation, token)

    assert {
        key: _failure_fields(step) for key, step in steps.items()
    } == EXPECTED_FAILURE_FIELDS


# recordStep: OUTPUT and FAILED events store the output.


@pytest.mark.asyncio
async def test_record_step_stores_output_and_failed_events(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    task = await seed_task(session, task_type=TaskType.RUN_JOB)
    actions_user = await ensure_actions_service_account(session)
    _row, actions_token = await create_session(session, actions_user)
    started = await _post(
        unauth_client,
        "record_step",
        {
            "input": {
                "taskId": str(task.id),
                "key": "command",
                "name": "Run the job's command",
                "kind": "COMMAND",
                "event": "STARTED",
                "occurredAt": _at(0).isoformat(),
            }
        },
        actions_token,
    )
    step_id = UUID(started["recordStep"]["id"])
    lines = [f"line {index}" for index in range(MAX_OUTPUT_LINES + 50)]

    await _post(
        unauth_client,
        "record_step",
        {
            "input": {
                "stepId": str(step_id),
                "event": "OUTPUT",
                "output": "\n".join(lines) + "\n",
                "occurredAt": _at(20).isoformat(),
            }
        },
        actions_token,
    )

    # The server keeps the end of the output and says it cut the start.
    row = await _stored(session, step_id)
    assert row.status is StepStatus.RUNNING
    assert row.output == "\n".join(lines[-MAX_OUTPUT_LINES:]) + "\n"
    assert row.output_truncated is True

    await _post(
        unauth_client,
        "record_step",
        {
            "input": {
                "stepId": str(step_id),
                "event": "FAILED",
                "error": "Job failed: exit code 3",
                "output": "step-output-1\nstep-output-2\n",
                "outputTruncated": False,
                "occurredAt": _at(40).isoformat(),
            }
        },
        actions_token,
    )

    row = await _stored(session, step_id)
    assert row.status is StepStatus.FAILED
    assert _stored_errors(row) == [(1, "Job failed: exit code 3", _at(40))]
    assert (row.output, row.output_truncated) == (
        "step-output-1\nstep-output-2\n",
        False,
    )

    read_only = await _token(session, Role.READ_ONLY)
    step = (
        await _post(unauth_client, "get_step", {"stepId": str(step_id)}, read_only)
    )["step"]
    assert step["status"] == "FAILED"
    assert step["error"] == "Job failed: exit code 3"
    assert (step["hasOutput"], step["output"], step["outputTruncated"]) == (
        True,
        "step-output-1\nstep-output-2\n",
        False,
    )
