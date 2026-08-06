"""Unit tests for EnvironmentBackupResource."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest
from styrmin_sdk import EnvironmentBackupStatus, EnvironmentRestoreStatus
from styrmin_sdk.exceptions import OperationFailedError, ResourceNotFoundError

if TYPE_CHECKING:
    from styrmin_sdk.client import StyrminClient

ENV_BACKUP_ID = "00000000-0000-0000-0000-0000000000e1"
ENV_RESTORE_ID = "00000000-0000-0000-0000-0000000000e2"
ENVIRONMENT_ID = "00000000-0000-0000-0000-0000000000e0"
DEPLOYMENT_ID = "00000000-0000-0000-0000-000000000100"
INSTANCE_ID = "00000000-0000-0000-0000-000000000010"
BACKUP_ID = "00000000-0000-0000-0000-000000000001"
RESTORE_ID = "00000000-0000-0000-0000-000000000002"


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


def _constituent_restore() -> dict[str, Any]:
    return {
        "id": RESTORE_ID,
        "name": "demo-restore",
        "status": "pending",
        "backupId": BACKUP_ID,
        "targetNamespace": "styrmin-demo",
        "targetInstanceId": INSTANCE_ID,
        "errorMessage": None,
        "startedAt": None,
        "completedAt": None,
    }


def _skipped(*, deployment_name: str = "other", reason: str = "backup not completed") -> dict[str, Any]:
    return {
        "deploymentId": "00000000-0000-0000-0000-000000000101",
        "deploymentName": deployment_name,
        "reason": reason,
    }


def _environment_restore(
    *,
    status: str = "PENDING",
    restores: list[dict[str, Any]] | None = None,
    skipped_constituents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": ENV_RESTORE_ID,
        "status": status,
        "createdOn": "2026-01-01T00:00:00",
        "updatedOn": None,
        "environmentBackupId": ENV_BACKUP_ID,
        "restores": restores if restores is not None else [_constituent_restore()],
        "skippedConstituents": skipped_constituents if skipped_constituents is not None else [],
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
    async def test_delete(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {"data": {"deleteEnvironmentBackup": True}}

        assert await client.environment_backups.delete(ENV_BACKUP_ID) is None

        query, variables = mock_transport.execute.call_args.args
        assert "deleteEnvironmentBackup" in query
        assert variables == {"environmentBackupId": ENV_BACKUP_ID}

    @staticmethod
    @pytest.mark.asyncio
    async def test_delete_not_found(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": None,
            "errors": [{"message": "Environment backup not found", "extensions": {"code": "NOT_FOUND"}}],
        }

        with pytest.raises(ResourceNotFoundError):
            await client.environment_backups.delete(ENV_BACKUP_ID)

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


class TestEnvironmentRestore:
    """The restore half of ``client.environment_backups`` (US2)."""

    @staticmethod
    @pytest.mark.asyncio
    async def test_restore(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": {"restoreEnvironmentBackup": _environment_restore(status="IN_PROGRESS")}
        }

        environment_restore = await client.environment_backups.restore(ENV_BACKUP_ID)

        assert environment_restore.status is EnvironmentRestoreStatus.IN_PROGRESS
        assert str(environment_restore.environment_backup_id) == ENV_BACKUP_ID
        assert len(environment_restore.restores) == 1
        _, variables = mock_transport.execute.call_args.args
        assert variables == {"environmentBackupId": ENV_BACKUP_ID}

    @staticmethod
    @pytest.mark.asyncio
    async def test_restore_reports_every_skip_with_a_reason(client: StyrminClient, mock_transport: AsyncMock) -> None:
        """FR-007: skips are complete in the mutation response, each attributed by name + reason."""
        mock_transport.execute.return_value = {
            "data": {
                "restoreEnvironmentBackup": _environment_restore(
                    status="PARTIAL",
                    skipped_constituents=[
                        _skipped(deployment_name="expired-one", reason="backup expired"),
                        _skipped(deployment_name="gone", reason="deployment no longer exists"),
                    ],
                )
            }
        }

        environment_restore = await client.environment_backups.restore(ENV_BACKUP_ID)

        assert environment_restore.status is EnvironmentRestoreStatus.PARTIAL
        assert [(s.deployment_name, s.reason) for s in environment_restore.skipped_constituents] == [
            ("expired-one", "backup expired"),
            ("gone", "deployment no longer exists"),
        ]

    @staticmethod
    @pytest.mark.asyncio
    async def test_restore_not_restorable(client: StyrminClient, mock_transport: AsyncMock) -> None:
        """A snapshot whose derived status is not COMPLETED/PARTIAL is refused, not silently retried."""
        mock_transport.execute.return_value = {
            "data": {"restoreEnvironmentBackup": None},
            "errors": [
                {
                    "message": "Environment backup is not restorable",
                    "extensions": {"code": "OPERATION_DENIED"},
                }
            ],
        }

        with pytest.raises(OperationFailedError):
            await client.environment_backups.restore(ENV_BACKUP_ID)

    @staticmethod
    @pytest.mark.asyncio
    async def test_restore_already_in_progress(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": {"restoreEnvironmentBackup": None},
            "errors": [
                {
                    "message": "An environment restore is already in progress",
                    "extensions": {"code": "ALREADY_IN_PROGRESS", "operation_kind": "restore"},
                }
            ],
        }

        with pytest.raises(OperationFailedError):
            await client.environment_backups.restore(ENV_BACKUP_ID)

    @staticmethod
    @pytest.mark.asyncio
    async def test_get_restore(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {"data": {"environmentRestore": _environment_restore(status="COMPLETED")}}

        environment_restore = await client.environment_backups.get_restore(ENV_RESTORE_ID)

        assert environment_restore.status is EnvironmentRestoreStatus.COMPLETED
        _, variables = mock_transport.execute.call_args.args
        assert variables == {"environmentRestoreId": ENV_RESTORE_ID}

    @staticmethod
    @pytest.mark.asyncio
    async def test_get_restore_not_found(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": {"environmentRestore": None},
            "errors": [{"message": "Environment restore not found", "extensions": {"code": "NOT_FOUND"}}],
        }

        with pytest.raises(ResourceNotFoundError):
            await client.environment_backups.get_restore(ENV_RESTORE_ID)

    @staticmethod
    @pytest.mark.asyncio
    async def test_list_restores(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": {
                "environmentRestores": [
                    {
                        "id": ENV_RESTORE_ID,
                        "status": "PARTIAL",
                        "createdOn": "2026-01-01T00:00:00",
                        "updatedOn": None,
                        "environmentBackupId": ENV_BACKUP_ID,
                        "restores": [
                            {
                                "id": RESTORE_ID,
                                "name": "demo-restore",
                                "status": "completed",
                                "backupId": BACKUP_ID,
                                "targetInstanceId": INSTANCE_ID,
                                "errorMessage": None,
                            }
                        ],
                        "skippedConstituents": [_skipped(reason="deployment busy with another restore")],
                    }
                ]
            }
        }

        environment_restores = await client.environment_backups.list_restores(ENV_BACKUP_ID)

        assert len(environment_restores) == 1
        assert environment_restores[0].status is EnvironmentRestoreStatus.PARTIAL
        assert environment_restores[0].skipped_constituents[0].reason == "deployment busy with another restore"
        _, variables = mock_transport.execute.call_args.args
        assert variables == {"environmentBackupId": ENV_BACKUP_ID}

    @staticmethod
    @pytest.mark.asyncio
    async def test_list_restores_empty(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {"data": {"environmentRestores": []}}

        assert await client.environment_backups.list_restores(ENV_BACKUP_ID) == []

    @staticmethod
    @pytest.mark.asyncio
    async def test_wait_for_restore_polls_until_terminal(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.side_effect = [
            {"data": {"environmentRestore": _environment_restore(status="IN_PROGRESS")}},
            {"data": {"environmentRestore": _environment_restore(status="COMPLETED")}},
        ]

        environment_restore = await client.environment_backups.wait_for_restore(ENV_RESTORE_ID, max_wait=10, interval=0)

        assert environment_restore.status is EnvironmentRestoreStatus.COMPLETED
        assert mock_transport.execute.await_count == 2

    @staticmethod
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["COMPLETED", "PARTIAL", "FAILED"])
    async def test_wait_for_restore_treats_partial_as_terminal(
        client: StyrminClient, mock_transport: AsyncMock, status: str
    ) -> None:
        """PARTIAL is a final outcome — polling must stop, not spin until timeout."""
        mock_transport.execute.return_value = {"data": {"environmentRestore": _environment_restore(status=status)}}

        environment_restore = await client.environment_backups.wait_for_restore(ENV_RESTORE_ID, max_wait=10, interval=0)

        assert environment_restore.status is EnvironmentRestoreStatus(status)
        assert mock_transport.execute.await_count == 1

    @staticmethod
    @pytest.mark.asyncio
    async def test_wait_for_restore_returns_last_record_on_timeout(
        client: StyrminClient, mock_transport: AsyncMock
    ) -> None:
        mock_transport.execute.return_value = {
            "data": {"environmentRestore": _environment_restore(status="IN_PROGRESS")}
        }

        environment_restore = await client.environment_backups.wait_for_restore(ENV_RESTORE_ID, max_wait=0, interval=0)

        assert environment_restore.status is EnvironmentRestoreStatus.IN_PROGRESS
