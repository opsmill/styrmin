"""Tests for the root styrminctl app."""

from __future__ import annotations

import pytest
from styrminctl.cli import app


def test_help_output_contains_all_command_groups(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "clusters" in output
    assert "environments" in output
    assert "drivers" in output
    assert "deployments" in output
    assert "backups" in output
    assert "backup-locations" in output
    assert "tasks" in output


def test_version_output(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["--version"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "0.1.0" in output


def test_invalid_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["nonexistent"])
    assert exc.value.code != 0


def test_help_shows_install_completion(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "--install-completion" in output


def test_shell_completion_generation() -> None:
    for shell in ("bash", "zsh", "fish"):
        script = app.generate_completion(shell=shell)
        assert script, f"Completion script for {shell} should not be empty"
