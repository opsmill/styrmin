"""Unit tests for BackupResource and ScheduleResource."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from styrmin_sdk.exceptions import OperationFailedError, ResourceNotFoundError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from styrmin_sdk.client import StyrminClient


class TestBackupResource:
    @staticmethod
    @pytest.mark.asyncio
    async def test_create_backup(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": {
                "createBackup": {
                    "id": "00000000-0000-0000-0000-000000000001",
                    "name": "test-backup",
                    "status": "pending",
                    "instanceId": "00000000-0000-0000-0000-000000000010",
                    "errorMessage": None,
                    "startedAt": None,
                    "completedAt": None,
                    "sizeBytes": None,
                    "ttl": None,
                    "expiresAt": None,
                    "createdOn": "2026-01-01T00:00:00",
                    "updatedOn": None,
                }
            }
        }

        backup = await client.backups.create_backup(instance_id="00000000-0000-0000-0000-000000000010")
        assert backup.name == "test-backup"
        assert backup.status == "pending"
        # A just-created backup has no retention recorded yet: the workflow
        # resolves the TTL and Velero reports the expiration only once it runs.
        assert backup.ttl is None
        assert backup.expires_at is None

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_backup_already_in_progress(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": {"createBackup": None},
            "errors": [
                {
                    "message": "A backup is already in progress",
                    "extensions": {
                        "code": "ALREADY_IN_PROGRESS",
                        "existing_backup_id": "00000000-0000-0000-0000-000000000002",
                    },
                }
            ],
        }

        with pytest.raises(OperationFailedError):
            await client.backups.create_backup(instance_id="00000000-0000-0000-0000-000000000010")

    @staticmethod
    @pytest.mark.asyncio
    async def test_get_backup(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": {
                "backup": {
                    "id": "00000000-0000-0000-0000-000000000001",
                    "name": "test-backup",
                    "status": "completed",
                    "instanceId": "00000000-0000-0000-0000-000000000010",
                    "errorMessage": None,
                    "startedAt": "2026-01-01T00:00:00",
                    "completedAt": "2026-01-01T00:05:00",
                    "sizeBytes": 1024,
                    "ttl": "2160h",
                    "expiresAt": "2026-04-01T00:00:00",
                    "createdOn": "2026-01-01T00:00:00",
                    "updatedOn": "2026-01-01T00:05:00",
                    "steps": [],
                }
            }
        }

        backup = await client.backups.get_backup("00000000-0000-0000-0000-000000000001")
        assert backup.status == "completed"
        assert backup.size_bytes == 1024
        assert backup.ttl == "2160h"
        assert backup.expires_at is not None
        assert backup.expires_at.isoformat() == "2026-04-01T00:00:00"

    @staticmethod
    @pytest.mark.asyncio
    async def test_get_backup_not_found(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": {"backup": None},
            "errors": [{"message": "Backup not found", "extensions": {"code": "NOT_FOUND"}}],
        }

        with pytest.raises(ResourceNotFoundError):
            await client.backups.get_backup("00000000-0000-0000-0000-000000000001")

    @staticmethod
    @pytest.mark.asyncio
    async def test_list_backups(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": {
                "backups": [
                    {
                        "id": "00000000-0000-0000-0000-000000000001",
                        "name": "backup-1",
                        "status": "completed",
                        "instanceId": "00000000-0000-0000-0000-000000000010",
                        "errorMessage": None,
                        "startedAt": None,
                        "completedAt": None,
                        "sizeBytes": None,
                        "ttl": "2160h",
                        "expiresAt": "2026-04-01T00:00:00",
                        "createdOn": "2026-01-01T00:00:00",
                        "updatedOn": None,
                        "steps": [],
                    },
                    {
                        "id": "00000000-0000-0000-0000-000000000002",
                        "name": "backup-2",
                        "status": "failed",
                        "instanceId": "00000000-0000-0000-0000-000000000010",
                        "errorMessage": "velero reported Failed",
                        "startedAt": None,
                        "completedAt": None,
                        "sizeBytes": None,
                        "ttl": "2160h",
                        "expiresAt": None,
                        "createdOn": "2026-01-01T00:00:00",
                        "updatedOn": None,
                        "steps": [],
                    },
                ]
            }
        }

        backups = await client.backups.list_backups(instance_id="00000000-0000-0000-0000-000000000010")
        assert len(backups) == 2
        assert backups[0].name == "backup-1"
        # A list mixes both retention shapes — the CLI and web UI render the
        # second as "—" while still reporting the TTL that was applied.
        assert backups[0].expires_at is not None
        assert backups[1].ttl == "2160h"
        assert backups[1].expires_at is None

    @staticmethod
    @pytest.mark.asyncio
    async def test_delete_backup(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {"data": {"deleteBackup": "Backup deleted"}}

        await client.backups.delete_backup("00000000-0000-0000-0000-000000000001")

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_restore(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": {
                "createRestore": {
                    "id": "00000000-0000-0000-0000-000000000020",
                    "name": "restore-test",
                    "status": "pending",
                    "backupId": "00000000-0000-0000-0000-000000000001",
                    "targetNamespace": "styrmin-ns",
                    "targetInstanceId": None,
                    "errorMessage": None,
                    "startedAt": None,
                    "completedAt": None,
                    "createdOn": "2026-01-01T00:00:00",
                    "updatedOn": None,
                }
            }
        }

        restore = await client.backups.create_restore(
            backup_id="00000000-0000-0000-0000-000000000001",
            target_namespace="styrmin-ns",
        )
        assert restore.status == "pending"
        assert restore.target_namespace == "styrmin-ns"

    @staticmethod
    @pytest.mark.asyncio
    async def test_get_restore(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": {
                "restore": {
                    "id": "00000000-0000-0000-0000-000000000020",
                    "name": "restore-test",
                    "status": "completed",
                    "backupId": "00000000-0000-0000-0000-000000000001",
                    "targetNamespace": "styrmin-ns",
                    "targetInstanceId": None,
                    "errorMessage": None,
                    "startedAt": "2026-01-01T00:00:00",
                    "completedAt": "2026-01-01T00:05:00",
                    "createdOn": "2026-01-01T00:00:00",
                    "updatedOn": "2026-01-01T00:05:00",
                    "steps": [],
                }
            }
        }

        restore = await client.backups.get_restore("00000000-0000-0000-0000-000000000020")
        assert restore.status == "completed"
        # A restore run before steps were recorded has none.
        assert restore.steps == []


BACKUP_ID = "00000000-0000-0000-0000-000000000001"
RESTORE_ID = "00000000-0000-0000-0000-000000000020"


def _step(
    key: str,
    name: str,
    kind: str,
    status: str,
    *,
    started_at: str | None = None,
    ended_at: str | None = None,
    duration_seconds: float | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """A step as the four backup and restore operations return it."""
    errors = [{"attempt": 1, "message": error, "occurredAt": ended_at}] if error else []
    return {
        "id": str(uuid4()),
        "key": key,
        "name": name,
        "kind": kind,
        "status": status,
        "startedAt": started_at,
        "endedAt": ended_at,
        "durationSeconds": duration_seconds,
        "attemptCount": 1 if started_at else 0,
        "errors": errors,
        "error": error,
        "hasOutput": False,
    }


COMPONENT_STEPS = [
    _step(
        "backup:component:db",
        "Back up db",
        "BACKUP_COMPONENT",
        "SUCCEEDED",
        started_at="2026-01-01T00:00:10+00:00",
        ended_at="2026-01-01T00:01:10+00:00",
        duration_seconds=60.0,
    ),
    _step(
        "backup:component:web",
        "Back up web",
        "BACKUP_COMPONENT",
        "FAILED",
        started_at="2026-01-01T00:00:12+00:00",
        ended_at="2026-01-01T00:00:42+00:00",
        duration_seconds=30.0,
        error="pod volume backup web-data failed: disk full",
    ),
]

RESTORE_STEPS = [
    _step(
        "restore:namespace",
        "Delete the namespace",
        "RESTORE",
        "SUCCEEDED",
        started_at="2026-01-01T00:00:00+00:00",
        ended_at="2026-01-01T00:00:12+00:00",
        duration_seconds=12.0,
    ),
    _step(
        "restore:velero",
        "Run the Velero restore",
        "RESTORE",
        "FAILED",
        started_at="2026-01-01T00:00:12+00:00",
        ended_at="2026-01-01T00:00:20+00:00",
        duration_seconds=8.0,
        error="Velero restore FailedValidation: backup not found",
    ),
    _step("restore:recovery", "Run the recovery", "RESTORE", "PENDING"),
]


def _backup(backup_id: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": backup_id,
        "name": f"backup-{backup_id[-1]}",
        "status": "failed",
        "instanceId": "00000000-0000-0000-0000-000000000010",
        "errorMessage": "velero reported PartiallyFailed",
        "startedAt": "2026-01-01T00:00:00+00:00",
        "completedAt": "2026-01-01T00:01:10+00:00",
        "sizeBytes": None,
        "ttl": "2160h",
        "expiresAt": None,
        "createdOn": "2026-01-01T00:00:00+00:00",
        "updatedOn": None,
        "steps": steps,
    }


def _restore(restore_id: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": restore_id,
        "name": f"restore-{restore_id[-1]}",
        "status": "failed",
        "backupId": BACKUP_ID,
        "targetNamespace": "styrmin-ns",
        "targetInstanceId": None,
        "errorMessage": "Velero restore failed",
        "startedAt": "2026-01-01T00:00:00+00:00",
        "completedAt": "2026-01-01T00:00:20+00:00",
        "createdOn": "2026-01-01T00:00:00+00:00",
        "updatedOn": None,
        "steps": steps,
    }


def _assert_steps(parsed: Sequence[Any], expected: list[dict[str, Any]]) -> None:
    """Each parsed step carries the payload's values, in the payload's order."""
    assert [step.key for step in parsed] == [step["key"] for step in expected]
    for step, payload in zip(parsed, expected, strict=True):
        assert str(step.id) == payload["id"]
        assert step.name == payload["name"]
        assert step.kind.value == payload["kind"]
        assert step.status.value == payload["status"]
        assert (step.started_at.isoformat() if step.started_at else None) == payload["startedAt"]
        assert (step.ended_at.isoformat() if step.ended_at else None) == payload["endedAt"]
        assert step.duration_seconds == payload["durationSeconds"]
        assert step.attempt_count == payload["attemptCount"]
        assert step.error == payload["error"]
        assert [(e.attempt, e.message) for e in step.errors] == [
            (e["attempt"], e["message"]) for e in payload["errors"]
        ]
        assert step.has_output is False


class TestBackupAndRestoreSteps:
    @staticmethod
    @pytest.mark.asyncio
    async def test_get_backup_parses_component_steps(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {"data": {"backup": _backup(BACKUP_ID, COMPONENT_STEPS)}}

        backup = await client.backups.get_backup(BACKUP_ID)

        _assert_steps(backup.steps, COMPONENT_STEPS)
        assert backup.steps[1].error == "pod volume backup web-data failed: disk full"

    @staticmethod
    @pytest.mark.asyncio
    async def test_list_backups_parses_the_steps_of_each_backup(
        client: StyrminClient, mock_transport: AsyncMock
    ) -> None:
        other_id = "00000000-0000-0000-0000-000000000002"
        mock_transport.execute.return_value = {
            "data": {"backups": [_backup(BACKUP_ID, COMPONENT_STEPS), _backup(other_id, [])]}
        }

        backups = await client.backups.list_backups(instance_id="00000000-0000-0000-0000-000000000010")

        _assert_steps(backups[0].steps, COMPONENT_STEPS)
        # A backup taken before steps were recorded has none.
        assert backups[1].steps == []

    @staticmethod
    @pytest.mark.asyncio
    async def test_get_restore_parses_the_three_restore_steps(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {"data": {"restore": _restore(RESTORE_ID, RESTORE_STEPS)}}

        restore = await client.backups.get_restore(RESTORE_ID)

        _assert_steps(restore.steps, RESTORE_STEPS)
        failed = [step for step in restore.steps if step.status.value == "FAILED"]
        assert [(step.name, step.error) for step in failed] == [
            ("Run the Velero restore", "Velero restore FailedValidation: backup not found")
        ]
        assert restore.steps[2].started_at is None
        assert restore.steps[2].duration_seconds is None

    @staticmethod
    @pytest.mark.asyncio
    async def test_list_restores_parses_the_steps_of_each_restore(
        client: StyrminClient, mock_transport: AsyncMock
    ) -> None:
        other_id = "00000000-0000-0000-0000-000000000021"
        mock_transport.execute.return_value = {
            "data": {"restores": [_restore(RESTORE_ID, RESTORE_STEPS), _restore(other_id, [])]}
        }

        restores = await client.backups.list_restores(backup_id=BACKUP_ID)

        _assert_steps(restores[0].steps, RESTORE_STEPS)
        assert restores[1].steps == []


class TestScheduleResource:
    @staticmethod
    @pytest.mark.asyncio
    async def test_create_schedule(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": {
                "createBackupSchedule": {
                    "id": "00000000-0000-0000-0000-000000000030",
                    "name": "daily-backup",
                    "enabled": True,
                    "cronExpression": "0 2 * * *",
                    "retentionCount": 10,
                    "deploymentId": "00000000-0000-0000-0000-000000000100",
                    "lastBackupAt": None,
                    "nextBackupAt": None,
                    "prefectDeploymentId": None,
                    "createdOn": "2026-01-01T00:00:00",
                    "updatedOn": None,
                }
            }
        }

        schedule = await client.schedules.create(
            deployment_id="00000000-0000-0000-0000-000000000100",
            name="daily-backup",
            cron_expression="0 2 * * *",
        )
        assert schedule.name == "daily-backup"
        assert schedule.cron_expression == "0 2 * * *"

    @staticmethod
    @pytest.mark.asyncio
    async def test_get_schedule(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": {
                "backupSchedule": {
                    "id": "00000000-0000-0000-0000-000000000030",
                    "name": "daily-backup",
                    "enabled": True,
                    "cronExpression": "0 2 * * *",
                    "retentionCount": 10,
                    "deploymentId": "00000000-0000-0000-0000-000000000100",
                    "lastBackupAt": None,
                    "nextBackupAt": None,
                    "prefectDeploymentId": None,
                    "createdOn": "2026-01-01T00:00:00",
                    "updatedOn": None,
                }
            }
        }

        schedule = await client.schedules.get("00000000-0000-0000-0000-000000000030")
        assert schedule.name == "daily-backup"

    @staticmethod
    @pytest.mark.asyncio
    async def test_delete_schedule(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {"data": {"deleteBackupSchedule": "Backup schedule deleted"}}

        await client.schedules.delete("00000000-0000-0000-0000-000000000030")

    @staticmethod
    @pytest.mark.asyncio
    async def test_update_schedule(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": {
                "updateBackupSchedule": {
                    "id": "00000000-0000-0000-0000-000000000030",
                    "name": "daily-backup",
                    "enabled": True,
                    "cronExpression": "0 3 * * *",
                    "retentionCount": 7,
                    "deploymentId": "00000000-0000-0000-0000-000000000100",
                    "lastBackupAt": None,
                    "nextBackupAt": None,
                    "prefectDeploymentId": None,
                    "createdOn": "2026-01-01T00:00:00",
                    "updatedOn": "2026-01-01T01:00:00",
                }
            }
        }

        schedule = await client.schedules.update(
            schedule_id="00000000-0000-0000-0000-000000000030",
            cron_expression="0 3 * * *",
            retention_count=7,
        )
        assert schedule.cron_expression == "0 3 * * *"
        assert schedule.retention_count == 7

    @staticmethod
    @pytest.mark.asyncio
    async def test_list_schedules(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": {
                "backupSchedules": [
                    {
                        "id": "00000000-0000-0000-0000-000000000030",
                        "name": "daily-backup",
                        "enabled": True,
                        "cronExpression": "0 2 * * *",
                        "retentionCount": 10,
                        "deploymentId": "00000000-0000-0000-0000-000000000100",
                        "lastBackupAt": None,
                        "nextBackupAt": None,
                        "prefectDeploymentId": None,
                        "createdOn": "2026-01-01T00:00:00",
                        "updatedOn": None,
                    },
                ]
            }
        }

        schedules = await client.schedules.list(deployment_id="00000000-0000-0000-0000-000000000100")
        assert len(schedules) == 1
        assert schedules[0].name == "daily-backup"
