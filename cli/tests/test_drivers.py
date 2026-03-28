"""Tests for the drivers command group."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from styrmin_sdk.exceptions import StyrminError
from styrminctl.cli import app


def test_drivers_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["drivers", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "create" in output
    assert "load-version" in output
    assert "load-local-version" in output


def test_drivers_create(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_driver = MagicMock(id="d-1", name="postgres", versions=[])
    mock_client.drivers.create = AsyncMock(return_value=mock_driver)

    with pytest.raises(SystemExit) as exc:
        app(["drivers", "create", "postgres"])
    assert exc.value.code == 0
    mock_client.drivers.create.assert_called_once_with(name="postgres")
    output = capsys.readouterr().out
    assert "postgres" in output


def test_drivers_load_version(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_version = MagicMock(
        id="v-1",
        version="1.0.0",
        application_driver_id="d-1",
        supported_versions=">=14",
        component_configs=[],
        actions=[],
        helm_chart=None,
    )
    mock_client.drivers.load_version = AsyncMock(return_value=mock_version)

    with pytest.raises(SystemExit) as exc:
        app(["drivers", "load-version", "https://github.com/example/driver.git", "main"])
    assert exc.value.code == 0
    mock_client.drivers.load_version.assert_called_once_with(
        repository_url="https://github.com/example/driver.git", branch="main"
    )
    output = capsys.readouterr().out
    assert "1.0.0" in output


def test_drivers_load_local_version(mock_client: MagicMock, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    mock_version = MagicMock(
        id="v-2",
        version="2.0.0",
        application_driver_id="d-1",
        supported_versions=">=14",
        component_configs=[],
        actions=[],
        helm_chart=None,
    )
    mock_client.drivers.load_local_version = AsyncMock(return_value=mock_version)

    with pytest.raises(SystemExit) as exc:
        app(["drivers", "load-local-version", str(tmp_path)])
    assert exc.value.code == 0
    mock_client.drivers.load_local_version.assert_called_once_with(path=str(tmp_path))
    output = capsys.readouterr().out
    assert "2.0.0" in output


def test_drivers_create_error(mock_client: MagicMock) -> None:
    mock_client.drivers.create = AsyncMock(side_effect=StyrminError("API error"))

    with pytest.raises(SystemExit) as exc:
        app(["drivers", "create", "bad-driver"])
    assert exc.value.code == 1
