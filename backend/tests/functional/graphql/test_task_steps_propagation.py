"""``Task.steps``, ``Task.startedByStepId`` and ``Task.type`` reach the caller (spec 019, T040).

Seeded steps reach a ``READ_ONLY`` user through ``Query.task`` (query
fallback) and ``Query.deploymentTimeline`` (read model), and so does the
deployment's last agent report as ``Step.noReportSince`` (T080). Each mutation
of research D19 stores its task with the type its caller means.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    DeploymentState,
    DeploymentStatus,
    Role,
    Step as StepRow,
    StepKind,
    StepStatus,
    Task as TaskRow,
    TaskStatus,
    TaskType,
)
from styrmin_backend.services.auth.session import create_session

from ._queries import load_query
from .conftest import gql
from .seeds import (
    seed_application_driver_version,
    seed_deployment,
    seed_environment,
    seed_task,
    seed_user,
)

T0 = datetime(2026, 10, 6, 10, 0, tzinfo=UTC)


def _at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


async def _read_only_token(session: AsyncSession) -> str:
    user = await seed_user(session, role=Role.READ_ONLY)
    _row, token = await create_session(session, user.id)
    return token


async def _read(
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


def _parse_times(step: dict[str, Any]) -> dict[str, Any]:
    for field in ("startedAt", "endedAt", "rolledBackAt", "noReportSince"):
        if step[field] is not None:
            step[field] = datetime.fromisoformat(step[field])
    for error in step["errors"]:
        error["occurredAt"] = datetime.fromisoformat(error["occurredAt"])
    return step


@dataclass(frozen=True)
class SeededTimeline:
    deployment_id: UUID
    task_id: UUID
    started_task_id: UUID
    superseding_task_id: UUID
    hook_step_id: UUID
    expected_steps: list[dict[str, Any]]


def _step_fields(
    step: StepRow, **views: Any
) -> dict[str, Any]:  # the payload the API returns for a seeded row
    duration = (
        (step.ended_at - step.started_at).total_seconds()
        if step.started_at is not None and step.ended_at is not None
        else None
    )
    errors = [
        {
            "attempt": error["attempt"],
            "message": error["message"],
            "occurredAt": datetime.fromisoformat(error["occurred_at"]),
        }
        for error in step.errors or []
    ]
    return {
        "id": str(step.id),
        "key": step.key,
        "name": step.name,
        "kind": step.kind.name,
        "status": step.status.name,
        "startedAt": step.started_at,
        "endedAt": step.ended_at,
        "durationSeconds": duration,
        "attemptCount": step.attempt_count,
        "errors": errors,
        "error": errors[-1]["message"] if errors else None,
        "detail": step.detail,
        "rolledBackAt": step.rolled_back_at,
        "rollbackMessage": step.rollback_message,
        "hasOutput": bool(step.output),
        "output": step.output,
        "outputTruncated": step.output_truncated,
        "supersededBy": None,
        "startedTasks": [],
        "noReportSince": None,
        "taskId": str(step.task_id),
        "backupId": None,
        "restoreId": None,
        **views,
    }


@pytest.fixture
async def seeded(session: AsyncSession) -> SeededTimeline:
    """An upgrade task with four steps, a task its hook started, and a later task."""
    deployment = await seed_deployment(session)
    task = await seed_task(
        session,
        deployment=deployment,
        task_type=TaskType.UPGRADE_INSTANCE,
        status=TaskStatus.FAILED,
    )
    superseding = await seed_task(
        session, deployment=deployment, task_type=TaskType.UPDATE_INSTANCE
    )
    # Inserted out of start order: the API orders by start, pending steps last.
    pending = StepRow(
        task_id=task.id,
        key="operator:ready",
        name="Wait until the deployment is ready",
        kind=StepKind.OPERATOR_PHASE,
        status=StepStatus.PENDING,
    )
    helm_release = StepRow(
        task_id=task.id,
        key="operator:helmrelease",
        name="Install or upgrade the HelmRelease",
        kind=StepKind.OPERATOR_PHASE,
        status=StepStatus.SUPERSEDED,
        started_at=_at(80),
        ended_at=_at(200),
        attempt_count=1,
        detail="UpgradeFailed: Helm upgrade failed",
        rolled_back_at=_at(190),
        rollback_message="Helm rollback to previous release succeeded",
        superseded_by_task_id=superseding.id,
    )
    hook = StepRow(
        task_id=task.id,
        key="hook:upgrade:core",
        name="Run the upgrade hook",
        kind=StepKind.HOOK,
        status=StepStatus.FAILED,
        started_at=_at(10),
        ended_at=_at(70),
        attempt_count=2,
        errors=[
            {
                "attempt": 1,
                "message": "first failure",
                "occurred_at": _at(30).isoformat(),
            },
            {
                "attempt": 2,
                "message": "second failure",
                "occurred_at": _at(70).isoformat(),
            },
        ],
        output="step-output-1\nstep-output-2\n",
        output_truncated=True,
    )
    plan = StepRow(
        task_id=task.id,
        key="plan",
        name="Plan the changes",
        kind=StepKind.PLAN,
        status=StepStatus.SUCCEEDED,
        started_at=_at(0),
        ended_at=_at(5),
        attempt_count=1,
    )
    session.add_all([pending, helm_release, hook, plan])
    await session.commit()
    started = TaskRow(
        type=TaskType.STOP_COMPONENTS,
        status=TaskStatus.SUCCESS,
        deployment_id=deployment.id,
        started_by_step_id=hook.id,
    )
    session.add(started)
    await session.commit()
    return SeededTimeline(
        deployment_id=deployment.id,
        task_id=task.id,
        started_task_id=started.id,
        superseding_task_id=superseding.id,
        hook_step_id=hook.id,
        expected_steps=[
            _step_fields(plan),
            _step_fields(hook, startedTasks=[{"id": str(started.id)}]),
            _step_fields(helm_release, supersededBy={"id": str(superseding.id)}),
            _step_fields(pending),
        ],
    )


# Task.steps and Task.startedByStepId: seeded rows reach a READ_ONLY caller.


@pytest.mark.asyncio
async def test_task_steps_reach_read_only_through_task(
    unauth_client: AsyncClient, session: AsyncSession, seeded: SeededTimeline
) -> None:
    token = await _read_only_token(session)

    data = await _read(
        unauth_client, "get_task_steps", {"taskId": str(seeded.task_id)}, token
    )

    task = data["task"]
    assert task["id"] == str(seeded.task_id)
    assert task["type"] == TaskType.UPGRADE_INSTANCE.value
    assert task["startedByStepId"] is None
    assert [_parse_times(step) for step in task["steps"]] == seeded.expected_steps


@pytest.mark.asyncio
async def test_task_steps_reach_read_only_through_timeline(
    unauth_client: AsyncClient, session: AsyncSession, seeded: SeededTimeline
) -> None:
    token = await _read_only_token(session)

    data = await _read(
        unauth_client,
        "get_deployment_timeline_steps",
        {"deploymentId": str(seeded.deployment_id)},
        token,
    )

    tasks = {entry["task"]["id"]: entry["task"] for entry in data["deploymentTimeline"]}
    assert set(tasks) == {
        str(seeded.task_id),
        str(seeded.started_task_id),
        str(seeded.superseding_task_id),
    }
    task = tasks[str(seeded.task_id)]
    assert [_parse_times(step) for step in task["steps"]] == seeded.expected_steps
    assert tasks[str(seeded.started_task_id)]["steps"] == []
    assert tasks[str(seeded.superseding_task_id)]["steps"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation", ["get_task_steps", "get_deployment_timeline_steps"]
)
async def test_started_by_step_id_reaches_read_only(
    unauth_client: AsyncClient,
    session: AsyncSession,
    seeded: SeededTimeline,
    operation: str,
) -> None:
    token = await _read_only_token(session)

    if operation == "get_task_steps":
        data = await _read(
            unauth_client, operation, {"taskId": str(seeded.started_task_id)}, token
        )
        started = data["task"]
    else:
        data = await _read(
            unauth_client,
            operation,
            {"deploymentId": str(seeded.deployment_id)},
            token,
        )
        (started,) = [
            entry["task"]
            for entry in data["deploymentTimeline"]
            if entry["task"]["id"] == str(seeded.started_task_id)
        ]

    assert started["type"] == TaskType.STOP_COMPONENTS.value
    assert started["startedByStepId"] == str(seeded.hook_step_id)


@pytest.mark.asyncio
async def test_task_without_steps_returns_an_empty_list(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    task = await seed_task(session, task_type=TaskType.UPDATE_INSTANCE)
    token = await _read_only_token(session)

    data = await _read(unauth_client, "get_task_steps", {"taskId": str(task.id)}, token)

    assert data["task"]["steps"] == []
    assert data["task"]["startedByStepId"] is None


# Step.noReportSince: the deployment's last agent report reaches a READ_ONLY caller.


async def _read_steps(
    client: AsyncClient, operation: str, task: TaskRow, token: str
) -> list[dict[str, Any]]:
    if operation == "get_task_steps":
        data = await _read(client, operation, {"taskId": str(task.id)}, token)
        return data["task"]["steps"]
    data = await _read(
        client, operation, {"deploymentId": str(task.deployment_id)}, token
    )
    (entry,) = data["deploymentTimeline"]
    return entry["task"]["steps"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation", ["get_task_steps", "get_deployment_timeline_steps"]
)
@pytest.mark.parametrize(
    ("report_age", "shown"),
    [
        pytest.param(timedelta(minutes=2), True, id="report-2-minutes-ago"),
        pytest.param(timedelta(seconds=10), False, id="report-10-seconds-ago"),
    ],
)
async def test_no_report_since_reaches_read_only(
    unauth_client: AsyncClient,
    session: AsyncSession,
    operation: str,
    report_age: timedelta,
    shown: bool,
) -> None:
    now = datetime.now(UTC)
    deployment = await seed_deployment(session)
    task = await seed_task(
        session,
        deployment=deployment,
        task_type=TaskType.UPGRADE_INSTANCE,
        status=TaskStatus.SUCCESS,
    )
    last_report = now - report_age
    # Started before the last report, so only the report decides the notice.
    running = StepRow(
        task_id=task.id,
        key="operator:helmrelease",
        name="Install or upgrade the HelmRelease",
        kind=StepKind.OPERATOR_PHASE,
        status=StepStatus.RUNNING,
        started_at=now - timedelta(minutes=5),
        attempt_count=1,
    )
    finished = StepRow(
        task_id=task.id,
        key="operator:prerequisites",
        name="Create network policies and secrets",
        kind=StepKind.OPERATOR_PHASE,
        status=StepStatus.SUCCEEDED,
        started_at=now - timedelta(minutes=6),
        ended_at=now - timedelta(minutes=5),
        attempt_count=1,
    )
    session.add_all(
        [
            running,
            finished,
            DeploymentStatus(
                deployment_id=deployment.id,
                phase="CreatingHelmRelease",
                last_polled_at=last_report,
            ),
        ]
    )
    await session.commit()
    token = await _read_only_token(session)

    steps = {
        step["key"]: _parse_times(step)
        for step in await _read_steps(unauth_client, operation, task, token)
    }

    assert steps[running.key]["noReportSince"] == (last_report if shown else None)
    assert steps[finished.key]["noReportSince"] is None


# Task.type: each mutation of research D19 stores its task with its type.


def _flow_info() -> AsyncMock:
    async def _run(*_args: Any, **_kwargs: Any) -> Any:
        return type("FlowInfo", (), {"id": uuid4()})()

    return AsyncMock(side_effect=_run)


async def _deploy(client: AsyncClient, session: AsyncSession) -> UUID:
    driver_name = f"driver-{uuid4().hex[:8]}"
    await seed_application_driver_version(session, driver_name=driver_name)
    environment = await seed_environment(session)
    data = await gql(
        client,
        "deploy",
        {
            "driver": driver_name,
            "version": "1.0.0",
            "environmentId": str(environment.id),
            "name": f"app-{uuid4().hex[:8]}",
        },
    )
    return UUID(data["deploy"]["id"])


async def _update_deployment(client: AsyncClient, session: AsyncSession) -> UUID:
    deployment = await seed_deployment(session)
    data = await gql(
        client,
        "update_deployment",
        {
            "deploymentId": str(deployment.id),
            "input": {"ipWhitelist": ["10.0.0.0/8"]},
        },
    )
    return UUID(data["updateDeployment"]["id"])


async def _update_deployment_version(
    client: AsyncClient, session: AsyncSession
) -> UUID:
    deployment = await seed_deployment(session)
    data = await gql(
        client,
        "update_deployment_version",
        {"deploymentId": str(deployment.id), "version": "1.0.1"},
    )
    return UUID(data["updateDeploymentVersion"]["id"])


async def _stop_components(client: AsyncClient, session: AsyncSession) -> UUID:
    deployment = await seed_deployment(session)
    data = await gql(
        client,
        "stop_components",
        {"deploymentId": str(deployment.id), "components": []},
    )
    return UUID(data["stopComponents"]["id"])


async def _start_components(client: AsyncClient, session: AsyncSession) -> UUID:
    deployment = await seed_deployment(session)
    data = await gql(
        client,
        "start_components",
        {"deploymentId": str(deployment.id), "components": []},
    )
    return UUID(data["startComponents"]["id"])


async def _update_environment(client: AsyncClient, session: AsyncSession) -> UUID:
    environment = await seed_environment(session)
    deployment_id = (await seed_deployment(session, environment=environment)).id
    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment.id),
            "input": {"envVars": [{"name": "OTEL_ENDPOINT", "value": "https://otel"}]},
        },
    )
    session.expire_all()
    (task,) = (
        await session.exec(
            select(TaskRow).where(TaskRow.deployment_id == deployment_id)
        )
    ).all()
    return task.id


async def _delete_deployment(client: AsyncClient, session: AsyncSession) -> UUID:
    deployment = await seed_deployment(session)
    deployment.status = DeploymentState.RUNNING
    session.add(deployment)
    await session.commit()
    data = await gql(client, "delete_deployment", {"deploymentId": str(deployment.id)})
    return UUID(data["deleteDeployment"]["id"])


Mutate = Callable[[AsyncClient, AsyncSession], Awaitable[UUID]]

D19_MUTATIONS: list[tuple[str, Mutate, TaskType]] = [
    ("deploy", _deploy, TaskType.CREATE_INSTANCE),
    ("updateDeployment", _update_deployment, TaskType.UPDATE_INSTANCE),
    (
        "updateDeploymentVersion",
        _update_deployment_version,
        TaskType.UPGRADE_INSTANCE,
    ),
    ("stopComponents", _stop_components, TaskType.STOP_COMPONENTS),
    ("startComponents", _start_components, TaskType.START_COMPONENTS),
    ("updateEnvironment", _update_environment, TaskType.UPDATE_INSTANCE),
    ("deleteDeployment", _delete_deployment, TaskType.DELETE_DEPLOYMENT),
]


@pytest.fixture
def dispatch(prefect_manager_mock: Any, mocker: Any) -> None:
    prefect_manager_mock.run_action = _flow_info()
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())
    mocker.patch(
        "styrmin_backend.services.deployment.patch_custom_resource", autospec=True
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("dispatch")
@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        pytest.param(mutate, expected, id=name)
        for name, mutate, expected in D19_MUTATIONS
    ],
)
async def test_task_type_of_each_mutation(
    client: AsyncClient,
    unauth_client: AsyncClient,
    session: AsyncSession,
    mutate: Mutate,
    expected: TaskType,
) -> None:
    task_id = await mutate(client, session)

    session.expire_all()
    row = await session.get(TaskRow, task_id)
    assert row is not None
    assert row.type is expected
    token = await _read_only_token(session)
    data = await _read(unauth_client, "get_task", {"taskId": str(task_id)}, token)
    assert data["task"]["type"] == expected.value


@pytest.mark.asyncio
@pytest.mark.usefixtures("dispatch")
async def test_steps_recorded_by_delete_deployment_reach_task_steps(
    client: AsyncClient, unauth_client: AsyncClient, session: AsyncSession
) -> None:
    task_id = await _delete_deployment(client, session)
    token = await _read_only_token(session)

    data = await _read(unauth_client, "get_task_steps", {"taskId": str(task_id)}, token)

    steps = data["task"]["steps"]
    assert [(step["key"], step["status"]) for step in steps] == [
        ("resource:delete-request", "SUCCEEDED"),
        ("operator:teardown", "PENDING"),
    ]
    assert steps[0]["endedAt"] is not None
    assert {step["taskId"] for step in steps} == {str(task_id)}
