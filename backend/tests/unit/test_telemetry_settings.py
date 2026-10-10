"""Telemetry settings and the setting that turns telemetry off (spec 020, D7)."""

import pytest

from styrmin_backend.config import (
    DEFAULT_TELEMETRY_ENDPOINT,
    Settings,
    TelemetrySettings,
    load,
)

ENABLED_OFF = "STYRMIN_TELEMETRY_ENABLED=false"
DNT_OFF = "DO_NOT_TRACK=1"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "STYRMIN_TELEMETRY_ENABLED",
        "STYRMIN_TELEMETRY_ENDPOINT",
        "STYRMIN_TELEMETRY",
        "DO_NOT_TRACK",
    ):
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_on_with_the_default_endpoint() -> None:
    settings = TelemetrySettings()

    assert settings.enabled is True
    assert settings.endpoint == DEFAULT_TELEMETRY_ENDPOINT
    assert settings.disabled_by() is None


@pytest.mark.parametrize("value", ["false", "0"])
def test_enabled_false_turns_telemetry_off(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("STYRMIN_TELEMETRY_ENABLED", value)

    assert TelemetrySettings().disabled_by() == ENABLED_OFF


def test_do_not_track_1_turns_telemetry_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DO_NOT_TRACK", "1")

    assert TelemetrySettings().disabled_by() == DNT_OFF


@pytest.mark.parametrize("value", ["true", "TRUE", "yes", "on", " 1 "])
def test_do_not_track_common_true_values_turn_telemetry_off(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("DO_NOT_TRACK", value)

    assert TelemetrySettings().disabled_by() == f"DO_NOT_TRACK={value.strip()}"


@pytest.mark.parametrize("value", ["0", "false", "no", ""])
def test_do_not_track_other_values_have_no_effect(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("DO_NOT_TRACK", value)

    assert TelemetrySettings().disabled_by() is None


@pytest.mark.parametrize("value", ["0", "false", "No", "off"])
def test_styrmin_telemetry_off_values_turn_telemetry_off(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("STYRMIN_TELEMETRY", value)

    assert TelemetrySettings().disabled_by() == f"STYRMIN_TELEMETRY={value}"


@pytest.mark.parametrize("value", ["1", "true", "", '{"enabled": false}'])
def test_styrmin_telemetry_other_values_have_no_effect(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("STYRMIN_TELEMETRY", value)

    assert TelemetrySettings().disabled_by() is None


@pytest.mark.parametrize("value", ["0", "1", "off", '{"enabled": true}'])
def test_server_settings_load_with_the_styrminctl_variable_set(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    # STYRMIN_TELEMETRY is the styrminctl opt-out; it is not the [telemetry] settings group.
    monkeypatch.setenv("STYRMIN_TELEMETRY", value)

    settings = Settings()

    assert isinstance(settings.telemetry, TelemetrySettings)
    assert settings.telemetry.endpoint == DEFAULT_TELEMETRY_ENDPOINT


def test_server_settings_ignore_a_variable_named_after_another_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STYRMIN_AGENT", "0")

    assert Settings().agent.poll_retries == 60


def test_enabled_false_is_checked_before_do_not_track(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STYRMIN_TELEMETRY_ENABLED", "false")
    monkeypatch.setenv("DO_NOT_TRACK", "1")

    assert TelemetrySettings().disabled_by() == ENABLED_OFF


@pytest.mark.parametrize("value", ["", "  "])
def test_blank_endpoint_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("STYRMIN_TELEMETRY_ENDPOINT", value)

    assert TelemetrySettings().endpoint == DEFAULT_TELEMETRY_ENDPOINT


def test_endpoint_override_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STYRMIN_TELEMETRY_ENDPOINT", "http://sink/report")

    assert TelemetrySettings().endpoint == "http://sink/report"


def test_settings_file_can_turn_telemetry_off() -> None:
    settings = load(config_data={"telemetry": {"enabled": False}})

    assert settings.telemetry.disabled_by() == ENABLED_OFF
