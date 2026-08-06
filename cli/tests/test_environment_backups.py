"""Tests for the env-backups command group."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from styrmin_sdk import EnvironmentBackupStatus, EnvironmentRestoreStatus
from styrmin_sdk.exceptions import OperationFailedError, ResourceNotFoundError, StyrminError
from styrminctl.cli import app

ENV_UUID = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
ENV_BACKUP_UUID = "c3d4e5f6-a7b8-9012-cdef-123456789012"
ENV_RESTORE_UUID = "f6a7b8c9-d0e1-2345-f012-3456789abcde"
CLUSTER_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
BACKUP_UUID = "d4e5f6a7-b8c9-0123-def0-123456789abc"
RESTORE_UUID = "a7b8c9d0-e1f2-3456-0123-456789abcdef"
DEPLOYMENT_UUID = "e5f6a7b8-c9d0-1234-ef01-23456789abcd"


def _make_constituent(
    *,
    deployment_name: str,
    backup_status: str | None = "completed",
    error: str | None = None,
    backup_error_message: str | None = None,
) -> MagicMock:
    """Build a per-constituent outcome: a backup, a creation error, or a gap (neither).

    ``error`` is the snapshot-level "never got a row" reason (FR-005);
    ``backup_error_message`` is the constituent backup's own failure reason,
    which only exists once the row does. Both are set explicitly so an
    auto-created ``MagicMock`` attribute can never masquerade as a real value.
    """
    backup = (
        MagicMock(id=BACKUP_UUID, status=backup_status, error_message=backup_error_message)
        if backup_status is not None
        else None
    )
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


def _make_restore(
    *, name: str = "demo-restore", status: str = "pending", error_message: str | None = None
) -> MagicMock:
    restore = MagicMock(id=RESTORE_UUID, status=status, error_message=error_message)
    restore.name = name
    return restore


def _make_skipped(*, deployment_name: str, reason: str) -> MagicMock:
    skipped = MagicMock(deployment_id=DEPLOYMENT_UUID, reason=reason)
    skipped.deployment_name = deployment_name
    return skipped


def _make_environment_restore(
    *,
    status: EnvironmentRestoreStatus = EnvironmentRestoreStatus.PENDING,
    restores: list[MagicMock] | None = None,
    skipped_constituents: list[MagicMock] | None = None,
) -> MagicMock:
    return MagicMock(
        id=ENV_RESTORE_UUID,
        status=status,
        environment_backup_id=ENV_BACKUP_UUID,
        created_on="2026-01-01T00:00:00",
        restores=restores if restores is not None else [_make_restore()],
        skipped_constituents=skipped_constituents if skipped_constituents is not None else [],
    )


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
    assert "delete" in output
    assert "restore" in output
    assert "restore-get" in output
    assert "restore-list" in output


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


def test_env_backups_create_already_failed_exits_nonzero(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """The derived status is synchronous: an all-failed fan-out returns FAILED already.

    Printing "Success" and exiting 0 there would tell a script that a backup it
    does not have was taken.
    """
    _seed_environment(mock_client)
    mock_client.environment_backups.create = AsyncMock(
        return_value=_make_environment_backup(
            status=EnvironmentBackupStatus.FAILED,
            constituents=[
                _make_constituent(deployment_name="demo", backup_status=None, error="A backup is already in progress")
            ],
        )
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "create", "prod"])
    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "Success" not in output
    assert "FAILED" in output
    assert "A backup is already in progress" in output
    # Nothing was polled: FAILED is terminal already.
    mock_client.environment_backups.wait_for_backup.assert_not_called()


def test_env_backups_create_already_partial_exits_nonzero(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """PARTIAL is terminal too, and the counts must not contradict it."""
    # Rich wraps at the terminal width; widen it so the printed reason is
    # asserted verbatim rather than split across lines.
    monkeypatch.setenv("COLUMNS", "200")
    _seed_environment(mock_client)
    mock_client.environment_backups.create = AsyncMock(
        return_value=_make_environment_backup(
            status=EnvironmentBackupStatus.PARTIAL,
            constituents=[
                _make_constituent(deployment_name="demo"),
                _make_constituent(
                    deployment_name="other",
                    backup_status="failed",
                    backup_error_message="velero exploded",
                ),
            ],
        )
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "create", "prod"])
    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "Success" not in output
    assert "PARTIAL" in output
    # ok counts completed backups only — a failed row is not an ok constituent.
    assert "1/0/2" in output
    # The constituent's own failure reason is printed, not just "(failed)".
    assert "velero exploded" in output


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
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """PARTIAL is terminal and restorable, but not "everything worked" — exit non-zero."""
    monkeypatch.setenv("COLUMNS", "200")
    _seed_environment(mock_client)
    mock_client.environment_backups.create = AsyncMock(return_value=_make_environment_backup())
    mock_client.environment_backups.wait_for_backup = AsyncMock(
        return_value=_make_environment_backup(
            status=EnvironmentBackupStatus.PARTIAL,
            constituents=[
                _make_constituent(deployment_name="demo"),
                _make_constituent(
                    deployment_name="other",
                    backup_status="failed",
                    backup_error_message="velero backup partially failed",
                ),
            ],
        )
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "create", "prod", "--wait"])
    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "PARTIAL" in output
    assert "other" in output
    # README promise: --wait prints the reason for every constituent that did
    # not complete, and a constituent that failed after its row existed carries
    # that reason on the backup itself.
    assert "velero backup partially failed" in output


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


# --- delete ---------------------------------------------------------------


def test_env_backups_delete(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.environment_backups.delete = AsyncMock(return_value=None)

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "delete", ENV_BACKUP_UUID])
    assert exc.value.code == 0
    mock_client.environment_backups.delete.assert_called_once_with(ENV_BACKUP_UUID)
    assert "deleted" in capsys.readouterr().out


def test_env_backups_delete_rejects_non_uuid(mock_client: MagicMock) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "delete", "not-a-uuid"])
    assert exc.value.code != 0
    mock_client.environment_backups.delete.assert_not_called()


def test_env_backups_delete_not_found(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.environment_backups.delete = AsyncMock(
        side_effect=ResourceNotFoundError("Environment backup not found", "NOT_FOUND")
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "delete", ENV_BACKUP_UUID])
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


# --- restore --------------------------------------------------------------


def test_env_backups_restore(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.environment_backups.restore = AsyncMock(
        return_value=_make_environment_restore(status=EnvironmentRestoreStatus.IN_PROGRESS)
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "restore", ENV_BACKUP_UUID])
    assert exc.value.code == 0
    mock_client.environment_backups.restore.assert_called_once_with(ENV_BACKUP_UUID)
    output = capsys.readouterr().out
    assert "IN_PROGRESS" in output
    assert "demo-restore" in output
    assert "Skipped constituents: none" in output


def test_env_backups_restore_prints_every_skip_with_a_reason(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-007 / SC-004: every non-restored constituent is attributed by name and reason."""
    mock_client.environment_backups.restore = AsyncMock(
        return_value=_make_environment_restore(
            status=EnvironmentRestoreStatus.IN_PROGRESS,
            skipped_constituents=[
                _make_skipped(deployment_name="stale", reason="backup expired"),
                _make_skipped(deployment_name="gone", reason="deployment no longer exists"),
                _make_skipped(deployment_name="busy", reason="deployment busy with another restore"),
            ],
        )
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "restore", ENV_BACKUP_UUID])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "skipped: 3" in output
    # Reasons are free text from the backend and are printed verbatim.
    assert "stale: backup expired" in output
    assert "gone: deployment no longer exists" in output
    assert "busy: deployment busy with another restore" in output


def test_env_backups_restore_already_failed_exits_nonzero(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """A restore where every constituent was skipped comes back FAILED immediately."""
    mock_client.environment_backups.restore = AsyncMock(
        return_value=_make_environment_restore(
            status=EnvironmentRestoreStatus.FAILED,
            restores=[],
            skipped_constituents=[_make_skipped(deployment_name="stale", reason="backup expired")],
        )
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "restore", ENV_BACKUP_UUID])
    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "Success" not in output
    assert "FAILED" in output
    assert "stale: backup expired" in output
    mock_client.environment_backups.wait_for_restore.assert_not_called()


def test_env_backups_restore_rejects_non_uuid(mock_client: MagicMock) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "restore", "not-a-uuid"])
    assert exc.value.code != 0
    mock_client.environment_backups.restore.assert_not_called()


def test_env_backups_restore_not_restorable(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    """A snapshot whose derived status is not COMPLETED/PARTIAL is refused, with the reason shown."""
    mock_client.environment_backups.restore = AsyncMock(
        side_effect=OperationFailedError("Environment backup is not restorable", "OPERATION_DENIED")
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "restore", ENV_BACKUP_UUID])
    assert exc.value.code == 1
    assert "not restorable" in capsys.readouterr().out


def test_env_backups_restore_wait_completed(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.environment_backups.restore = AsyncMock(return_value=_make_environment_restore())
    mock_client.environment_backups.wait_for_restore = AsyncMock(
        return_value=_make_environment_restore(status=EnvironmentRestoreStatus.COMPLETED)
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "restore", ENV_BACKUP_UUID, "--wait", "--max-wait", "30", "--interval", "1"])
    assert exc.value.code == 0
    mock_client.environment_backups.wait_for_restore.assert_called_once_with(ENV_RESTORE_UUID, max_wait=30, interval=1)
    assert "Environment restore completed" in capsys.readouterr().out


def test_env_backups_restore_wait_partial_exits_nonzero(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """PARTIAL is terminal, but not "everything restored" — exit non-zero, same as backup --wait."""
    mock_client.environment_backups.restore = AsyncMock(return_value=_make_environment_restore())
    mock_client.environment_backups.wait_for_restore = AsyncMock(
        return_value=_make_environment_restore(
            status=EnvironmentRestoreStatus.PARTIAL,
            restores=[_make_restore(name="ok-restore", status="completed")],
            skipped_constituents=[_make_skipped(deployment_name="gone", reason="deployment no longer exists")],
        )
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "restore", ENV_BACKUP_UUID, "--wait"])
    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "PARTIAL" in output
    assert "gone: deployment no longer exists" in output


def test_env_backups_restore_wait_failed_exits_nonzero(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    mock_client.environment_backups.restore = AsyncMock(return_value=_make_environment_restore())
    mock_client.environment_backups.wait_for_restore = AsyncMock(
        return_value=_make_environment_restore(
            status=EnvironmentRestoreStatus.FAILED,
            restores=[],
            skipped_constituents=[_make_skipped(deployment_name="demo", reason="backup not completed")],
        )
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "restore", ENV_BACKUP_UUID, "--wait"])
    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "FAILED" in output
    assert "Restored constituents: none" in output
    assert "demo: backup not completed" in output


# --- restore-get ----------------------------------------------------------


def test_env_backups_restore_get(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.environment_backups.get_restore = AsyncMock(
        return_value=_make_environment_restore(
            status=EnvironmentRestoreStatus.PARTIAL,
            restores=[
                _make_restore(name="ok-restore", status="completed"),
                _make_restore(name="bad-restore", status="failed", error_message="velero exploded"),
            ],
            skipped_constituents=[_make_skipped(deployment_name="gone", reason="backup deleted")],
        )
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "restore-get", ENV_RESTORE_UUID])
    assert exc.value.code == 0
    mock_client.environment_backups.get_restore.assert_called_once_with(ENV_RESTORE_UUID)
    output = capsys.readouterr().out
    assert "PARTIAL" in output
    assert "ok-restore" in output
    assert "velero exploded" in output
    assert "gone: backup deleted" in output


def test_env_backups_restore_get_rejects_non_uuid(mock_client: MagicMock) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "restore-get", "not-a-uuid"])
    assert exc.value.code != 0
    mock_client.environment_backups.get_restore.assert_not_called()


def test_env_backups_restore_get_not_found(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.environment_backups.get_restore = AsyncMock(
        side_effect=ResourceNotFoundError("Environment restore not found", "NOT_FOUND")
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "restore-get", ENV_RESTORE_UUID])
    assert exc.value.code == 1
    assert "Environment restore not found" in capsys.readouterr().out


# --- restore-list ---------------------------------------------------------


def test_env_backups_restore_list(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    mock_client.environment_backups.list_restores = AsyncMock(
        return_value=[
            _make_environment_restore(
                status=EnvironmentRestoreStatus.PARTIAL,
                restores=[_make_restore(status="completed")],
                skipped_constituents=[
                    _make_skipped(deployment_name="gone", reason="deployment no longer exists"),
                    _make_skipped(deployment_name="stale", reason="backup expired"),
                ],
            )
        ]
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "restore-list", ENV_BACKUP_UUID])
    assert exc.value.code == 0
    mock_client.environment_backups.list_restores.assert_called_once_with(ENV_BACKUP_UUID)
    output = capsys.readouterr().out
    assert ENV_RESTORE_UUID in output
    assert "PARTIAL" in output


def test_env_backups_restore_list_empty(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.environment_backups.list_restores = AsyncMock(return_value=[])

    with pytest.raises(SystemExit) as exc:
        app(["env-backups", "restore-list", ENV_BACKUP_UUID])
    assert exc.value.code == 0
    assert "No environment restores found" in capsys.readouterr().out
