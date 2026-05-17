"""Tests for the backup-locations command group."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from styrmin_sdk.exceptions import StyrminError
from styrminctl.cli import app

BSL_UUID = "c3d4e5f6-a7b8-9012-cdef-123456789012"
ENV_UUID = "b2c3d4e5-f6a7-8901-bcde-f12345678901"


def test_backup_locations_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["backup-locations", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "create" in output
    assert "list" in output
    assert "get" in output
    assert "delete" in output
    assert "assign" in output
    assert "unassign" in output


def test_backup_locations_create(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_bsl = MagicMock(id=BSL_UUID, name="my-s3")
    mock_client.backup_storage_locations.create = AsyncMock(return_value=mock_bsl)

    with pytest.raises(SystemExit) as exc:
        app(
            [
                "backup-locations",
                "create",
                "my-s3",
                "--endpoint",
                "https://s3.example.com",
                "--bucket",
                "backups",
                "--region",
                "us-east-1",
                "--access-key-id",
                "AKID",
                "--secret-access-key",
                "SECRET",
            ]
        )
    assert exc.value.code == 0
    mock_client.backup_storage_locations.create.assert_called_once_with(
        name="my-s3",
        endpoint="https://s3.example.com",
        bucket="backups",
        region="us-east-1",
        access_key_id="AKID",
        secret_access_key="SECRET",
    )
    output = capsys.readouterr().out
    assert "my-s3" in output


def test_backup_locations_list(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_bsl = MagicMock(
        id=BSL_UUID,
        endpoint="https://s3.example.com",
        bucket="backups",
        region="us-east-1",
        environment_count=2,
    )
    mock_bsl.name = "my-s3"
    mock_client.backup_storage_locations.list = AsyncMock(return_value=[mock_bsl])

    with pytest.raises(SystemExit) as exc:
        app(["backup-locations", "list"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "my-s3" in output


def test_backup_locations_list_empty(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.backup_storage_locations.list = AsyncMock(return_value=[])

    with pytest.raises(SystemExit) as exc:
        app(["backup-locations", "list"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "No backup storage locations found" in output


def test_backup_locations_get(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_bsl = MagicMock(
        id=BSL_UUID,
        name="my-s3",
        endpoint="https://s3.example.com",
        bucket="backups",
        region="us-east-1",
        environment_count=2,
    )
    mock_client.backup_storage_locations.get = AsyncMock(return_value=mock_bsl)

    with pytest.raises(SystemExit) as exc:
        app(["backup-locations", "get", BSL_UUID])
    assert exc.value.code == 0
    mock_client.backup_storage_locations.get.assert_called_once_with(BSL_UUID)


def test_backup_locations_delete(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.backup_storage_locations.delete = AsyncMock(return_value=None)

    with pytest.raises(SystemExit) as exc:
        app(["backup-locations", "delete", BSL_UUID])
    assert exc.value.code == 0
    mock_client.backup_storage_locations.delete.assert_called_once_with(BSL_UUID)
    output = capsys.readouterr().out
    assert "deleted" in output.lower()


def test_backup_locations_assign(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.environments.get = AsyncMock(return_value=MagicMock(id=ENV_UUID))
    mock_client.backup_storage_locations.assign = AsyncMock(return_value=None)

    with pytest.raises(SystemExit) as exc:
        app(["backup-locations", "assign", ENV_UUID, BSL_UUID])
    assert exc.value.code == 0
    mock_client.environments.get.assert_called_once_with(
        environment_name=ENV_UUID, cluster_id=None, cluster_name="default"
    )
    mock_client.backup_storage_locations.assign.assert_called_once_with(ENV_UUID, BSL_UUID)
    output = capsys.readouterr().out
    assert "assigned" in output.lower()


def test_backup_locations_unassign(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.environments.get = AsyncMock(return_value=MagicMock(id=ENV_UUID))
    mock_client.backup_storage_locations.unassign = AsyncMock(return_value=None)

    with pytest.raises(SystemExit) as exc:
        app(["backup-locations", "unassign", ENV_UUID])
    assert exc.value.code == 0
    mock_client.environments.get.assert_called_once_with(
        environment_name=ENV_UUID, cluster_id=None, cluster_name="default"
    )
    mock_client.backup_storage_locations.unassign.assert_called_once_with(ENV_UUID)
    output = capsys.readouterr().out
    assert "unassigned" in output.lower()


def test_backup_locations_create_error(mock_client: MagicMock) -> None:
    mock_client.backup_storage_locations.create = AsyncMock(side_effect=StyrminError("API error"))

    with pytest.raises(SystemExit) as exc:
        app(
            [
                "backup-locations",
                "create",
                "bad",
                "--endpoint",
                "x",
                "--bucket",
                "x",
                "--region",
                "x",
                "--access-key-id",
                "x",
                "--secret-access-key",
                "x",
            ]
        )
    assert exc.value.code == 1
