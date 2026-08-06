"""Unit tests for EnvironmentBackupResource."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest
from styrmin_sdk import EnvironmentBackupStatus
from styrmin_sdk.exceptions import OperationFailedError, ResourceNotFoundError

if TYPE_CHECKING:
    from styrmin_sdk.client import StyrminClient

ENV_BACKUP_ID = "00000000-0000-0000-0000-0000000000e1"
ENVIRONMENT_ID = "00000000-0000-0000-0000-0000000000e0"
DEPLOYMENT_ID = "00000000-0000-0000-0000-000000000100"
INSTANCE_ID = "00000000-0000-0000-0000-000000000010"
BACKUP_ID = "00000000-0000-0000-0000-000000000001"


def _snapshot() -> dict[str, Any]:
    return {
        "deploymentId": DEPLOYMENT_ID,
        "deploymentName": "demo",
        "instanceId": INSTANCE_ID,
        "driverName": "semaphore",
        "driverVersion": "1.0.0",
        "driverFingerprint": "sha256:abc",
        "applicationVersion": "2.9.0",
        "config": {"replicas": 1},
        "parameters": None,
    }


def _constituent(*, error: str | None = None, with_backup: bool = True) -> dict[str, Any]:
    backup = (
        {
            "id": BACKUP_ID,
            "name": "demo-backup",
            "status": "pending",
            "instanceId": INSTANCE_ID,
            "errorMessage": None,
            "sizeBytes": None,
            "startedAt": None,
            "completedAt": None,
        }
        if with_backup
        else None
    )
    return {
        "deploymentId": DEPLOYMENT_ID,
        "deploymentName": "demo",
        "error": error,
        "backup": backup,
    }


def _environment_backup(
    *,
    status: str = "PENDING",
    constituents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": ENV_BACKUP_ID,
        "name": "env-backup-1",
        "status": status,
        "createdOn": "2026-01-01T00:00:00",
        "updatedOn": None,
        "environmentId": ENVIRONMENT_ID,
        "environmentConfig": {"backupStorageLocationId": None},
        "deploymentSnapshots": [_snapshot()],
        "constituents": constituents if constituents is not None else [_constituent()],
    }


class TestEnvironmentBackupResource:
    @staticmethod
    @pytest.mark.asyncio
    async def test_create(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {"data": {"createEnvironmentBackup": _environment_backup()}}

        environment_backup = await client.environment_backups.create(environment_id=ENVIRONMENT_ID, name="env-backup-1")

        assert environment_backup.name == "env-backup-1"
        assert environment_backup.status is EnvironmentBackupStatus.PENDING
        assert environment_backup.deployment_snapshots[0].driver_fingerprint == "sha256:abc"
        assert environment_backup.constituents[0].backup is not None
        _, variables = mock_transport.execute.call_args.args
        assert variables == {"environmentId": ENVIRONMENT_ID, "name": "env-backup-1"}

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_omits_name_when_not_given(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {"data": {"createEnvironmentBackup": _environment_backup()}}

        await client.environment_backups.create(environment_id=ENVIRONMENT_ID)

        _, variables = mock_transport.execute.call_args.args
        assert variables == {"environmentId": ENVIRONMENT_ID}

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_empty_environment_is_completed(client: StyrminClient, mock_transport: AsyncMock) -> None:
        """An environment with no eligible deployments yields a config-only COMPLETED snapshot."""
        payload = _environment_backup(status="COMPLETED", constituents=[])
        payload["deploymentSnapshots"] = []
        mock_transport.execute.return_value = {"data": {"createEnvironmentBackup": payload}}

        environment_backup = await client.environment_backups.create(environment_id=ENVIRONMENT_ID)

        assert environment_backup.status is EnvironmentBackupStatus.COMPLETED
        assert environment_backup.constituents == []

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_already_in_progress(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": {"createEnvironmentBackup": None},
            "errors": [
                {
                    "message": "An environment backup is already in progress",
                    "extensions": {"code": "ALREADY_IN_PROGRESS"},
                }
            ],
        }

        with pytest.raises(OperationFailedError):
            await client.environment_backups.create(environment_id=ENVIRONMENT_ID)

    @staticmethod
    @pytest.mark.asyncio
    async def test_get(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {"data": {"environmentBackup": _environment_backup(status="PARTIAL")}}

        environment_backup = await client.environment_backups.get(ENV_BACKUP_ID)

        assert environment_backup.status is EnvironmentBackupStatus.PARTIAL
        _, variables = mock_transport.execute.call_args.args
        assert variables == {"environmentBackupId": ENV_BACKUP_ID}

    @staticmethod
    @pytest.mark.asyncio
    async def test_get_not_found(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": {"environmentBackup": None},
            "errors": [{"message": "Environment backup not found", "extensions": {"code": "NOT_FOUND"}}],
        }

        with pytest.raises(ResourceNotFoundError):
            await client.environment_backups.get(ENV_BACKUP_ID)

    @staticmethod
    @pytest.mark.asyncio
    async def test_list_projects_constituent_outcomes(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": {
                "environmentBackups": [
                    {
                        "id": ENV_BACKUP_ID,
                        "name": "env-backup-1",
                        "status": "PARTIAL",
                        "createdOn": "2026-01-01T00:00:00",
                        "updatedOn": None,
                        "environmentId": ENVIRONMENT_ID,
                        "constituents": [
                            {
                                "deploymentId": DEPLOYMENT_ID,
                                "deploymentName": "demo",
                                "error": None,
                                "backup": {
                                    "id": BACKUP_ID,
                                    "name": "demo-backup",
                                    "status": "completed",
                                    "instanceId": INSTANCE_ID,
                                },
                            },
                            {
                                "deploymentId": "00000000-0000-0000-0000-000000000101",
                                "deploymentName": "other",
                                "error": "A backup is already in progress",
                                "backup": None,
                            },
                        ],
                    }
                ]
            }
        }

        environment_backups = await client.environment_backups.list(environment_id=ENVIRONMENT_ID)

        assert len(environment_backups) == 1
        assert environment_backups[0].status is EnvironmentBackupStatus.PARTIAL
        assert environment_backups[0].constituents[1].backup is None
        assert environment_backups[0].constituents[1].error == "A backup is already in progress"

    @staticmethod
    @pytest.mark.asyncio
    async def test_list_empty(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {"data": {"environmentBackups": []}}

        assert await client.environment_backups.list(environment_id=ENVIRONMENT_ID) == []

    @staticmethod
    @pytest.mark.asyncio
    async def test_wait_for_backup_polls_until_terminal(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.side_effect = [
            {"data": {"environmentBackup": _environment_backup(status="IN_PROGRESS")}},
            {"data": {"environmentBackup": _environment_backup(status="COMPLETED")}},
        ]

        environment_backup = await client.environment_backups.wait_for_backup(ENV_BACKUP_ID, max_wait=10, interval=0)

        assert environment_backup.status is EnvironmentBackupStatus.COMPLETED
        assert mock_transport.execute.await_count == 2

    @staticmethod
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["COMPLETED", "PARTIAL", "FAILED"])
    async def test_wait_for_backup_treats_partial_as_terminal(
        client: StyrminClient, mock_transport: AsyncMock, status: str
    ) -> None:
        """PARTIAL is a final outcome — polling must stop, not spin until timeout."""
        mock_transport.execute.return_value = {"data": {"environmentBackup": _environment_backup(status=status)}}

        environment_backup = await client.environment_backups.wait_for_backup(ENV_BACKUP_ID, max_wait=10, interval=0)

        assert environment_backup.status is EnvironmentBackupStatus(status)
        assert mock_transport.execute.await_count == 1

    @staticmethod
    @pytest.mark.asyncio
    async def test_wait_for_backup_returns_last_snapshot_on_timeout(
        client: StyrminClient, mock_transport: AsyncMock
    ) -> None:
        mock_transport.execute.return_value = {"data": {"environmentBackup": _environment_backup(status="IN_PROGRESS")}}

        environment_backup = await client.environment_backups.wait_for_backup(ENV_BACKUP_ID, max_wait=0, interval=0)

        assert environment_backup.status is EnvironmentBackupStatus.IN_PROGRESS
