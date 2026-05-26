"""Tests for the server management commands."""

import pytest
from pytest_mock import MockerFixture

from styrmin_backend.cli.server import server_app


def test_server_start_help_shows_options(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that server start --help shows all expected options."""
    with pytest.raises(SystemExit) as exc_info:
        server_app(["start", "--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out

    # Verify all options are documented
    assert "--host" in output
    assert "--port" in output
    assert "--workers" in output
    assert "--reload" in output
    assert "--config" in output


def test_server_start_accepts_host_option(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that server start accepts --host option."""
    with pytest.raises(SystemExit) as exc_info:
        server_app(["start", "--help"])

    assert exc_info.value.code == 0
    assert "--host" in capsys.readouterr().out


def test_server_start_accepts_port_option(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that server start accepts --port option."""
    with pytest.raises(SystemExit) as exc_info:
        server_app(["start", "--help"])

    assert exc_info.value.code == 0
    assert "--port" in capsys.readouterr().out


def test_server_start_invokes_uvicorn_with_defaults(mocker: MockerFixture) -> None:
    """Test that server start invokes uvicorn with default parameters."""
    mock_uvicorn = mocker.patch("styrmin_backend.cli.server.uvicorn")
    mock_config = mocker.patch("styrmin_backend.cli.server.config")

    with pytest.raises(SystemExit) as exc_info:
        server_app(["start"])

    assert exc_info.value.code == 0
    mock_config.SETTINGS.initialize.assert_called_once_with()
    mock_uvicorn.run.assert_called_once_with(
        "styrmin_backend.server.app:app",
        host="",
        port=8000,
        workers=1,
        reload=False,
    )


def test_server_start_invokes_uvicorn_with_custom_options(
    mocker: MockerFixture,
) -> None:
    """Test that server start passes custom options to uvicorn."""
    mock_uvicorn = mocker.patch("styrmin_backend.cli.server.uvicorn")
    mocker.patch("styrmin_backend.cli.server.config")

    with pytest.raises(SystemExit) as exc_info:
        server_app(["start", "--host", "127.0.0.1", "--port", "9000", "--workers", "4"])

    assert exc_info.value.code == 0
    mock_uvicorn.run.assert_called_once_with(
        "styrmin_backend.server.app:app",
        host="127.0.0.1",
        port=9000,
        workers=4,
        reload=False,
    )


def test_server_start_with_reload_uses_single_worker(mocker: MockerFixture) -> None:
    """Test that server start with --reload uses 1 worker regardless of --workers."""
    mock_uvicorn = mocker.patch("styrmin_backend.cli.server.uvicorn")
    mocker.patch("styrmin_backend.cli.server.config")

    with pytest.raises(SystemExit) as exc_info:
        server_app(["start", "--reload", "--workers", "4"])

    assert exc_info.value.code == 0
    mock_uvicorn.run.assert_called_once_with(
        "styrmin_backend.server.app:app",
        host="",
        port=8000,
        workers=1,  # Should be 1 when reload is enabled
        reload=True,
    )


def test_server_start_with_config_file(mocker: MockerFixture) -> None:
    """Test that server start loads config from specified file."""
    mocker.patch("styrmin_backend.cli.server.uvicorn")
    mock_config = mocker.patch("styrmin_backend.cli.server.config")

    config_path = "/path/to/config.toml"
    with pytest.raises(SystemExit) as exc_info:
        server_app(["start", "--config-file", config_path])

    assert exc_info.value.code == 0
    mock_config.SETTINGS.initialize.assert_called_once_with(config_path)
