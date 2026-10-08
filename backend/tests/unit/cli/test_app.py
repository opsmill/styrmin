"""Tests for the main Styrmin CLI application."""

import pytest

from styrmin_backend.cli.app import app


def test_help_output_contains_all_command_groups(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that --help output contains all command groups."""
    with pytest.raises(SystemExit) as exc:
        app(["--help"])

    assert exc.value.code == 0
    output = capsys.readouterr().out

    # Verify all command groups are present
    assert "server" in output
    assert "db" in output
    assert "config" in output
    assert "export" in output
    assert "telemetry" in output

    # Verify help descriptions are present
    assert "Server management commands" in output
    assert "Database management commands" in output
    assert "Configuration management commands" in output
    assert "Export commands" in output
    assert "Telemetry commands" in output


def test_version_output_shows_package_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that --version output shows the package version."""
    with pytest.raises(SystemExit) as exc_info:
        app(["--version"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out.strip()

    # Verify version format (semver-like)
    assert output, "Version output should not be empty"
    parts = output.split(".")
    assert len(parts) >= 2, (
        f"Version should have at least major.minor format, got: {output}"
    )


def test_help_flag_short_form(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that -h works as alias for --help."""
    with pytest.raises(SystemExit) as exc_info:
        app(["-h"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out

    # Should show the same help as --help
    assert "server" in output
    assert "Styrmin server management CLI" in output
