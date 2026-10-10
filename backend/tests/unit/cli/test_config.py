"""Tests for the configuration management commands."""

from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError
from pytest_mock import MockerFixture

from styrmin_backend import config
from styrmin_backend.cli.config_cmd import config_app
from styrmin_backend.config import (
    ConfiguredSettings,
    DatabaseSettings,
    DriverSettings,
    KubernetesConfigMode,
    KubernetesSettings,
    RemoteAgentCodeSettings,
    Settings,
    TelemetrySettings,
    WorkflowDriver,
    WorkflowSettings,
)
from styrmin_backend.db.constants import DatabaseType


def test_config_show_help(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that config show --help shows expected options."""
    with pytest.raises(SystemExit) as exc_info:
        config_app(["show", "--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "--format" in output


def test_config_validate_help(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that config validate --help shows expected options."""
    with pytest.raises(SystemExit) as exc_info:
        config_app(["validate", "--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "CONFIG-FILE" in output or "config-file" in output.lower()


def test_config_show_outputs_toml_by_default(
    capsys: pytest.CaptureFixture[str], mocker: MockerFixture
) -> None:
    """Test that config show outputs TOML format by default."""
    # Mock config.SETTINGS
    mock_config = mocker.patch("styrmin_backend.cli.config_cmd.config")
    mock_config.SETTINGS.active_settings.model_dump.return_value = {
        "database": {"db_type": "sqlite", "db_name": "test.db"}
    }

    # Cyclopts calls sys.exit(0) after successful command
    with pytest.raises(SystemExit) as exc_info:
        config_app(["show"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out

    # TOML format should have section headers and key = value pairs
    assert "[database]" in output
    assert "db_type" in output
    assert "sqlite" in output


def test_config_show_json_format(
    capsys: pytest.CaptureFixture[str], mocker: MockerFixture
) -> None:
    """Test that config show --format json outputs JSON."""
    # Mock config.SETTINGS
    mock_config = mocker.patch("styrmin_backend.cli.config_cmd.config")
    mock_config.SETTINGS.active_settings.model_dump.return_value = {
        "database": {"db_type": "sqlite"}
    }

    with pytest.raises(SystemExit) as exc_info:
        config_app(["show", "--format", "json"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out

    # JSON format should have braces
    assert "{" in output
    assert "}" in output
    assert '"database"' in output


def test_config_validate_valid_file(
    capsys: pytest.CaptureFixture[str], mocker: MockerFixture
) -> None:
    """Test that config validate returns exit code 0 for valid config."""
    # Mock config.load to succeed
    mock_config = mocker.patch("styrmin_backend.cli.config_cmd.config")

    with pytest.raises(SystemExit) as exc_info:
        config_app(["validate", "styrmin.toml"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out

    mock_config.load.assert_called_once_with(config_file_name="styrmin.toml")
    assert "Configuration is valid" in output


def test_config_validate_invalid_file(
    capsys: pytest.CaptureFixture[str], mocker: MockerFixture
) -> None:
    """Test that config validate returns exit code 2 for invalid config."""

    # Create a real ValidationError using a pydantic model
    class TestModel(BaseModel):
        db_type: int  # Wrong type to force error

    # Create a real ValidationError
    with pytest.raises(ValidationError) as validation_exc:
        TestModel(db_type="not_an_int")  # type: ignore[arg-type]

    mock_config = mocker.patch("styrmin_backend.cli.config_cmd.config")
    mock_config.load.side_effect = validation_exc.value

    with pytest.raises(SystemExit) as exit_exc:
        config_app(["validate", "invalid.toml"])

    assert exit_exc.value.code == 2
    output = capsys.readouterr().out
    assert "not valid" in output


def test_config_validate_file_not_found(
    capsys: pytest.CaptureFixture[str], mocker: MockerFixture
) -> None:
    """Test that config validate returns exit code 2 for missing file."""
    # Mock config.load to raise FileNotFoundError
    mock_config = mocker.patch("styrmin_backend.cli.config_cmd.config")
    mock_config.load.side_effect = FileNotFoundError("File not found")

    with pytest.raises(SystemExit) as exc_info:
        config_app(["validate", "missing.toml"])

    assert exc_info.value.code == 2
    output = capsys.readouterr().out
    assert "not found" in output


def test_config_show_output_loads_back_as_a_config_file(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Aliased fields and enums are written in a form that styrmin.toml accepts."""
    settings = Settings(
        session_cookie_secure=False,
        database=DatabaseSettings(db_type=DatabaseType.POSTGRES, db_host="db.example"),
        workflow=WorkflowSettings(driver=WorkflowDriver.LOCAL),
        kubernetes=KubernetesSettings(config_mode=KubernetesConfigMode.KUBECONFIG),
    )
    monkeypatch.setattr(config, "SETTINGS", ConfiguredSettings(settings=settings))

    with pytest.raises(SystemExit):
        config_app(["show"])
    path = tmp_path / "styrmin.toml"
    path.write_text(capsys.readouterr().out, encoding="utf-8")

    assert config.load(str(path)) == settings


@pytest.mark.parametrize("output_format", ["toml", "json"])
def test_config_show_leaves_out_credentials(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    output_format: str,
) -> None:
    settings = Settings(
        admin_password="s3cret-admin",
        database=DatabaseSettings(
            db_password="s3cret-db", db_url="postgresql://u:s3cret-url@db/styrmin"
        ),
        kubernetes=KubernetesSettings(token="s3cret-k8s"),
        driver=DriverSettings(token="s3cret-driver"),
        agent_code=RemoteAgentCodeSettings(token="s3cret-agent-code"),
    )
    monkeypatch.setattr(config, "SETTINGS", ConfiguredSettings(settings=settings))

    with pytest.raises(SystemExit):
        config_app(["show", "--format", output_format])
    output = capsys.readouterr().out

    assert "s3cret" not in output
    assert "db_host" in output


def test_saved_config_show_output_reads_credentials_from_env(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = Settings(database=DatabaseSettings(db_password="stale"))
    monkeypatch.setattr(config, "SETTINGS", ConfiguredSettings(settings=settings))

    with pytest.raises(SystemExit):
        config_app(["show"])
    path = tmp_path / "styrmin.toml"
    path.write_text(capsys.readouterr().out, encoding="utf-8")
    monkeypatch.setenv("STYRMIN_DB_PASSWORD", "rotated")

    assert config.load(str(path)).database.db_password == "rotated"


@pytest.mark.parametrize("name", ["DO_NOT_TRACK", "STYRMIN_TELEMETRY"])
def test_config_show_prints_telemetry_off_when_an_environment_variable_turns_it_off(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    monkeypatch.setenv(name, "1" if name == "DO_NOT_TRACK" else "0")
    settings = Settings(telemetry=TelemetrySettings())
    monkeypatch.setattr(config, "SETTINGS", ConfiguredSettings(settings=settings))

    with pytest.raises(SystemExit):
        config_app(["show", "--format", "json"])
    output = capsys.readouterr().out

    assert '"enabled": false' in output
    assert "do_not_track" not in output
    assert "styrmin_telemetry" not in output
