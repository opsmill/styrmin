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
    """Test that db command is available."""
    with pytest.raises(SystemExit) as exc_info:
        db_app(["--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "init" in output


def test_db_init_calls_init_db(mocker: MockerFixture) -> None:
    """Test that db init calls init_db from styrmin_backend.db.utils."""
    mock_init_db = mocker.patch("styrmin_backend.cli.db.init_db")
    mock_config = mocker.patch("styrmin_backend.cli.db.config")

    with pytest.raises(SystemExit) as exc_info:
        db_app(["init"])

    assert exc_info.value.code == 0
    mock_config.SETTINGS.initialize.assert_called_once_with()
    mock_init_db.assert_called_once()


def test_db_init_with_config_file(mocker: MockerFixture) -> None:
    """Test that db init loads config from specified file."""
    mock_init_db = mocker.patch("styrmin_backend.cli.db.init_db")
    mock_config = mocker.patch("styrmin_backend.cli.db.config")

    config_path = "/path/to/config.toml"
    with pytest.raises(SystemExit) as exc_info:
        db_app(["init", "--config-file", config_path])

    assert exc_info.value.code == 0
    mock_config.SETTINGS.initialize.assert_called_once_with(config_path)
    mock_init_db.assert_called_once()


def test_db_init_handles_error(
    capsys: pytest.CaptureFixture[str], mocker: MockerFixture
) -> None:
    """Test that db init returns exit code 1 on error."""
    mock_init_db = mocker.patch("styrmin_backend.cli.db.init_db")
    mock_init_db.side_effect = Exception("Database connection failed")
    mocker.patch("styrmin_backend.cli.db.config")

    with pytest.raises(SystemExit) as exc_info:
        db_app(["init"])

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "Failed to initialize database" in output
