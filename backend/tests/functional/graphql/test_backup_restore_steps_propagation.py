"""``Backup.steps`` and ``Restore.steps`` reach the caller (spec 019, T097).

Seeded steps reach a ``READ_ONLY`` user through the single reads
(``Query.backup``, ``Query.restore``: query fallback) and the lists
(``Query.backups``, ``Query.restores``: one query for the steps of every
listed row). Deleting a backup deletes its steps and the steps of its restores.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    ApplicationInstance,
    Backup,
    BackupStatus,
    Restore,
    RestoreStatus,
    Role,
    Step as StepRow,
    StepKind,
    StepStatus,
)
from styrmin_backend.db.utils import get_session
from styrmin_backend.server.app import app
from styrmin_backend.services.auth.session import create_session

from ._queries import load_query
from .conftest import gql
from .seeds import seed_application_instance, seed_user

T0 = datetime(2026, 10, 6, 10, 0, tzinfo=UTC)


def _at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


async def _token(session: AsyncSession, role: Role) -> str:
    user = await seed_user(session, role=role)
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


def _parse_times(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for step in steps:
        for field in ("startedAt", "endedAt", "rolledBackAt", "noReportSince"):
            if step[field] is not None:
                step[field] = datetime.fromisoformat(step[field])
        for error in step["errors"]:
            error["occurredAt"] = datetime.fromisoformat(error["occurredAt"])
    return steps


def _step_fields(step: StepRow) -> dict[str, Any]:
    """The payload the API returns for a seeded backup or restore step."""
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
        "detail": None,
        "rolledBackAt": None,
        "rollbackMessage": None,
        "hasOutput": False,
        "output": None,
        "outputTruncated": False,
        # Task links and agent reports do not apply to backup or restore steps.
        "supersededBy": None,
        "startedTasks": [],
        "noReportSince": None,
        "taskId": None,
        "backupId": str(step.backup_id) if step.backup_id else None,
        "restoreId": str(step.restore_id) if step.restore_id else None,
    }


def _backup_steps(backup_id: UUID) -> list[StepRow]:
    """Two component steps, the second to start failed; returned in start order."""
    database = StepRow(
        backup_id=backup_id,
        key="backup:component:db",
        name="Back up db",
        kind=StepKind.BACKUP_COMPONENT,
        status=StepStatus.SUCCEEDED,
        started_at=_at(10),
        ended_at=_at(40),
        attempt_count=1,
    )
    web = StepRow(
        backup_id=backup_id,
        key="backup:component:web",
        name="Back up web",
        kind=StepKind.BACKUP_COMPONENT,
        status=StepStatus.FAILED,
        started_at=_at(5),
        ended_at=_at(65),
        attempt_count=1,
        errors=[
            {
                "attempt": 1,
                "message": "pod volume backup web-data failed: disk full",
                "occurred_at": _at(65).isoformat(),
            }
        ],
    )
    return [web, database]


def _restore_steps(restore_id: UUID) -> list[StepRow]:
    """The three restore steps; the Velero restore failed, the recovery never ran."""
    namespace = StepRow(
        restore_id=restore_id,
        key="restore:namespace",
        name="Delete the namespace",
        kind=StepKind.RESTORE,
        status=StepStatus.SUCCEEDED,
        started_at=_at(0),
        ended_at=_at(12),
        attempt_count=1,
    )
    velero = StepRow(
        restore_id=restore_id,
        key="restore:velero",
        name="Run the Velero restore",
        kind=StepKind.RESTORE,
        status=StepStatus.FAILED,
        started_at=_at(12),
        ended_at=_at(20),
        attempt_count=1,
        errors=[
            {
                "attempt": 1,
                "message": "Velero restore FailedValidation: backup not found",
                "occurred_at": _at(20).isoformat(),
            }
        ],
    )
    recovery = StepRow(
        restore_id=restore_id,
        key="restore:recovery",
        name="Run the recovery",
        kind=StepKind.RESTORE,
        status=StepStatus.PENDING,
    )
    return [namespace, velero, recovery]


@dataclass(frozen=True)
class SeededBackups:
    instance_id: UUID
    backup_id: UUID
    #: A backup taken before steps were recorded.
    stepless_backup_id: UUID
    restore_id: UUID
    stepless_restore_id: UUID
    backup_steps: list[dict[str, Any]]
    restore_steps: list[dict[str, Any]]


async def _seed_backup(
    session: AsyncSession, instance: ApplicationInstance, name: str
) -> Backup:
    backup = Backup(name=name, status=BackupStatus.COMPLETED, instance_id=instance.id)
    session.add(backup)
    await session.commit()
    return backup


async def _seed_restore(session: AsyncSession, backup: Backup, name: str) -> Restore:
    restore = Restore(
        name=name,
        status=RestoreStatus.FAILED,
        target_namespace="styrmin-steps",
        backup_id=backup.id,
    )
    session.add(restore)
    await session.commit()
    return restore


async def _seed(session: AsyncSession) -> SeededBackups:
    instance = await seed_application_instance(session)
    backup = await _seed_backup(session, instance, "with-steps")
    stepless_backup = await _seed_backup(session, instance, "before-steps")
    restore = await _seed_restore(session, backup, "with-steps")
    stepless_restore = await _seed_restore(session, backup, "before-steps")
    backup_steps = _backup_steps(backup.id)
    restore_steps = _restore_steps(restore.id)
    # Inserted out of start order: the API orders by start, pending steps last.
    session.add_all([*reversed(backup_steps), *reversed(restore_steps)])
    await session.commit()
    return SeededBackups(
        instance_id=instance.id,
        backup_id=backup.id,
        stepless_backup_id=stepless_backup.id,
        restore_id=restore.id,
        stepless_restore_id=stepless_restore.id,
        backup_steps=[_step_fields(step) for step in backup_steps],
        restore_steps=[_step_fields(step) for step in restore_steps],
    )


@pytest.fixture
async def seeded(session: AsyncSession) -> SeededBackups:
    return await _seed(session)


# Backup.steps and Restore.steps: seeded rows reach a READ_ONLY caller.


@pytest.mark.asyncio
async def test_backup_steps_reach_read_only_through_backup(
    unauth_client: AsyncClient, session: AsyncSession, seeded: SeededBackups
) -> None:
    token = await _token(session, Role.READ_ONLY)

    data = await _read(
        unauth_client, "get_backup_steps", {"backupId": str(seeded.backup_id)}, token
    )

    assert _parse_times(data["backup"]["steps"]) == seeded.backup_steps


@pytest.mark.asyncio
async def test_backup_steps_reach_read_only_through_backups(
    unauth_client: AsyncClient, session: AsyncSession, seeded: SeededBackups
) -> None:
    token = await _token(session, Role.READ_ONLY)

    data = await _read(
        unauth_client,
        "list_backup_steps",
        {"instanceId": str(seeded.instance_id)},
        token,
    )

    steps = {backup["id"]: _parse_times(backup["steps"]) for backup in data["backups"]}
    assert steps == {
        str(seeded.backup_id): seeded.backup_steps,
        str(seeded.stepless_backup_id): [],
    }


@pytest.mark.asyncio
async def test_restore_steps_reach_read_only_through_restore(
    unauth_client: AsyncClient, session: AsyncSession, seeded: SeededBackups
) -> None:
    token = await _token(session, Role.READ_ONLY)

    data = await _read(
        unauth_client,
        "get_restore_steps",
        {"restoreId": str(seeded.restore_id)},
        token,
    )

    assert _parse_times(data["restore"]["steps"]) == seeded.restore_steps


@pytest.mark.asyncio
async def test_restore_steps_reach_read_only_through_restores(
    unauth_client: AsyncClient, session: AsyncSession, seeded: SeededBackups
) -> None:
    token = await _token(session, Role.READ_ONLY)

    data = await _read(
        unauth_client, "list_restore_steps", {"backupId": str(seeded.backup_id)}, token
    )

    steps = {
        restore["id"]: _parse_times(restore["steps"]) for restore in data["restores"]
    }
    assert steps == {
        str(seeded.restore_id): seeded.restore_steps,
        str(seeded.stepless_restore_id): [],
    }


# The lists read the steps of all their rows with one query.


@contextmanager
def _count_selects(session: AsyncSession) -> Iterator[list[str]]:
    statements: list[str] = []
    engine = session.bind.sync_engine  # type: ignore[union-attr]

    def _record(
        conn: Any,  # noqa: ARG001
        cursor: Any,  # noqa: ARG001
        statement: str,
        parameters: Any,  # noqa: ARG001
        context: Any,  # noqa: ARG001
        executemany: bool,  # noqa: ARG001
    ) -> None:
        if statement.lstrip().lower().startswith("select"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _record)


async def _seed_many(session: AsyncSession, backups: int) -> tuple[UUID, UUID]:
    """An instance with ``backups`` backups; the first has ``backups`` restores.

    Every backup and restore has steps. Returns the instance and the first backup.
    """
    instance = await seed_application_instance(session)
    rows = [
        await _seed_backup(session, instance, f"backup-{instance.id}-{index}")
        for index in range(backups)
    ]
    restores = [
        await _seed_restore(session, rows[0], f"restore-{instance.id}-{index}")
        for index in range(backups)
    ]
    for backup in rows:
        session.add_all(_backup_steps(backup.id))
    for restore in restores:
        session.add_all(_restore_steps(restore.id))
    await session.commit()
    return instance.id, rows[0].id


async def _list_queries(
    client: AsyncClient,
    session: AsyncSession,
    token: str,
    instance_id: UUID,
    backup_id: UUID,
) -> tuple[list[str], list[str]]:
    with _count_selects(session) as backup_queries:
        backups = await _read(
            client, "list_backup_steps", {"instanceId": str(instance_id)}, token
        )
    with _count_selects(session) as restore_queries:
        restores = await _read(
            client, "list_restore_steps", {"backupId": str(backup_id)}, token
        )
    assert all(len(backup["steps"]) == 2 for backup in backups["backups"])
    assert all(len(restore["steps"]) == 3 for restore in restores["restores"])
    return backup_queries, restore_queries


@pytest.mark.asyncio
async def test_lists_read_steps_with_a_fixed_number_of_queries(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    token = await _token(session, Role.READ_ONLY)
    one = await _seed_many(session, backups=1)
    ten = await _seed_many(session, backups=10)

    one_backup, one_restore = await _list_queries(unauth_client, session, token, *one)
    ten_backups, ten_restores = await _list_queries(unauth_client, session, token, *ten)

    assert len(ten_backups) == len(one_backup), ten_backups
    assert len(ten_restores) == len(one_restore), ten_restores


# Steps are deleted with their backup (PostgreSQL enforces the foreign keys).


@pytest.fixture
async def postgres_session(
    postgres_url: str,
) -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(postgres_url)
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def postgres_client(
    postgres_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
    async def get_session_override() -> AsyncGenerator[AsyncSession, None]:
        yield postgres_session

    app.dependency_overrides[get_session] = get_session_override
    token = await _token(postgres_session, Role.READ_WRITE)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_steps_are_deleted_with_their_backup(
    postgres_client: AsyncClient, postgres_session: AsyncSession
) -> None:
    session = postgres_session
    seeded = await _seed(session)
    kept = await _seed_backup(
        session,
        await seed_application_instance(session),
        "kept",
    )
    session.add_all(_backup_steps(kept.id))
    await session.commit()

    await gql(postgres_client, "delete_backup", {"backupId": str(seeded.backup_id)})

    remaining = (
        await session.exec(select(StepRow.backup_id, StepRow.restore_id))
    ).all()
    # The deleted backup's steps and its restores' steps are gone; others stay.
    assert sorted(remaining) == [(kept.id, None), (kept.id, None)]
