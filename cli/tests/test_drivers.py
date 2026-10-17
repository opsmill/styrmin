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
        repository_url="https://github.com/example/driver.git", branch="main", driver_directory=None
    )
    output = capsys.readouterr().out
    assert "1.0.0" in output


def test_drivers_load_version_with_driver_directory(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    """Spec 028 / US1: --driver-directory reaches the SDK and the output names the driver directory."""
    mock_version = MagicMock(
        id="v-1",
        version="1.0.0",
        application_driver_id="d-1",
        supported_versions=">=14",
        content_hash=None,
        source_commit_sha="def4567890abcdef1234567890abcdef12345678",
        source_repository="https://github.com/example/drivers.git",
        source_branch="main",
        source_path="drivers/a",
        load_warnings=[],
        component_configs=[],
        actions=[],
        helm_chart=None,
    )
    mock_client.drivers.load_version = AsyncMock(return_value=mock_version)

    with pytest.raises(SystemExit) as exc:
        app(
            [
                "drivers",
                "load-version",
                "https://github.com/example/drivers.git",
                "main",
                "--driver-directory",
                "drivers/a",
            ]
        )
    assert exc.value.code == 0
    mock_client.drivers.load_version.assert_called_once_with(
        repository_url="https://github.com/example/drivers.git", branch="main", driver_directory="drivers/a"
    )
    output = capsys.readouterr().out
    assert "Driver directory: drivers/a" in output
    assert output.index("Commit SHA:") < output.index("Driver directory:")


def test_drivers_load_version_help_lists_driver_directory(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["drivers", "load-version", "--help"])
    assert exc.value.code == 0
    assert "--driver-directory" in capsys.readouterr().out


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


def test_drivers_load_local_version_renders_label_and_full_content_hash(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Spec 013 / US4: local driver detail renders <version>@<short> and the full Content hash line."""
    full_hash = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"
    mock_version = MagicMock(
        id="v-2",
        version="2.0.0",
        application_driver_id="d-1",
        supported_versions=">=14",
        content_hash=full_hash,
        source_commit_sha=None,
        component_configs=[],
        actions=[],
        helm_chart=None,
    )
    mock_client.drivers.load_local_version = AsyncMock(return_value=mock_version)

    with pytest.raises(SystemExit) as exc:
        app(["drivers", "load-local-version", str(tmp_path)])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    # T040: label rendered with @<short>
    assert "2.0.0@a1b2c3d" in output
    # T041: full fingerprint exposed on detail
    assert f"Content hash: {full_hash}" in output
    assert "Commit SHA:" not in output


def test_drivers_load_version_renders_label_and_full_commit_sha(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec 013 / US4: git driver detail renders <version>@<short> and the full Commit SHA line."""
    full_sha = "def4567890abcdef1234567890abcdef12345678"
    mock_version = MagicMock(
        id="v-1",
        version="1.0.0",
        application_driver_id="d-1",
        supported_versions=">=14",
        content_hash=None,
        source_commit_sha=full_sha,
        source_repository="https://github.com/example/driver.git",
        source_path=None,
        component_configs=[],
        actions=[],
        helm_chart=None,
    )
    mock_client.drivers.load_version = AsyncMock(return_value=mock_version)

    with pytest.raises(SystemExit) as exc:
        app(["drivers", "load-version", "https://github.com/example/driver.git", "main"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    # T040: label rendered with @<short>
    assert "1.0.0@def4567" in output
    # T041: full fingerprint exposed on detail
    assert f"Commit SHA: {full_sha}" in output
    assert "Content hash:" not in output
    assert "Driver directory:" not in output


def test_drivers_load_local_version_prints_load_warnings(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Spec 020: a value of spec.info that the load left out is printed as a warning."""
    warning = (
        "spec.info.links[0].url must be an absolute http or https URL, such as "
        "https://example.com/docs (found 'xxxx'). The link was not stored."
    )
    mock_version = MagicMock(
        id="v-2",
        version="2.0.0",
        application_driver_id="d-1",
        supported_versions=">=14",
        content_hash=None,
        source_commit_sha=None,
        load_warnings=[warning],
        component_configs=[],
        actions=[],
        helm_chart=None,
    )
    mock_client.drivers.load_local_version = AsyncMock(return_value=mock_version)

    with pytest.raises(SystemExit) as exc:
        app(["drivers", "load-local-version", str(tmp_path)])
    assert exc.value.code == 0
    output = " ".join(capsys.readouterr().out.split())
    assert f"Warning: {warning}" in output
