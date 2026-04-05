"""Tests for the database management commands."""

import pytest
from pytest_mock import MockerFixture

from styrmin_backend.cli.db import db_app


def test_db_init_help_shows_options(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that db init --help shows expected options."""
    with pytest.raises(SystemExit) as exc_info:
        db_app(["init", "--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "--config-file" in output or "CONFIG-FILE" in output


def test_db_commands_available(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that all db commands are available."""
    with pytest.raises(SystemExit) as exc_info:
        db_app(["--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "init" in output
    assert "migrate" in output
    assert "downgrade" in output
    assert "status" in output
    assert "stamp" in output


def test_db_init_calls_alembic_upgrade(mocker: MockerFixture) -> None:
    """Test that db init calls alembic upgrade to head."""
    mock_upgrade = mocker.patch("styrmin_backend.cli.db.alembic_command.upgrade")
    mock_config = mocker.patch("styrmin_backend.cli.db.config")
    mocker.patch("styrmin_backend.cli.db._get_alembic_config")

    with pytest.raises(SystemExit) as exc_info:
        db_app(["init"])

    assert exc_info.value.code == 0
    mock_config.SETTINGS.initialize.assert_called_once_with()
    mock_upgrade.assert_called_once()
    assert mock_upgrade.call_args[0][1] == "head"


def test_db_init_with_config_file(mocker: MockerFixture) -> None:
    """Test that db init loads config from specified file."""
    mock_upgrade = mocker.patch("styrmin_backend.cli.db.alembic_command.upgrade")
    mock_config = mocker.patch("styrmin_backend.cli.db.config")
    mocker.patch("styrmin_backend.cli.db._get_alembic_config")

    config_path = "/path/to/config.toml"
    with pytest.raises(SystemExit) as exc_info:
        db_app(["init", "--config-file", config_path])

    assert exc_info.value.code == 0
    mock_config.SETTINGS.initialize.assert_called_once_with(config_path)
    mock_upgrade.assert_called_once()
    assert mock_upgrade.call_args[0][1] == "head"


def test_db_init_handles_error(
    capsys: pytest.CaptureFixture[str], mocker: MockerFixture
) -> None:
    """Test that db init returns exit code 1 on error."""
    mock_upgrade = mocker.patch("styrmin_backend.cli.db.alembic_command.upgrade")
    mock_upgrade.side_effect = Exception("Database connection failed")
    mocker.patch("styrmin_backend.cli.db.config")
    mocker.patch("styrmin_backend.cli.db._get_alembic_config")

    with pytest.raises(SystemExit) as exc_info:
        db_app(["init"])

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "Failed to initialize database" in output


def test_db_migrate_calls_alembic_upgrade(mocker: MockerFixture) -> None:
    """Test that db migrate calls alembic upgrade to head."""
    mock_upgrade = mocker.patch("styrmin_backend.cli.db.alembic_command.upgrade")
    mock_config = mocker.patch("styrmin_backend.cli.db.config")
    mocker.patch("styrmin_backend.cli.db._get_alembic_config")

    with pytest.raises(SystemExit) as exc_info:
        db_app(["migrate"])

    assert exc_info.value.code == 0
    mock_config.SETTINGS.initialize.assert_called_once_with()
    mock_upgrade.assert_called_once()
    assert mock_upgrade.call_args[0][1] == "head"


def test_db_migrate_handles_error(
    capsys: pytest.CaptureFixture[str], mocker: MockerFixture
) -> None:
    """Test that db migrate returns exit code 1 on error."""
    mock_upgrade = mocker.patch("styrmin_backend.cli.db.alembic_command.upgrade")
    mock_upgrade.side_effect = Exception("Migration failed")
    mocker.patch("styrmin_backend.cli.db.config")
    mocker.patch("styrmin_backend.cli.db._get_alembic_config")

    with pytest.raises(SystemExit) as exc_info:
        db_app(["migrate"])

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "Migration failed" in output


def test_db_downgrade_calls_alembic_downgrade(mocker: MockerFixture) -> None:
    """Test that db downgrade calls alembic downgrade -1."""
    mock_downgrade = mocker.patch("styrmin_backend.cli.db.alembic_command.downgrade")
    mock_config = mocker.patch("styrmin_backend.cli.db.config")
    mocker.patch("styrmin_backend.cli.db._get_alembic_config")

    with pytest.raises(SystemExit) as exc_info:
        db_app(["downgrade"])

    assert exc_info.value.code == 0
    mock_config.SETTINGS.initialize.assert_called_once_with()
    mock_downgrade.assert_called_once()
    assert mock_downgrade.call_args[0][1] == "-1"


def test_db_downgrade_handles_error(
    capsys: pytest.CaptureFixture[str], mocker: MockerFixture
) -> None:
    """Test that db downgrade returns exit code 1 on error."""
    mock_downgrade = mocker.patch("styrmin_backend.cli.db.alembic_command.downgrade")
    mock_downgrade.side_effect = Exception("Downgrade failed")
    mocker.patch("styrmin_backend.cli.db.config")
    mocker.patch("styrmin_backend.cli.db._get_alembic_config")

    with pytest.raises(SystemExit) as exc_info:
        db_app(["downgrade"])

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "Downgrade failed" in output


def test_db_status_calls_alembic_current(mocker: MockerFixture) -> None:
    """Test that db status calls alembic current."""
    mock_current = mocker.patch("styrmin_backend.cli.db.alembic_command.current")
    mock_config = mocker.patch("styrmin_backend.cli.db.config")
    mocker.patch("styrmin_backend.cli.db._get_alembic_config")

    with pytest.raises(SystemExit) as exc_info:
        db_app(["status"])

    assert exc_info.value.code == 0
    mock_config.SETTINGS.initialize.assert_called_once_with()
    mock_current.assert_called_once()


def test_db_status_handles_error(
    capsys: pytest.CaptureFixture[str], mocker: MockerFixture
) -> None:
    """Test that db status returns exit code 1 on error."""
    mock_current = mocker.patch("styrmin_backend.cli.db.alembic_command.current")
    mock_current.side_effect = Exception("Status check failed")
    mocker.patch("styrmin_backend.cli.db.config")
    mocker.patch("styrmin_backend.cli.db._get_alembic_config")

    with pytest.raises(SystemExit) as exc_info:
        db_app(["status"])

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "Failed to get migration status" in output


def test_db_stamp_calls_alembic_stamp(mocker: MockerFixture) -> None:
    """Test that db stamp calls alembic stamp head."""
    mock_stamp = mocker.patch("styrmin_backend.cli.db.alembic_command.stamp")
    mock_config = mocker.patch("styrmin_backend.cli.db.config")
    mocker.patch("styrmin_backend.cli.db._get_alembic_config")

    with pytest.raises(SystemExit) as exc_info:
        db_app(["stamp"])

    assert exc_info.value.code == 0
    mock_config.SETTINGS.initialize.assert_called_once_with()
    mock_stamp.assert_called_once()


def test_db_stamp_handles_error(
    capsys: pytest.CaptureFixture[str], mocker: MockerFixture
) -> None:
    """Test that db stamp returns exit code 1 on error."""
    mock_stamp = mocker.patch("styrmin_backend.cli.db.alembic_command.stamp")
    mock_stamp.side_effect = Exception("Stamp failed")
    mocker.patch("styrmin_backend.cli.db.config")
    mocker.patch("styrmin_backend.cli.db._get_alembic_config")

    with pytest.raises(SystemExit) as exc_info:
        db_app(["stamp"])

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "Failed to stamp database" in output
