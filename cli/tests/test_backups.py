"""Tests for the backups command group."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from styrmin_sdk.exceptions import StyrminError
from styrminctl.cli import app
from styrminctl.commands import backups as backups_commands

BACKUP_UUID = "d4e5f6a7-b8c9-0123-def0-123456789abc"
INSTANCE_UUID = "e5f6a7b8-c9d0-1234-ef01-23456789abcd"
PREVIOUS_INSTANCE_UUID = "c3d4e5f6-a7b8-9012-cdef-0123456789ab"
RESTORE_UUID = "f6a7b8c9-d0e1-2345-f012-3456789abcde"
DEPLOYMENT_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
ENV_UUID = "b2c3d4e5-f6a7-8901-bcde-f12345678901"

NS = "ns-1"
APP_VERSION = "1.4.2"


def _make_deployment(
    *,
    name: str,
    deployment_id: str = DEPLOYMENT_UUID,
    instance_id: str | None = INSTANCE_UUID,
    application_version: str = APP_VERSION,
    deleted_at: str | None = None,
):
    """Build a mock deployment whose ``.name`` is a real string (the resolver matches on it)."""
    deployment = MagicMock(id=deployment_id, application_version=application_version, deleted_at=deleted_at)
    deployment.name = name
    deployment.application_instance = MagicMock(id=instance_id) if instance_id is not None else None
    return deployment


def _make_completed_backup(
    backup_id: str = BACKUP_UUID,
    *,
    instance_id: str = INSTANCE_UUID,
    application_version: str = APP_VERSION,
    expires_at: datetime | None = None,
    deployment_id: str = DEPLOYMENT_UUID,
):
    """A completed backup as ``list_backups`` returns it, with real expiry, version and deployment values."""
    backup = MagicMock(id=backup_id, status="completed", instance_id=instance_id, expires_at=expires_at)
    backup.instance.application_version = application_version
    backup.instance.deployment_id = deployment_id
    return backup


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


def test_backups_list_by_deployment_name(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    _seed_name_lookup(mock_client, deployments=[_make_deployment(name="demo")])
    mock_backup = MagicMock(
        id=BACKUP_UUID,
        status="completed",
        started_at="x",
        completed_at="y",
        size_bytes=1,
        expires_at="2026-11-01T12:04:06+00:00",
    )
    mock_backup.name = "backup-1"
    mock_backup.instance.application_version = APP_VERSION
    mock_client.backups.list_backups = AsyncMock(return_value=[mock_backup])

    with pytest.raises(SystemExit) as exc:
        app(["backups", "list", "demo"])
    assert exc.value.code == 0
    mock_client.backups.list_backups.assert_called_once_with(deployment_id=DEPLOYMENT_UUID, status=None)
    assert "backup-1" in capsys.readouterr().out


def test_backups_list_by_deployment_id_without_active_instance(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``list --id`` lists the deployment's history even when it has no active instance."""
    monkeypatch.setenv("COLUMNS", "200")
    mock_client.deployments.get = AsyncMock(return_value=_make_deployment(name="demo", instance_id=None))
    mock_backup = MagicMock(
        id=BACKUP_UUID,
        status="completed",
        started_at="x",
        completed_at="y",
        size_bytes=1,
        expires_at=None,
    )
    mock_backup.name = "backup-1"
    mock_backup.instance.application_version = APP_VERSION
    mock_client.backups.list_backups = AsyncMock(return_value=[mock_backup])

    with pytest.raises(SystemExit) as exc:
        app(["backups", "list", "--id", DEPLOYMENT_UUID])
    assert exc.value.code == 0
    mock_client.deployments.get.assert_called_once_with(DEPLOYMENT_UUID)
    mock_client.backups.list_backups.assert_called_once_with(deployment_id=DEPLOYMENT_UUID, status=None)
    assert "backup-1" in capsys.readouterr().out


def test_backups_list_shows_application_version_column(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each row shows the application version of the instance the backup was taken of."""
    monkeypatch.setenv("COLUMNS", "200")
    _seed_name_lookup(mock_client, deployments=[_make_deployment(name="demo")])
    newer = MagicMock(
        id=BACKUP_UUID, status="completed", started_at="x", completed_at="y", size_bytes=1, expires_at=None
    )
    newer.name = "backup-2"
    newer.instance.application_version = "2.0.0"
    older = MagicMock(
        id="11111111-2222-3333-4444-555555555555",
        status="completed",
        started_at="x",
        completed_at="y",
        size_bytes=1,
        expires_at=None,
    )
    older.name = "backup-1"
    older.instance.application_version = APP_VERSION
    mock_client.backups.list_backups = AsyncMock(return_value=[newer, older])

    with pytest.raises(SystemExit) as exc:
        app(["backups", "list", "demo"])
    assert exc.value.code == 0
    lines = capsys.readouterr().out.splitlines()
    header = next(line for line in lines if "application_version" in line)
    assert header.index("status") < header.index("application_version") < header.index("started_at")
    newer_row = next(line for line in lines if "backup-2" in line)
    older_row = next(line for line in lines if "backup-1" in line)
    assert "2.0.0" in newer_row
    assert APP_VERSION in older_row


def test_backups_list_shows_expiry_column(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recorded expiration renders in the ``expires_at`` column (SC-005)."""
    # Rich ellipsizes cells that do not fit; widen the console so the header
    # and the full ISO timestamp are asserted verbatim instead of truncated.
    monkeypatch.setenv("COLUMNS", "200")
    mock_backup = MagicMock(
        id=BACKUP_UUID,
        status="completed",
        started_at="x",
        completed_at="y",
        size_bytes=1,
        expires_at="2026-11-01T12:04:06+00:00",
    )
    mock_backup.name = "backup-1"
    mock_backup.instance.application_version = APP_VERSION
    mock_client.backups.list_backups = AsyncMock(return_value=[mock_backup])

    with pytest.raises(SystemExit) as exc:
        app(["backups", "list", "--instance-id", INSTANCE_UUID])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "expires_at" in output
    assert "2026-11-01T12:04:06+00:00" in output


def test_backups_list_renders_dash_without_expiry(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A backup with no recorded expiration renders the em-dash placeholder."""
    monkeypatch.setenv("COLUMNS", "200")
    mock_backup = MagicMock(
        id=BACKUP_UUID,
        status="failed",
        started_at="x",
        completed_at="y",
        size_bytes=None,
        expires_at=None,
    )
    mock_backup.name = "backup-1"
    mock_backup.instance.application_version = APP_VERSION
    mock_client.backups.list_backups = AsyncMock(return_value=[mock_backup])

    with pytest.raises(SystemExit) as exc:
        app(["backups", "list", "--instance-id", INSTANCE_UUID])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "expires_at" in output
    assert "—" in output


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
        ttl="2160h",
        expires_at="2026-11-01T12:04:06+00:00",
    )
    mock_backup.instance.application_version = APP_VERSION
    mock_client.backups.get_backup = AsyncMock(return_value=mock_backup)

    with pytest.raises(SystemExit) as exc:
        app(["backups", "get", BACKUP_UUID])
    assert exc.value.code == 0
    mock_client.backups.get_backup.assert_called_once_with(BACKUP_UUID)
    output = capsys.readouterr().out
    assert BACKUP_UUID in output
    assert f"Application version: {APP_VERSION}" in output
    assert "TTL: 2160h" in output
    assert "Expires at: 2026-11-01T12:04:06+00:00" in output


def test_backups_get_without_retention_metadata(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    """``get`` still prints the retention lines with the em-dash placeholder."""
    mock_backup = MagicMock(
        id=BACKUP_UUID,
        name="backup-1",
        status="failed",
        instance_id=INSTANCE_UUID,
        started_at="2024-01-01",
        completed_at=None,
        size_bytes=None,
        error_message=None,
        ttl=None,
        expires_at=None,
    )
    mock_client.backups.get_backup = AsyncMock(return_value=mock_backup)

    with pytest.raises(SystemExit) as exc:
        app(["backups", "get", BACKUP_UUID])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "TTL: —" in output
    assert "Expires at: —" in output


def test_backups_delete(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.backups.delete_backup = AsyncMock(return_value=None)

    with pytest.raises(SystemExit) as exc:
        app(["backups", "delete", BACKUP_UUID])
    assert exc.value.code == 0
    mock_client.backups.delete_backup.assert_called_once_with(BACKUP_UUID)
    assert "deleted" in capsys.readouterr().out.lower()


# --- restore --------------------------------------------------------------


def test_backups_restore_backup_id_alone_sends_only_the_backup_id(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """A backup is restored into the deployment it was taken of, so the command sends only its id."""
    mock_restore = MagicMock(id=RESTORE_UUID, status="pending")
    mock_restore.name = "restore-1"
    mock_client.backups.create_restore = AsyncMock(return_value=mock_restore)

    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", BACKUP_UUID])
    assert exc.value.code == 0
    mock_client.backups.create_restore.assert_called_once_with(backup_id=BACKUP_UUID)
    mock_client.backups.list_backups.assert_not_called()
    mock_client.deployments.get.assert_not_called()
    assert "restore-1" in capsys.readouterr().out


@pytest.mark.parametrize(
    "target_args",
    [
        pytest.param(["--target-deployment", "demo"], id="by-deployment-name"),
        pytest.param(["--target-deployment-id", DEPLOYMENT_UUID], id="by-deployment-id"),
        pytest.param(["--target-instance-id", INSTANCE_UUID], id="by-instance-id"),
        # --environment narrows --target-deployment, so it is refused next to a backup id too.
        pytest.param(["--environment", "prod"], id="environment"),
        # This refusal comes before the "only one of" refusal.
        pytest.param(
            ["--target-deployment-id", DEPLOYMENT_UUID, "--target-instance-id", INSTANCE_UUID],
            id="two-target-options",
        ),
    ],
)
def test_backups_restore_backup_id_with_a_target_option_is_refused(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    *,
    target_args: list[str],
) -> None:
    """The target options work only with ``--last``; the refusal comes before any call to the server."""
    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", BACKUP_UUID, *target_args])
    assert exc.value.code == 1
    # The client is never opened, so neither the target lookup nor the restore reaches the server.
    mock_client.__aenter__.assert_not_awaited()
    mock_client.backups.create_restore.assert_not_called()
    # Rich wraps the long message to the terminal width; compare it as one line.
    output = " ".join(capsys.readouterr().out.split())
    assert "work only with --last" in output
    assert "restored into the deployment it was taken of" in output
    assert f"Run the command again without {target_args[0]}" in output


def test_backups_restore_target_namespace_is_an_unknown_option(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")

    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", BACKUP_UUID, "--target-namespace", NS])
    assert exc.value.code == 1
    mock_client.__aenter__.assert_not_awaited()
    mock_client.backups.create_restore.assert_not_called()
    assert 'Unknown option: "--target-namespace"' in capsys.readouterr().err


@pytest.mark.parametrize(
    "target_args",
    [
        pytest.param(["--target-deployment", "demo"], id="by-deployment-name"),
        pytest.param(["--target-deployment-id", DEPLOYMENT_UUID], id="by-deployment-id"),
    ],
)
def test_backups_restore_last_by_deployment(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    target_args: list[str],
) -> None:
    """``--last`` picks the newest completed backup of the deployment's history, even of a replaced instance."""
    monkeypatch.setenv("COLUMNS", "200")
    _seed_name_lookup(mock_client, deployments=[_make_deployment(name="demo")])
    mock_client.deployments.get = AsyncMock(return_value=_make_deployment(name="demo"))
    newest = _make_completed_backup(instance_id=PREVIOUS_INSTANCE_UUID, application_version="1.4.1")
    older = _make_completed_backup("11111111-2222-3333-4444-555555555555")
    mock_client.backups.list_backups = AsyncMock(return_value=[newest, older])
    mock_client.backups.create_restore = AsyncMock(return_value=MagicMock(id=RESTORE_UUID, status="pending"))

    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", "--last", "--yes", *target_args])
    assert exc.value.code == 0
    mock_client.backups.list_backups.assert_called_once_with(deployment_id=DEPLOYMENT_UUID, status="completed")
    # The backup comes from the replaced instance. The command sends only its id: the server
    # restores it into the deployment it was taken of.
    mock_client.backups.create_restore.assert_called_once_with(backup_id=BACKUP_UUID)
    assert BACKUP_UUID in capsys.readouterr().out


def test_backups_restore_last_by_instance_id(mock_client: MagicMock) -> None:
    """``--last --target-instance-id`` needs no namespace option and sends only the chosen backup's id."""
    newest = _make_completed_backup()
    mock_client.deployments.get = AsyncMock(return_value=_make_deployment(name="demo"))
    mock_client.backups.list_backups = AsyncMock(return_value=[newest])
    mock_client.backups.create_restore = AsyncMock(return_value=MagicMock(id=RESTORE_UUID, status="pending"))

    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", "--last", "--target-instance-id", INSTANCE_UUID])
    assert exc.value.code == 0
    mock_client.backups.list_backups.assert_called_once_with(instance_id=INSTANCE_UUID, status="completed")
    mock_client.backups.create_restore.assert_called_once_with(backup_id=BACKUP_UUID)


def test_backups_restore_last_requires_a_target(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", "--last"])
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
            ]
        )
    assert exc.value.code == 1
    mock_client.backups.create_restore.assert_not_called()
    assert "not both" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("target_args", "expected_list_call", "expected_message"),
    [
        pytest.param(
            ["--target-deployment", "demo"],
            {"deployment_id": DEPLOYMENT_UUID, "status": "completed"},
            "No completed backups found for deployment 'demo'",
            id="by-deployment-name",
        ),
        pytest.param(
            ["--target-deployment-id", DEPLOYMENT_UUID],
            {"deployment_id": DEPLOYMENT_UUID, "status": "completed"},
            f"No completed backups found for deployment '{DEPLOYMENT_UUID}'",
            id="by-deployment-id",
        ),
        pytest.param(
            ["--target-instance-id", INSTANCE_UUID],
            {"instance_id": INSTANCE_UUID, "status": "completed"},
            f"No completed backups found for instance {INSTANCE_UUID}",
            id="by-instance-id",
        ),
    ],
)
def test_backups_restore_last_no_completed_backups_exits_nonzero(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    target_args: list[str],
    expected_list_call: dict[str, str],
    expected_message: str,
) -> None:
    """The failure names the deployment when one is targeted, and the instance otherwise."""
    monkeypatch.setenv("COLUMNS", "200")
    _seed_name_lookup(mock_client, deployments=[_make_deployment(name="demo")])
    mock_client.deployments.get = AsyncMock(return_value=_make_deployment(name="demo"))
    mock_client.backups.list_backups = AsyncMock(return_value=[])

    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", "--last", *target_args])
    assert exc.value.code == 1
    mock_client.backups.list_backups.assert_called_once_with(**expected_list_call)
    mock_client.backups.create_restore.assert_not_called()
    assert expected_message in capsys.readouterr().out


def test_backups_restore_without_backup_id_or_last_is_rejected(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore"])
    assert exc.value.code == 1
    mock_client.backups.create_restore.assert_not_called()
    assert "backup_id is required" in capsys.readouterr().out


def test_backups_restore_conflicting_targets_rejected(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """With ``--last``, only one target option may name whose backup history is used."""
    with pytest.raises(SystemExit) as exc:
        app(
            [
                "backups",
                "restore",
                "--last",
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


# --- restore --last: expiry and earlier instances (#304 review) ------------


def _arm_restore_last(mock_client: MagicMock, backups: list, *, deployment=None) -> None:
    mock_client.deployments.get = AsyncMock(return_value=deployment or _make_deployment(name="demo"))
    mock_client.backups.list_backups = AsyncMock(return_value=backups)
    mock_client.backups.create_restore = AsyncMock(return_value=MagicMock(id=RESTORE_UUID, status="pending"))


def _restore_last(*extra: str) -> int | str | None:
    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", "--last", "--target-deployment-id", DEPLOYMENT_UUID, *extra])
    return exc.value.code


def test_backups_restore_last_skips_expired_backups(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    expired = _make_completed_backup(
        "11111111-2222-3333-4444-555555555555", expires_at=datetime.now(UTC) - timedelta(days=1)
    )
    usable = _make_completed_backup(expires_at=datetime.now(UTC) + timedelta(days=30))
    _arm_restore_last(mock_client, [expired, usable])

    assert _restore_last() == 0
    mock_client.backups.create_restore.assert_called_once_with(backup_id=BACKUP_UUID)
    output = capsys.readouterr().out
    assert "Skipped 1 newer completed backup(s) whose expiry date has passed" in output
    assert f"(application version {APP_VERSION})" in output


def test_backups_restore_last_fails_when_every_backup_expired(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    _arm_restore_last(mock_client, [_make_completed_backup(expires_at=datetime.now(UTC) - timedelta(days=1))])

    assert _restore_last() == 1
    mock_client.backups.create_restore.assert_not_called()
    output = capsys.readouterr().out
    assert "that have not expired" in output
    assert "1 completed backup(s) have passed their expiry date" in output


def test_backups_restore_last_of_the_current_instance_does_not_ask(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backups_commands, "_stdin_is_terminal", lambda: False)
    _arm_restore_last(mock_client, [_make_completed_backup()])

    assert _restore_last() == 0
    mock_client.backups.create_restore.assert_called_once_with(backup_id=BACKUP_UUID)
    assert "Warning" not in capsys.readouterr().out


def test_backups_restore_last_of_an_earlier_instance_needs_yes_without_a_terminal(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(backups_commands, "_stdin_is_terminal", lambda: False)
    _arm_restore_last(
        mock_client, [_make_completed_backup(instance_id=PREVIOUS_INSTANCE_UUID, application_version="1.4.1")]
    )

    assert _restore_last() == 1
    mock_client.backups.create_restore.assert_not_called()
    output = capsys.readouterr().out
    assert "earlier instance" in output
    assert "application version 1.4.1" in output
    assert f"runs application version {APP_VERSION} now" in output
    assert "HelmRelease" in output
    assert "Pass --yes" in output


@pytest.mark.parametrize(("answer", "code"), [(True, 0), (False, 1)])
def test_backups_restore_last_of_an_earlier_instance_asks_in_a_terminal(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    answer: bool,
    code: int,
) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(backups_commands, "_stdin_is_terminal", lambda: True)
    asked: list[str] = []

    def _ask(prompt: str, **_: object) -> bool:
        asked.append(prompt)
        return answer

    monkeypatch.setattr(backups_commands.Confirm, "ask", _ask)
    _arm_restore_last(mock_client, [_make_completed_backup(instance_id=PREVIOUS_INSTANCE_UUID)])

    assert _restore_last() == code
    assert asked == ["Restore this backup?"]
    if answer:
        mock_client.backups.create_restore.assert_called_once_with(backup_id=BACKUP_UUID)
    else:
        mock_client.backups.create_restore.assert_not_called()
        assert "Restore cancelled." in capsys.readouterr().out


def test_backups_restore_last_into_a_deleted_deployment_is_refused(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    _arm_restore_last(
        mock_client,
        [_make_completed_backup()],
        deployment=_make_deployment(name="demo", deleted_at="2026-10-01T00:00:00+00:00"),
    )

    assert _restore_last("--yes") == 1
    mock_client.backups.create_restore.assert_not_called()
    output = capsys.readouterr().out
    assert "Deployment 'demo' was deleted" in output
    assert f"styrminctl backups list --id {DEPLOYMENT_UUID}" in output


# --- restore --last --target-instance-id: earlier instances (#532 review) --


def _restore_last_of_instance(instance_id: str, *extra: str) -> int | str | None:
    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", "--last", "--target-instance-id", instance_id, *extra])
    return exc.value.code


def test_backups_restore_last_of_an_earlier_instance_id_needs_yes_without_a_terminal(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raw instance id that is an earlier instance of its deployment asks like ``--target-deployment-id`` does."""
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(backups_commands, "_stdin_is_terminal", lambda: False)
    _arm_restore_last(
        mock_client, [_make_completed_backup(instance_id=PREVIOUS_INSTANCE_UUID, application_version="1.4.1")]
    )

    assert _restore_last_of_instance(PREVIOUS_INSTANCE_UUID) == 1
    mock_client.backups.list_backups.assert_called_once_with(instance_id=PREVIOUS_INSTANCE_UUID, status="completed")
    mock_client.backups.create_restore.assert_not_called()
    output = capsys.readouterr().out
    assert "earlier instance of deployment 'demo'" in output
    assert "application version 1.4.1" in output
    assert f"runs application version {APP_VERSION} now" in output
    assert "Pass --yes" in output


def test_backups_restore_last_of_an_earlier_instance_id_with_yes_restores(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(backups_commands, "_stdin_is_terminal", lambda: False)
    _arm_restore_last(
        mock_client, [_make_completed_backup(instance_id=PREVIOUS_INSTANCE_UUID, application_version="1.4.1")]
    )

    assert _restore_last_of_instance(PREVIOUS_INSTANCE_UUID, "--yes") == 0
    mock_client.deployments.get.assert_awaited_with(DEPLOYMENT_UUID)
    mock_client.backups.create_restore.assert_called_once_with(backup_id=BACKUP_UUID)
    assert "earlier instance of deployment 'demo'" in capsys.readouterr().out


def test_backups_restore_last_of_the_active_instance_id_does_not_ask(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backups_commands, "_stdin_is_terminal", lambda: False)
    _arm_restore_last(mock_client, [_make_completed_backup()])

    assert _restore_last_of_instance(INSTANCE_UUID) == 0
    # The command looks up the deployment the backup was taken of, to compare its active instance.
    mock_client.deployments.get.assert_awaited_with(DEPLOYMENT_UUID)
    mock_client.backups.create_restore.assert_called_once_with(backup_id=BACKUP_UUID)
    assert "Warning" not in capsys.readouterr().out


def test_backups_restore_last_of_an_instance_id_whose_deployment_has_no_active_instance_restores(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The server restores into a deployment without an active instance, so the command does not refuse it."""
    monkeypatch.setattr(backups_commands, "_stdin_is_terminal", lambda: False)
    _arm_restore_last(
        mock_client, [_make_completed_backup()], deployment=_make_deployment(name="demo", instance_id=None)
    )

    assert _restore_last_of_instance(INSTANCE_UUID) == 0
    mock_client.backups.create_restore.assert_called_once_with(backup_id=BACKUP_UUID)
    assert "Warning" not in capsys.readouterr().out


def test_backups_restore_last_of_an_instance_id_of_a_deleted_deployment_is_refused(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    _arm_restore_last(
        mock_client,
        [_make_completed_backup()],
        deployment=_make_deployment(name="demo", instance_id=None, deleted_at="2026-10-01T00:00:00+00:00"),
    )

    assert _restore_last_of_instance(INSTANCE_UUID, "--yes") == 1
    mock_client.backups.create_restore.assert_not_called()
    output = capsys.readouterr().out
    assert "Deployment 'demo' was deleted" in output
    assert f"styrminctl backups list --id {DEPLOYMENT_UUID}" in output


# --- restore --last into a deployment without an active instance (#532 review) --


@pytest.mark.parametrize(
    "target_args",
    [
        pytest.param(["--target-deployment", "demo"], id="by-deployment-name"),
        pytest.param(["--target-deployment-id", DEPLOYMENT_UUID], id="by-deployment-id"),
    ],
)
def test_backups_restore_last_into_a_deployment_without_an_active_instance_restores(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    target_args: list[str],
) -> None:
    """``--last`` reads only the deployment's backup history, so it needs no active instance.

    The server restores into a deployment without one, as ``--target-instance-id`` and a bare
    backup id already do.
    """
    monkeypatch.setattr(backups_commands, "_stdin_is_terminal", lambda: False)
    without_instance = _make_deployment(name="demo", instance_id=None)
    _seed_name_lookup(mock_client, deployments=[without_instance])
    _arm_restore_last(mock_client, [_make_completed_backup()], deployment=without_instance)

    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", "--last", *target_args])
    assert exc.value.code == 0
    mock_client.backups.list_backups.assert_called_once_with(deployment_id=DEPLOYMENT_UUID, status="completed")
    mock_client.backups.create_restore.assert_called_once_with(backup_id=BACKUP_UUID)
    assert "Warning" not in capsys.readouterr().out


def test_backups_restore_last_at_another_version_into_a_deployment_without_an_active_instance_warns(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The warning does not say that Styrmin keeps a current instance the deployment does not have."""
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(backups_commands, "_stdin_is_terminal", lambda: False)
    _arm_restore_last(
        mock_client,
        [_make_completed_backup(application_version="1.4.1")],
        deployment=_make_deployment(name="demo", instance_id=None),
    )

    assert _restore_last() == 1
    mock_client.backups.create_restore.assert_not_called()
    output = " ".join(capsys.readouterr().out.split())
    assert "was taken of deployment 'demo', at application version 1.4.1" in output
    assert "has no active instance, and the restore does not give it one" in output
    assert "keeps the current instance" not in output
    assert "Pass --yes" in output


def test_backups_restore_last_of_an_instance_id_with_environment_is_refused(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", "--last", "--target-instance-id", INSTANCE_UUID, "--environment", "prod"])
    assert exc.value.code == 1
    mock_client.backups.list_backups.assert_not_called()
    mock_client.backups.create_restore.assert_not_called()
    assert "--environment only applies when looking up a deployment by name" in capsys.readouterr().out


def test_backups_restore_last_unknown_deployment_name_does_not_point_to_backups_list(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``--id`` hint belongs to ``backups list``; a deleted deployment cannot be restored into."""
    monkeypatch.setenv("COLUMNS", "200")
    _seed_name_lookup(mock_client, deployments=[_make_deployment(name="other")])

    with pytest.raises(SystemExit) as exc:
        app(["backups", "restore", "--last", "--target-deployment", "demo"])
    assert exc.value.code == 1
    mock_client.backups.create_restore.assert_not_called()
    output = capsys.readouterr().out
    assert "No deployment named 'demo'." in output
    assert "--id" not in output


# --- list: pointing to --id for a deleted deployment (#304 review) -------


def test_backups_list_by_name_without_backups_points_to_id(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    _seed_name_lookup(mock_client, deployments=[_make_deployment(name="demo")])
    mock_client.backups.list_backups = AsyncMock(return_value=[])

    with pytest.raises(SystemExit) as exc:
        app(["backups", "list", "demo"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "No backups found for deployment 'demo'" in output
    assert "--id <deployment-id>" in output


def test_backups_list_unknown_name_points_to_id(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    _seed_name_lookup(mock_client, deployments=[_make_deployment(name="other")])

    with pytest.raises(SystemExit) as exc:
        app(["backups", "list", "demo"])
    assert exc.value.code == 1
    mock_client.backups.list_backups.assert_not_called()
    output = capsys.readouterr().out
    assert "No deployment named 'demo'." in output
    assert "does not find a deleted deployment" in output
    assert "--id" in output
