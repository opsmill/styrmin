"""Tests for the backups command group."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from styrmin_sdk.exceptions import StyrminError
from styrminctl.cli import app

BACKUP_UUID = "d4e5f6a7-b8c9-0123-def0-123456789abc"
INSTANCE_UUID = "e5f6a7b8-c9d0-1234-ef01-23456789abcd"
RESTORE_UUID = "f6a7b8c9-d0e1-2345-f012-3456789abcde"
DEPLOYMENT_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
ENV_UUID = "b2c3d4e5-f6a7-8901-bcde-f12345678901"

NS = "ns-1"


def _make_deployment(*, name: str, deployment_id: str = DEPLOYMENT_UUID, instance_id: str | None = INSTANCE_UUID):
    """Build a mock deployment whose ``.name`` is a real string (the resolver matches on it)."""
    deployment = MagicMock(id=deployment_id)
    deployment.name = name
    deployment.application_instance = MagicMock(id=instance_id) if instance_id is not None else None
    return deployment


def _make_environment(*, name: str, env_id: str = ENV_UUID):
    env = MagicMock(id=env_id)
    env.name = name
    return env


def _seed_name_lookup(mock_client: MagicMock, *, deployments: list, environments: list | None = None) -> None:
    """Wire environments.list / deployments.list for a deployment-name lookup."""
    envs = environments if environments is not None else [_make_environment(name="prod")]
    mock_client.environments.list = AsyncMock(return_value=envs)
    mock_client.deployments.list = AsyncMock(return_value=deployments)


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


# --- create ---------------------------------------------------------------


def test_backups_create_by_deployment_name(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_name_lookup(mock_client, deployments=[_make_deployment(name="demo")])
    mock_backup = MagicMock(id=BACKUP_UUID, status="pending")
    mock_backup.name = "backup-1"
    mock_client.backups.create_backup = AsyncMock(return_value=mock_backup)

    with pytest.raises(SystemExit) as exc:
        app(["backups", "create", "demo"])
    assert exc.value.code == 0
    mock_client.backups.create_backup.assert_called_once_with(instance_id=INSTANCE_UUID, name=None)
    assert "backup-1" in capsys.readouterr().out


def test_backups_create_by_deployment_name_scoped_to_environment(mock_client: MagicMock) -> None:
    _seed_name_lookup(
        mock_client,
        environments=[_make_environment(name="prod"), _make_environment(name="staging", env_id=ENV_UUID)],
        deployments=[_make_deployment(name="demo")],
    )
    mock_client.backups.create_backup = AsyncMock(return_value=MagicMock(id=BACKUP_UUID, status="pending"))

    with pytest.raises(SystemExit) as exc:
        app(["backups", "create", "demo", "--environment", "prod"])
    assert exc.value.code == 0
    # Only the matching environment is queried for deployments.
    mock_client.deployments.list.assert_called_once_with(ENV_UUID)
    mock_client.backups.create_backup.assert_called_once_with(instance_id=INSTANCE_UUID, name=None)


def test_backups_create_by_deployment_id(mock_client: MagicMock) -> None:
    mock_client.deployments.get = AsyncMock(return_value=_make_deployment(name="demo"))
    mock_client.backups.create_backup = AsyncMock(return_value=MagicMock(id=BACKUP_UUID, status="pending"))

    with pytest.raises(SystemExit) as exc:
        app(["backups", "create", "--id", DEPLOYMENT_UUID])
    assert exc.value.code == 0
    mock_client.deployments.get.assert_called_once_with(DEPLOYMENT_UUID)
    mock_client.backups.create_backup.assert_called_once_with(instance_id=INSTANCE_UUID, name=None)


def test_backups_create_by_instance_id_escape_hatch(mock_client: MagicMock) -> None:
    mock_client.backups.create_backup = AsyncMock(return_value=MagicMock(id=BACKUP_UUID, status="pending"))

    with pytest.raises(SystemExit) as exc:
        app(["backups", "create", "--instance-id", INSTANCE_UUID, "--name", "my-backup"])
    assert exc.value.code == 0
    # The escape hatch bypasses deployment resolution entirely.
    mock_client.deployments.get.assert_not_called()
    mock_client.backups.create_backup.assert_called_once_with(instance_id=INSTANCE_UUID, name="my-backup")


def test_backups_create_without_target_is_rejected(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["backups", "create"])
    assert exc.value.code == 1
    mock_client.backups.create_backup.assert_not_called()
    assert "Provide a deployment name" in capsys.readouterr().out


def test_backups_create_no_active_instance_errors(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.deployments.get = AsyncMock(return_value=_make_deployment(name="demo", instance_id=None))

    with pytest.raises(SystemExit) as exc:
        app(["backups", "create", "--id", DEPLOYMENT_UUID])
    assert exc.value.code == 1
    mock_client.backups.create_backup.assert_not_called()
    assert "no active instance" in capsys.readouterr().out


def test_backups_create_ambiguous_name_errors(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_name_lookup(
        mock_client,
        environments=[_make_environment(name="prod"), _make_environment(name="staging", env_id=ENV_UUID)],
        deployments=[_make_deployment(name="demo")],  # returned for every environment -> two matches
    )

    with pytest.raises(SystemExit) as exc:
        app(["backups", "create", "demo"])
    assert exc.value.code == 1
    mock_client.backups.create_backup.assert_not_called()
    assert "Multiple deployments named" in capsys.readouterr().out


# --- list -----------------------------------------------------------------


def test_backups_list_by_deployment_name(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_name_lookup(mock_client, deployments=[_make_deployment(name="demo")])
    mock_backup = MagicMock(id=BACKUP_UUID, status="completed", started_at="x", completed_at="y", size_bytes=1)
    mock_backup.name = "backup-1"
    mock_client.backups.list_backups = AsyncMock(return_value=[mock_backup])

    with pytest.raises(SystemExit) as exc:
        app(["backups", "list", "demo"])
    assert exc.value.code == 0
    mock_client.backups.list_backups.assert_called_once_with(instance_id=INSTANCE_UUID, status=None)
    assert "backup-1" in capsys.readouterr().out


def test_backups_list_by_instance_id_escape_hatch(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.backups.list_backups = AsyncMock(return_value=[])

    with pytest.raises(SystemExit) as exc:
        app(["backups", "list", "--instance-id", INSTANCE_UUID])
    assert exc.value.code == 0
    mock_client.backups.list_backups.assert_called_once_with(instance_id=INSTANCE_UUID, status=None)
    assert "No backups found" in capsys.readouterr().out


# --- get / delete ---------------------------------------------------------


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
    assert BACKUP_UUID in capsys.readouterr().out


def test_backups_delete(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.backups.delete_backup = AsyncMock(return_value=None)

    with pytest.raises(SystemExit) as exc:
        app(["backups", "delete", BACKUP_UUID])
    assert exc.value.code == 0
    mock_client.backups.delete_backup.assert_called_once_with(BACKUP_UUID)
    assert "deleted" in capsys.readouterr().out.lower()


# --- restore --------------------------------------------------------------


def test_backups_restore_backup_into_explicit_namespace(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    mock_restore = MagicMock(id=RESTORE_UUID, status="pending")
    mock_restore.name = "restore-1"
    mock_client.backups.create_restore = AsyncMock(return_value=mock_restore)

    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", BACKUP_UUID, "--target-namespace", NS])
    assert exc.value.code == 0
    mock_client.backups.create_restore.assert_called_once_with(
        backup_id=BACKUP_UUID,
        target_namespace=NS,
        target_instance_id=None,
    )
    assert "restore-1" in capsys.readouterr().out


def test_backups_restore_into_deployment_derives_namespace(mock_client: MagicMock) -> None:
    mock_client.deployments.get = AsyncMock(return_value=_make_deployment(name="demo"))
    mock_client.backups.create_restore = AsyncMock(return_value=MagicMock(id=RESTORE_UUID, status="pending"))

    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", BACKUP_UUID, "--target-deployment-id", DEPLOYMENT_UUID])
    assert exc.value.code == 0
    mock_client.backups.create_restore.assert_called_once_with(
        backup_id=BACKUP_UUID,
        target_namespace=f"styrmin-{DEPLOYMENT_UUID}",
        target_instance_id=INSTANCE_UUID,
    )


def test_backups_restore_into_deployment_by_name(mock_client: MagicMock) -> None:
    _seed_name_lookup(mock_client, deployments=[_make_deployment(name="demo")])
    mock_client.backups.create_restore = AsyncMock(return_value=MagicMock(id=RESTORE_UUID, status="pending"))

    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", BACKUP_UUID, "--target-deployment", "demo"])
    assert exc.value.code == 0
    mock_client.backups.create_restore.assert_called_once_with(
        backup_id=BACKUP_UUID,
        target_namespace=f"styrmin-{DEPLOYMENT_UUID}",
        target_instance_id=INSTANCE_UUID,
    )


def test_backups_restore_to_instance_requires_namespace(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", BACKUP_UUID, "--target-instance-id", INSTANCE_UUID])
    assert exc.value.code == 1
    mock_client.backups.create_restore.assert_not_called()
    assert "--target-namespace is required" in capsys.readouterr().out


def test_backups_restore_last_by_deployment(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.deployments.get = AsyncMock(return_value=_make_deployment(name="demo"))
    newest = MagicMock(id=BACKUP_UUID, status="completed")
    older = MagicMock(id="11111111-2222-3333-4444-555555555555", status="completed")
    mock_client.backups.list_backups = AsyncMock(return_value=[newest, older])
    mock_client.backups.create_restore = AsyncMock(return_value=MagicMock(id=RESTORE_UUID, status="pending"))

    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", "--last", "--target-deployment-id", DEPLOYMENT_UUID])
    assert exc.value.code == 0
    mock_client.backups.list_backups.assert_called_once_with(instance_id=INSTANCE_UUID, status="completed")
    mock_client.backups.create_restore.assert_called_once_with(
        backup_id=BACKUP_UUID,
        target_namespace=f"styrmin-{DEPLOYMENT_UUID}",
        target_instance_id=INSTANCE_UUID,
    )
    assert BACKUP_UUID in capsys.readouterr().out


def test_backups_restore_last_by_instance_id(mock_client: MagicMock) -> None:
    newest = MagicMock(id=BACKUP_UUID, status="completed")
    mock_client.backups.list_backups = AsyncMock(return_value=[newest])
    mock_client.backups.create_restore = AsyncMock(return_value=MagicMock(id=RESTORE_UUID, status="pending"))

    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", "--last", "--target-instance-id", INSTANCE_UUID, "--target-namespace", NS])
    assert exc.value.code == 0
    mock_client.backups.list_backups.assert_called_once_with(instance_id=INSTANCE_UUID, status="completed")
    mock_client.backups.create_restore.assert_called_once_with(
        backup_id=BACKUP_UUID,
        target_namespace=NS,
        target_instance_id=INSTANCE_UUID,
    )


def test_backups_restore_last_requires_a_target(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", "--last", "--target-namespace", NS])
    assert exc.value.code == 1
    mock_client.backups.list_backups.assert_not_called()
    mock_client.backups.create_restore.assert_not_called()
    assert "--last requires a target" in capsys.readouterr().out


def test_backups_restore_last_and_backup_id_is_rejected(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        app(
            [
                "backups",
                "restore",
                BACKUP_UUID,
                "--last",
                "--target-instance-id",
                INSTANCE_UUID,
                "--target-namespace",
                NS,
            ]
        )
    assert exc.value.code == 1
    mock_client.backups.create_restore.assert_not_called()
    assert "not both" in capsys.readouterr().out


def test_backups_restore_last_no_completed_backups_exits_nonzero(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    mock_client.backups.list_backups = AsyncMock(return_value=[])

    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", "--last", "--target-instance-id", INSTANCE_UUID, "--target-namespace", NS])
    assert exc.value.code == 1
    mock_client.backups.create_restore.assert_not_called()
    assert "No completed backups" in capsys.readouterr().out


def test_backups_restore_without_backup_id_or_last_is_rejected(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", "--target-namespace", NS])
    assert exc.value.code == 1
    mock_client.backups.create_restore.assert_not_called()
    assert "backup_id is required" in capsys.readouterr().out


def test_backups_restore_conflicting_targets_rejected(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        app(
            [
                "backups",
                "restore",
                BACKUP_UUID,
                "--target-deployment-id",
                DEPLOYMENT_UUID,
                "--target-instance-id",
                INSTANCE_UUID,
            ]
        )
    assert exc.value.code == 1
    mock_client.backups.create_restore.assert_not_called()
    assert "only one of" in capsys.readouterr().out.lower()


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
    assert RESTORE_UUID in capsys.readouterr().out


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
    assert RESTORE_UUID[:8] in capsys.readouterr().out


def test_backups_restore_list_empty(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.backups.list_restores = AsyncMock(return_value=[])

    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore-list", BACKUP_UUID])
    assert exc.value.code == 0
    assert "No restores found" in capsys.readouterr().out


def test_backups_create_error(mock_client: MagicMock) -> None:
    mock_client.backups.create_backup = AsyncMock(side_effect=StyrminError("API error"))

    with pytest.raises(SystemExit) as exc:
        app(["backups", "create", "--instance-id", INSTANCE_UUID])
    assert exc.value.code == 1
