"""``recordStep`` and ``Query.step`` reach the database and back (spec 019, T021).

``recordStep`` runs as the ``styrmin-actions`` user, the caller the flow step
reporter uses; every other caller is rejected and writes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend import config
from styrmin_backend.agent.steps import reporter as reporter_module
from styrmin_backend.agent.steps.reporter import StepReporter
from styrmin_backend.agent.tasks.utils import API_TOKEN_ENV, TASK_ID_ENV
from styrmin_backend.db.models import (
    Backup,
    BackupStatus,
    Restore,
    RestoreStatus,
    Role,
    Step as StepRow,
    StepKind,
    StepStatus,
    Task as TaskRow,
    TaskType,
)
from styrmin_backend.services.auth.bootstrap import ensure_actions_service_account
from styrmin_backend.server.app import app
from styrmin_backend.services.auth.session import create_session

from ._queries import load_query
from .seeds import seed_application_instance, seed_task, seed_user

STARTED_AT = datetime(2026, 10, 6, 10, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Parents:
    task_id: UUID
    backup_id: UUID
    restore_id: UUID

    def variables(self, parent: str) -> dict[str, str]:
        """The ``recordStep`` input fields naming ``parent``."""
        return {f"{parent}Id": str(getattr(self, f"{parent}_id"))}


@pytest.fixture
async def parents(session: AsyncSession) -> Parents:
    instance = await seed_application_instance(session)
    task = await seed_task(session, task_type=TaskType.UPGRADE_INSTANCE)
    backup = Backup(
        name="steps-backup", status=BackupStatus.IN_PROGRESS, instance_id=instance.id
    )
    session.add(backup)
    await session.commit()
    restore = Restore(
        name="steps-restore",
        status=RestoreStatus.IN_PROGRESS,
        target_namespace="steps",
        backup_id=backup.id,
    )
    session.add(restore)
    await session.commit()
    return Parents(task_id=task.id, backup_id=backup.id, restore_id=restore.id)


@pytest.fixture
async def actions_token(session: AsyncSession) -> str:
    """A session token of ``styrmin-actions``, as ``action_api_token`` mints it."""
    user_id = await ensure_actions_service_account(session)
    _row, token = await create_session(session, user_id)
    return token


async def _token_for(session: AsyncSession, role: Role) -> str:
    user = await seed_user(session, role=role)
    _row, token = await create_session(session, user.id)
    return token


async def _post(
    client: AsyncClient, operation: str, variables: dict[str, Any], token: str | None
) -> dict[str, Any]:
    response = await client.post(
        "/graphql",
        json={"query": load_query(operation), "variables": variables},
        headers={"Authorization": f"Bearer {token}"} if token else {},
    )
    assert response.status_code == 200
    return response.json()


async def _record(client: AsyncClient, token: str, **record: Any) -> dict[str, Any]:
    payload = await _post(client, "record_step", {"input": record}, token)
    assert "errors" not in payload, payload
    return payload["data"]["recordStep"]


async def _stored_steps(session: AsyncSession) -> list[StepRow]:
    session.expire_all()
    return list((await session.exec(select(StepRow))).all())


async def _stored_step(session: AsyncSession, step_id: str) -> StepRow:
    (row,) = [row for row in await _stored_steps(session) if str(row.id) == step_id]
    return row


def _utc(value: datetime | None) -> datetime | None:
    # SQLite drops the time zone; PostgreSQL keeps it.
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _at(seconds: int) -> str:
    return (STARTED_AT + timedelta(seconds=seconds)).isoformat()


async def _start(
    client: AsyncClient, token: str, parents: Parents, parent: str
) -> dict[str, Any]:
    return await _record(
        client,
        token,
        **parents.variables(parent),
        key="hook:upgrade:core",
        name="Run the upgrade",
        kind="HOOK",
        event="STARTED",
        occurredAt=_at(0),
    )


PARENTS = ["task", "backup", "restore"]


# recordStep: each event, each parent type, reaches the database.


@pytest.mark.asyncio
@pytest.mark.parametrize("parent", PARENTS)
async def test_started_creates_a_running_step(
    unauth_client: AsyncClient,
    session: AsyncSession,
    parents: Parents,
    actions_token: str,
    parent: str,
) -> None:
    returned = await _start(unauth_client, actions_token, parents, parent)

    row = await _stored_step(session, returned["id"])
    parent_id = getattr(parents, f"{parent}_id")
    assert getattr(row, f"{parent}_id") == parent_id
    assert (row.key, row.name, row.kind) == (
        "hook:upgrade:core",
        "Run the upgrade",
        StepKind.HOOK,
    )
    assert row.status is StepStatus.RUNNING
    assert row.attempt_count == 1
    assert _utc(row.started_at) == STARTED_AT
    assert returned[f"{parent}Id"] == str(parent_id)
    assert returned["status"] == "RUNNING"
    assert returned["kind"] == "HOOK"
    assert datetime.fromisoformat(returned["startedAt"]) == STARTED_AT


@pytest.mark.asyncio
@pytest.mark.parametrize("parent", PARENTS)
async def test_succeeded_ends_the_step(
    unauth_client: AsyncClient,
    session: AsyncSession,
    parents: Parents,
    actions_token: str,
    parent: str,
) -> None:
    started = await _start(unauth_client, actions_token, parents, parent)

    returned = await _record(
        unauth_client,
        actions_token,
        stepId=started["id"],
        event="SUCCEEDED",
        occurredAt=_at(30),
    )

    row = await _stored_step(session, started["id"])
    assert row.status is StepStatus.SUCCEEDED
    assert _utc(row.ended_at) == STARTED_AT + timedelta(seconds=30)
    assert returned["status"] == "SUCCEEDED"
    assert datetime.fromisoformat(returned["endedAt"]) == STARTED_AT + timedelta(
        seconds=30
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("parent", PARENTS)
async def test_failed_stores_the_error_and_output(
    unauth_client: AsyncClient,
    session: AsyncSession,
    parents: Parents,
    actions_token: str,
    parent: str,
) -> None:
    started = await _start(unauth_client, actions_token, parents, parent)

    returned = await _record(
        unauth_client,
        actions_token,
        **parents.variables(parent),
        key="hook:upgrade:core",
        event="FAILED",
        error="RuntimeError: migration failed",
        output="step-output-1\nstep-output-2\n",
        outputTruncated=True,
        occurredAt=_at(45),
    )

    row = await _stored_step(session, started["id"])
    assert row.status is StepStatus.FAILED
    assert _utc(row.ended_at) == STARTED_AT + timedelta(seconds=45)
    assert row.errors == [
        {
            "attempt": 1,
            "message": "RuntimeError: migration failed",
            "occurred_at": _at(45).replace("+00:00", "Z"),
        }
    ]
    assert row.output == "step-output-1\nstep-output-2\n"
    assert row.output_truncated is True
    assert returned["id"] == started["id"]
    assert returned["status"] == "FAILED"
    assert returned["errors"][0]["message"] == "RuntimeError: migration failed"
    assert returned["output"] == "step-output-1\nstep-output-2\n"
    assert returned["outputTruncated"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("parent", PARENTS)
async def test_output_is_stored_on_a_running_step(
    unauth_client: AsyncClient,
    session: AsyncSession,
    parents: Parents,
    actions_token: str,
    parent: str,
) -> None:
    started = await _start(unauth_client, actions_token, parents, parent)

    returned = await _record(
        unauth_client,
        actions_token,
        stepId=started["id"],
        event="OUTPUT",
        output="line 1\nline 2\n",
        occurredAt=_at(10),
    )

    row = await _stored_step(session, started["id"])
    assert row.status is StepStatus.RUNNING
    assert row.output == "line 1\nline 2\n"
    assert row.output_truncated is False
    assert returned["output"] == "line 1\nline 2\n"
    assert returned["outputTruncated"] is False


# recordStep: every caller other than styrmin-actions is rejected.


@pytest.mark.asyncio
async def test_record_step_without_token_is_unauthenticated(
    unauth_client: AsyncClient, session: AsyncSession, parents: Parents
) -> None:
    payload = await _post(
        unauth_client,
        "record_step",
        {
            "input": {
                **parents.variables("task"),
                "key": "plan",
                "name": "Plan the changes",
                "kind": "PLAN",
                "event": "STARTED",
            }
        },
        token=None,
    )

    assert payload["errors"][0]["extensions"]["code"] == "UNAUTHENTICATED"
    assert await _stored_steps(session) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", [Role.READ_ONLY, Role.READ_WRITE, Role.ADMIN], ids=lambda role: role.name
)
async def test_record_step_by_a_person_is_forbidden(
    unauth_client: AsyncClient, session: AsyncSession, parents: Parents, role: Role
) -> None:
    token = await _token_for(session, role)

    payload = await _post(
        unauth_client,
        "record_step",
        {
            "input": {
                **parents.variables("task"),
                "key": "plan",
                "name": "Plan the changes",
                "kind": "PLAN",
                "event": "STARTED",
            }
        },
        token=token,
    )

    assert payload["errors"][0]["extensions"]["code"] == "FORBIDDEN"
    assert await _stored_steps(session) == []


# Query.step: a seeded row reaches a READ_ONLY caller.


@pytest.mark.asyncio
async def test_query_step_returns_every_field_to_read_only(
    unauth_client: AsyncClient, session: AsyncSession, parents: Parents
) -> None:
    task = await session.get(TaskRow, parents.task_id)
    assert task is not None
    superseding = await seed_task(session, task_type=TaskType.UPDATE_INSTANCE)
    step = StepRow(
        task_id=parents.task_id,
        key="operator:helmrelease",
        name="Install the Helm release",
        kind=StepKind.OPERATOR_PHASE,
        status=StepStatus.SUPERSEDED,
        started_at=STARTED_AT,
        ended_at=STARTED_AT + timedelta(seconds=90),
        attempt_count=2,
        errors=[
            {"attempt": 1, "message": "first failure", "occurred_at": _at(20)},
            {"attempt": 2, "message": "second failure", "occurred_at": _at(80)},
        ],
        detail="InstallFailed: image pull failed",
        rolled_back_at=STARTED_AT + timedelta(seconds=85),
        rollback_message="Helm rollback to previous release succeeded",
        output="tail of the output\n",
        output_truncated=True,
        superseded_by_task_id=superseding.id,
    )
    session.add(step)
    await session.commit()
    started = TaskRow(
        type=TaskType.STOP_COMPONENTS,
        status=task.status,
        deployment_id=task.deployment_id,
        started_by_step_id=step.id,
    )
    session.add(started)
    await session.commit()
    token = await _token_for(session, Role.READ_ONLY)

    payload = await _post(unauth_client, "get_step", {"stepId": str(step.id)}, token)

    assert "errors" not in payload, payload
    data = payload["data"]["step"]
    for field in ("startedAt", "endedAt", "rolledBackAt"):
        data[field] = datetime.fromisoformat(data[field])
    for error in data["errors"]:
        error["occurredAt"] = datetime.fromisoformat(error["occurredAt"])
    assert data == {
        "id": str(step.id),
        "key": "operator:helmrelease",
        "name": "Install the Helm release",
        "kind": "OPERATOR_PHASE",
        "status": "SUPERSEDED",
        "startedAt": STARTED_AT,
        "endedAt": STARTED_AT + timedelta(seconds=90),
        "durationSeconds": 90.0,
        "attemptCount": 2,
        "errors": [
            {
                "attempt": 1,
                "message": "first failure",
                "occurredAt": STARTED_AT + timedelta(seconds=20),
            },
            {
                "attempt": 2,
                "message": "second failure",
                "occurredAt": STARTED_AT + timedelta(seconds=80),
            },
        ],
        "error": "second failure",
        "detail": "InstallFailed: image pull failed",
        "rolledBackAt": STARTED_AT + timedelta(seconds=85),
        "rollbackMessage": "Helm rollback to previous release succeeded",
        "hasOutput": True,
        "output": "tail of the output\n",
        "outputTruncated": True,
        "supersededBy": {"id": str(superseding.id)},
        "startedTasks": [{"id": str(started.id)}],
        "noReportSince": None,
        "taskId": str(parents.task_id),
        "backupId": None,
        "restoreId": None,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("parent", ["backup", "restore"])
async def test_query_step_returns_the_backup_or_restore_parent(
    unauth_client: AsyncClient, session: AsyncSession, parents: Parents, parent: str
) -> None:
    parent_id = getattr(parents, f"{parent}_id")
    step = StepRow(
        key=f"{parent}:velero",
        name="Run Velero",
        kind=StepKind.RESTORE if parent == "restore" else StepKind.BACKUP_COMPONENT,
        status=StepStatus.PENDING,
        **{f"{parent}_id": parent_id},
    )
    session.add(step)
    await session.commit()
    token = await _token_for(session, Role.READ_ONLY)

    payload = await _post(unauth_client, "get_step", {"stepId": str(step.id)}, token)

    assert "errors" not in payload, payload
    data = payload["data"]["step"]
    assert data[f"{parent}Id"] == str(parent_id)
    assert data["taskId"] is None
    assert data["status"] == "PENDING"
    assert data["startedAt"] is None
    assert data["durationSeconds"] is None
    assert data["errors"] == []
    assert data["error"] is None
    assert data["hasOutput"] is False
    assert data["outputTruncated"] is False
    assert data["supersededBy"] is None
    assert data["startedTasks"] == []


# The flow step reporter's own operation and variables are accepted end to end.


@pytest.mark.asyncio
async def test_flow_step_reporter_records_through_the_api(
    unauth_client: AsyncClient,
    session: AsyncSession,
    parents: Parents,
    actions_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        reporter_module,
        "httpx",
        SimpleNamespace(
            AsyncClient=lambda **kwargs: real_client(
                transport=ASGITransport(app=app), **kwargs
            )
        ),
    )
    monkeypatch.setattr(config.SETTINGS.url, "api", "http://test")
    monkeypatch.setenv(API_TOKEN_ENV, actions_token)
    monkeypatch.setenv(TASK_ID_ENV, str(parents.task_id))
    reporter = StepReporter.from_env()

    async with reporter.step("plan", "Plan the changes", StepKind.PLAN) as planned:
        pass
    with pytest.raises(RuntimeError, match="hook exploded"):
        async with reporter.step(
            "hook:upgrade:core", "Run the upgrade", StepKind.HOOK
        ) as hook:
            await reporter.record_output(hook.id, "last line\n", truncated=False)
            raise RuntimeError("hook exploded")

    rows = {row.key: row for row in await _stored_steps(session)}
    assert str(rows["plan"].id) == str(planned.id)
    assert rows["plan"].status is StepStatus.SUCCEEDED
    assert rows["plan"].task_id == parents.task_id
    assert str(rows["hook:upgrade:core"].id) == str(hook.id)
    assert rows["hook:upgrade:core"].status is StepStatus.FAILED
    assert rows["hook:upgrade:core"].output == "last line\n"
    assert rows["hook:upgrade:core"].errors is not None
    assert rows["hook:upgrade:core"].errors[0]["message"] == (
        "RuntimeError: hook exploded"
    )
