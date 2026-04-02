"""Unit tests for BackupResource and ScheduleResource."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from styrmin_sdk.exceptions import OperationFailedError, ResourceNotFoundError

if TYPE_CHECKING:
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
                    "createdOn": "2026-01-01T00:00:00",
                    "updatedOn": None,
                }
            }
        }

        backup = await client.backups.create_backup(instance_id="00000000-0000-0000-0000-000000000010")
        assert backup.name == "test-backup"
        assert backup.status == "pending"

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
                    "createdOn": "2026-01-01T00:00:00",
                    "updatedOn": "2026-01-01T00:05:00",
                }
            }
        }

        backup = await client.backups.get_backup("00000000-0000-0000-0000-000000000001")
        assert backup.status == "completed"
        assert backup.size_bytes == 1024

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
                        "createdOn": "2026-01-01T00:00:00",
                        "updatedOn": None,
                    },
                ]
            }
        }

        backups = await client.backups.list_backups(instance_id="00000000-0000-0000-0000-000000000010")
        assert len(backups) == 1
        assert backups[0].name == "backup-1"

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
                }
            }
        }

        restore = await client.backups.get_restore("00000000-0000-0000-0000-000000000020")
        assert restore.status == "completed"


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
