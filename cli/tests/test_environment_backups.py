"""Tests for the env-backups command group."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from styrmin_sdk import EnvironmentBackupStatus
from styrmin_sdk.exceptions import ResourceNotFoundError, StyrminError
from styrminctl.cli import app

ENV_UUID = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
ENV_BACKUP_UUID = "c3d4e5f6-a7b8-9012-cdef-123456789012"
CLUSTER_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
BACKUP_UUID = "d4e5f6a7-b8c9-0123-def0-123456789abc"
DEPLOYMENT_UUID = "e5f6a7b8-c9d0-1234-ef01-23456789abcd"


def _make_constituent(
    *,
    deployment_name: str,
    backup_status: str | None = "completed",
    error: str | None = None,
) -> MagicMock:
    """Build a per-constituent outcome: a backup, a creation error, or a gap (neither)."""
    backup = MagicMock(id=BACKUP_UUID, status=backup_status) if backup_status is not None else None
    constituent = MagicMock(id=DEPLOYMENT_UUID, backup=backup, error=error)
    constituent.deployment_name = deployment_name
    return constituent


def _make_environment_backup(
    *,
    status: EnvironmentBackupStatus = EnvironmentBackupStatus.PENDING,
    constituents: list[MagicMock] | None = None,
    name: str = "env-backup-1",
) -> MagicMock:
    environment_backup = MagicMock(
        id=ENV_BACKUP_UUID,
        status=status,
        environment_id=ENV_UUID,
        created_on="2026-01-01T00:00:00",
        environment_config={"backupStorageLocationId": None},
        deployment_snapshots=[MagicMock()],
        constituents=constituents if constituents is not None else [_make_constituent(deployment_name="demo")],
    )
    environment_backup.name = name
    return environment_backup


def _seed_environment(mock_client: MagicMock) -> None:
    environment = MagicMock(id=ENV_UUID)
    environment.name = "prod"
    mock_client.environments.get = AsyncMock(return_value=environment)


def test_env_backups_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "create" in output
    assert "get" in output
    assert "list" in output


# --- create ---------------------------------------------------------------


def test_env_backups_create_by_environment_name(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_environment(mock_client)
    mock_client.environment_backups.create = AsyncMock(return_value=_make_environment_backup())

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "create", "prod"])
    assert exc.value.code == 0
    # The name lookup is delegated to the server-side dual-identifier
    # ``environment`` query (ADR-0031) rather than matched in the CLI.
    mock_client.environments.get.assert_called_once_with(
        environment_name="prod", cluster_id=None, cluster_name="default"
    )
    mock_client.environment_backups.create.assert_called_once_with(environment_id=ENV_UUID, name=None)
    output = capsys.readouterr().out
    assert "env-backup-1" in output
    assert "PENDING" in output


def test_env_backups_create_scoped_to_cluster(mock_client: MagicMock) -> None:
    _seed_environment(mock_client)
    mock_client.environment_backups.create = AsyncMock(return_value=_make_environment_backup())

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "create", "prod", "--cluster", "edge"])
    assert exc.value.code == 0
    mock_client.environments.get.assert_called_once_with(environment_name="prod", cluster_id=None, cluster_name="edge")


def test_env_backups_create_scoped_to_cluster_id(mock_client: MagicMock) -> None:
    _seed_environment(mock_client)
    mock_client.environment_backups.create = AsyncMock(return_value=_make_environment_backup())

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "create", "prod", "--cluster-id", CLUSTER_UUID])
    assert exc.value.code == 0
    mock_client.environments.get.assert_called_once_with(
        environment_name="prod", cluster_id=CLUSTER_UUID, cluster_name=None
    )


def test_env_backups_create_by_environment_id(mock_client: MagicMock) -> None:
    mock_client.environment_backups.create = AsyncMock(return_value=_make_environment_backup())

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "create", "--id", ENV_UUID, "--name", "nightly"])
    assert exc.value.code == 0
    # --id short-circuits the lookup entirely.
    mock_client.environments.get.assert_not_called()
    mock_client.environment_backups.create.assert_called_once_with(environment_id=ENV_UUID, name="nightly")


def test_env_backups_create_rejects_name_and_id(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "create", "prod", "--id", ENV_UUID])
    assert exc.value.code == 1
    mock_client.environment_backups.create.assert_not_called()
    assert "not both" in capsys.readouterr().out


def test_env_backups_create_requires_a_target(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "create"])
    assert exc.value.code == 1
    mock_client.environment_backups.create.assert_not_called()
    assert "Either an environment name or --id is required" in capsys.readouterr().out


def test_env_backups_create_rejects_cluster_and_cluster_id(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "create", "prod", "--cluster", "edge", "--cluster-id", CLUSTER_UUID])
    assert exc.value.code == 1
    mock_client.environment_backups.create.assert_not_called()
    assert "not both" in capsys.readouterr().out


def test_env_backups_create_empty_environment_reports_config_only(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """An environment with no eligible deployments yields a config-only snapshot (FR-011)."""
    _seed_environment(mock_client)
    mock_client.environment_backups.create = AsyncMock(
        return_value=_make_environment_backup(status=EnvironmentBackupStatus.COMPLETED, constituents=[])
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "create", "prod"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "0/0/0" in output
    assert "config-only snapshot" in output


def test_env_backups_create_reports_constituent_error(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """A constituent that failed at creation is attributed, not swallowed (FR-005)."""
    _seed_environment(mock_client)
    mock_client.environment_backups.create = AsyncMock(
        return_value=_make_environment_backup(
            constituents=[
                _make_constituent(deployment_name="demo"),
                _make_constituent(deployment_name="other", backup_status=None, error="A backup is already in progress"),
            ]
        )
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "create", "prod"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "1/1/2" in output
    assert "other" in output
    assert "A backup is already in progress" in output


def test_env_backups_create_wait_completed(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_environment(mock_client)
    mock_client.environment_backups.create = AsyncMock(return_value=_make_environment_backup())
    mock_client.environment_backups.wait_for_backup = AsyncMock(
        return_value=_make_environment_backup(status=EnvironmentBackupStatus.COMPLETED)
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "create", "prod", "--wait", "--max-wait", "30", "--interval", "1"])
    assert exc.value.code == 0
    mock_client.environment_backups.wait_for_backup.assert_called_once_with(ENV_BACKUP_UUID, max_wait=30, interval=1)
    assert "Environment backup completed" in capsys.readouterr().out


def test_env_backups_create_wait_partial_exits_nonzero(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """PARTIAL is terminal and restorable, but not "everything worked" — exit non-zero."""
    _seed_environment(mock_client)
    mock_client.environment_backups.create = AsyncMock(return_value=_make_environment_backup())
    mock_client.environment_backups.wait_for_backup = AsyncMock(
        return_value=_make_environment_backup(
            status=EnvironmentBackupStatus.PARTIAL,
            constituents=[
                _make_constituent(deployment_name="demo"),
                _make_constituent(deployment_name="other", backup_status="failed"),
            ],
        )
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "create", "prod", "--wait"])
    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "PARTIAL" in output
    assert "other" in output


def test_env_backups_create_wait_failed_exits_nonzero(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_environment(mock_client)
    mock_client.environment_backups.create = AsyncMock(return_value=_make_environment_backup())
    mock_client.environment_backups.wait_for_backup = AsyncMock(
        return_value=_make_environment_backup(status=EnvironmentBackupStatus.FAILED)
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "create", "prod", "--wait"])
    assert exc.value.code == 1
    assert "FAILED" in capsys.readouterr().out


def test_env_backups_create_api_error(mock_client: MagicMock) -> None:
    _seed_environment(mock_client)
    mock_client.environment_backups.create = AsyncMock(side_effect=StyrminError("API error"))

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "create", "prod"])
    assert exc.value.code == 1


# --- get ------------------------------------------------------------------


def test_env_backups_get(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.environment_backups.get = AsyncMock(
        return_value=_make_environment_backup(
            status=EnvironmentBackupStatus.PARTIAL,
            constituents=[
                _make_constituent(deployment_name="demo"),
                _make_constituent(deployment_name="broken", backup_status=None, error="boom"),
                _make_constituent(deployment_name="gone", backup_status=None),
            ],
        )
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "get", ENV_BACKUP_UUID])
    assert exc.value.code == 0
    mock_client.environment_backups.get.assert_called_once_with(ENV_BACKUP_UUID)
    output = capsys.readouterr().out
    assert "PARTIAL" in output
    assert "demo" in output
    assert "failed: boom" in output
    # A constituent deleted after the snapshot leaves a visible gap (US3).
    assert "gone: deleted" in output


def test_env_backups_get_rejects_non_uuid(mock_client: MagicMock) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "get", "not-a-uuid"])
    assert exc.value.code != 0
    mock_client.environment_backups.get.assert_not_called()


def test_env_backups_get_not_found(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.environment_backups.get = AsyncMock(
        side_effect=ResourceNotFoundError("Environment backup not found", "NOT_FOUND")
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "get", ENV_BACKUP_UUID])
    assert exc.value.code == 1
    assert "Environment backup not found" in capsys.readouterr().out


# --- list -----------------------------------------------------------------


def test_env_backups_list_by_environment_name(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Rich ellipsizes cells that do not fit; widen the console so the counts
    # column is asserted verbatim instead of truncated.
    monkeypatch.setenv("COLUMNS", "200")
    _seed_environment(mock_client)
    mock_client.environment_backups.list = AsyncMock(
        return_value=[
            _make_environment_backup(
                status=EnvironmentBackupStatus.PARTIAL,
                constituents=[
                    _make_constituent(deployment_name="demo"),
                    _make_constituent(deployment_name="other", backup_status=None, error="boom"),
                    _make_constituent(deployment_name="gone", backup_status=None),
                ],
            )
        ]
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "list", "prod"])
    assert exc.value.code == 0
    mock_client.environment_backups.list.assert_called_once_with(environment_id=ENV_UUID)
    output = capsys.readouterr().out
    assert "env-backup-1" in output
    assert "PARTIAL" in output
    # ok / failed / total — the gap shows up only in the total.
    assert "1/1/3" in output


def test_env_backups_list_by_environment_id(mock_client: MagicMock) -> None:
    mock_client.environment_backups.list = AsyncMock(return_value=[])

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "list", "--id", ENV_UUID])
    assert exc.value.code == 0
    mock_client.environments.get.assert_not_called()
    mock_client.environment_backups.list.assert_called_once_with(environment_id=ENV_UUID)


def test_env_backups_list_empty(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_environment(mock_client)
    mock_client.environment_backups.list = AsyncMock(return_value=[])

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "list", "prod"])
    assert exc.value.code == 0
    assert "No environment backups found" in capsys.readouterr().out


def test_env_backups_list_requires_a_target(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "list"])
    assert exc.value.code == 1
    mock_client.environment_backups.list.assert_not_called()
    assert "Either an environment name or --id is required" in capsys.readouterr().out
