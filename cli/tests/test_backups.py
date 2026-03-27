"""Tests for the backups command group."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from styrmin_sdk.exceptions import StyrminError
from styrminctl.cli import app

BACKUP_UUID = "d4e5f6a7-b8c9-0123-def0-123456789abc"
INSTANCE_UUID = "e5f6a7b8-c9d0-1234-ef01-23456789abcd"
RESTORE_UUID = "f6a7b8c9-d0e1-2345-f012-3456789abcde"

NS = "ns-1"


def test_backups_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["backups", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "create" in output
    assert "get" in output
    assert "list" in output
    assert "delete" in output
    assert "restore" in output
    assert "restore-get" in output
    assert "restore-list" in output


def test_backups_create(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_backup = MagicMock(id=BACKUP_UUID, name="backup-1", status="pending")
    mock_client.backups.create_backup = AsyncMock(return_value=mock_backup)

    with pytest.raises(SystemExit) as exc:
        app(["backups", "create", INSTANCE_UUID])
    assert exc.value.code == 0
    mock_client.backups.create_backup.assert_called_once_with(instance_id=INSTANCE_UUID, name=None)
    output = capsys.readouterr().out
    assert "backup-1" in output


def test_backups_create_with_name(mock_client: MagicMock) -> None:
    mock_backup = MagicMock(id=BACKUP_UUID, name="my-backup", status="pending")
    mock_client.backups.create_backup = AsyncMock(return_value=mock_backup)

    with pytest.raises(SystemExit) as exc:
        app(["backups", "create", INSTANCE_UUID, "--name", "my-backup"])
    assert exc.value.code == 0
    mock_client.backups.create_backup.assert_called_once_with(instance_id=INSTANCE_UUID, name="my-backup")


def test_backups_get(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_backup = MagicMock(
        id=BACKUP_UUID,
        name="backup-1",
        status="completed",
        instance_id=INSTANCE_UUID,
        started_at="2024-01-01",
        completed_at="2024-01-01",
        size_bytes=1024,
        error_message=None,
    )
    mock_client.backups.get_backup = AsyncMock(return_value=mock_backup)

    with pytest.raises(SystemExit) as exc:
        app(["backups", "get", BACKUP_UUID])
    assert exc.value.code == 0
    mock_client.backups.get_backup.assert_called_once_with(BACKUP_UUID)
    output = capsys.readouterr().out
    assert BACKUP_UUID in output


def test_backups_list(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_backup = MagicMock(
        id=BACKUP_UUID,
        status="completed",
        started_at="2024-01-01",
        completed_at="2024-01-01",
        size_bytes=1024,
    )
    mock_backup.name = "backup-1"
    mock_client.backups.list_backups = AsyncMock(return_value=[mock_backup])

    with pytest.raises(SystemExit) as exc:
        app(["backups", "list", INSTANCE_UUID])
    assert exc.value.code == 0
    mock_client.backups.list_backups.assert_called_once_with(instance_id=INSTANCE_UUID, status=None)
    output = capsys.readouterr().out
    assert "backup-1" in output


def test_backups_list_empty(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.backups.list_backups = AsyncMock(return_value=[])

    with pytest.raises(SystemExit) as exc:
        app(["backups", "list", INSTANCE_UUID])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "No backups found" in output


def test_backups_delete(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.backups.delete_backup = AsyncMock(return_value=None)

    with pytest.raises(SystemExit) as exc:
        app(["backups", "delete", BACKUP_UUID])
    assert exc.value.code == 0
    mock_client.backups.delete_backup.assert_called_once_with(BACKUP_UUID)
    output = capsys.readouterr().out
    assert "deleted" in output.lower()


def test_backups_restore(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_restore = MagicMock(id=RESTORE_UUID, name="restore-1", status="pending")
    mock_client.backups.create_restore = AsyncMock(return_value=mock_restore)

    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", BACKUP_UUID, "--target-namespace", NS])
    assert exc.value.code == 0
    mock_client.backups.create_restore.assert_called_once_with(
        backup_id=BACKUP_UUID,
        target_namespace=NS,
        target_instance_id=None,
    )
    output = capsys.readouterr().out
    assert "restore-1" in output


def test_backups_restore_get(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_restore = MagicMock(
        id=RESTORE_UUID,
        name="restore-1",
        status="completed",
        backup_id=BACKUP_UUID,
        target_namespace=NS,
        target_instance_id=None,
        started_at="2024-01-01",
        completed_at="2024-01-01",
        error_message=None,
    )
    mock_client.backups.get_restore = AsyncMock(return_value=mock_restore)

    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore-get", RESTORE_UUID])
    assert exc.value.code == 0
    mock_client.backups.get_restore.assert_called_once_with(RESTORE_UUID)
    output = capsys.readouterr().out
    assert RESTORE_UUID in output


def test_backups_restore_list(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_restore = MagicMock(
        id=RESTORE_UUID,
        status="completed",
        target_namespace=NS,
        started_at="2024-01-01",
        completed_at="2024-01-01",
    )
    mock_restore.name = "restore-1"
    mock_client.backups.list_restores = AsyncMock(return_value=[mock_restore])

    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore-list", BACKUP_UUID])
    assert exc.value.code == 0
    mock_client.backups.list_restores.assert_called_once_with(backup_id=BACKUP_UUID, status=None)
    output = capsys.readouterr().out
    assert RESTORE_UUID[:8] in output


def test_backups_restore_list_empty(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.backups.list_restores = AsyncMock(return_value=[])

    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore-list", BACKUP_UUID])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "No restores found" in output


def test_backups_create_error(mock_client: MagicMock) -> None:
    mock_client.backups.create_backup = AsyncMock(side_effect=StyrminError("API error"))

    with pytest.raises(SystemExit) as exc:
        app(["backups", "create", INSTANCE_UUID])
    assert exc.value.code == 1
