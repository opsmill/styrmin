"""The telemetry line the server logs on every start (spec 020, FR-010, research D17)."""

import pytest

from styrmin_backend.config import DEFAULT_TELEMETRY_ENDPOINT, TelemetrySettings
from styrmin_backend.services.telemetry.state import (
    show_status_message,
    startup_message,
)

SINK_ENDPOINT = "http://telemetry-sink.default.svc.cluster.local:8080/report"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "STYRMIN_TELEMETRY_ENABLED",
        "STYRMIN_TELEMETRY_ENDPOINT",
        "STYRMIN_TELEMETRY",
        "DO_NOT_TRACK",
    ):
        monkeypatch.delenv(name, raising=False)


def test_on_text_is_the_contract_text_with_the_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STYRMIN_TELEMETRY_ENDPOINT", SINK_ENDPOINT)

    message = startup_message(TelemetrySettings())

    assert message == (
        f"Telemetry is on: Styrmin sends one anonymous report a day to {SINK_ENDPOINT}. "
        "To view it, run 'styrmin telemetry show' in the server container. "
        "To turn telemetry off, set "
        "STYRMIN_TELEMETRY_ENABLED=false (Helm value styrmin.telemetry.enabled=false) "
        "or DO_NOT_TRACK=1."
    )


@pytest.mark.parametrize(
    "expected",
    [
        SINK_ENDPOINT,
        "styrmin telemetry show",
        "STYRMIN_TELEMETRY_ENABLED=false",
        "styrmin.telemetry.enabled=false",
        "DO_NOT_TRACK=1",
    ],
)
def test_on_text_names_the_endpoint_and_how_to_view_and_turn_off(
    monkeypatch: pytest.MonkeyPatch, expected: str
) -> None:
    monkeypatch.setenv("STYRMIN_TELEMETRY_ENDPOINT", SINK_ENDPOINT)

    assert expected in startup_message(TelemetrySettings())


def test_on_text_names_the_default_endpoint_when_the_endpoint_is_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STYRMIN_TELEMETRY_ENDPOINT", "")

    assert f"to {DEFAULT_TELEMETRY_ENDPOINT}." in startup_message(TelemetrySettings())


def test_enabled_false_text_names_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STYRMIN_TELEMETRY_ENABLED", "false")

    message = startup_message(TelemetrySettings())

    assert message == "Telemetry is off (STYRMIN_TELEMETRY_ENABLED=false)."


def test_do_not_track_text_names_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DO_NOT_TRACK", "1")

    assert startup_message(TelemetrySettings()) == "Telemetry is off (DO_NOT_TRACK=1)."


@pytest.mark.parametrize(
    ("name", "value"),
    [
        pytest.param(None, None, id="on"),
        pytest.param("STYRMIN_TELEMETRY_ENABLED", "false", id="enabled-false"),
        pytest.param("DO_NOT_TRACK", "1", id="do-not-track"),
    ],
)
def test_text_is_one_line(
    monkeypatch: pytest.MonkeyPatch, name: str | None, value: str | None
) -> None:
    if name is not None and value is not None:
        monkeypatch.setenv(name, value)

    message = startup_message(TelemetrySettings())

    assert "\n" not in message
    assert "\r" not in message


def test_show_status_names_the_endpoint_and_the_task_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STYRMIN_TELEMETRY_ENDPOINT", SINK_ENDPOINT)

    assert show_status_message(TelemetrySettings()) == (
        "Telemetry is on in this container. With the same settings, the task worker "
        f"sends this report once a day to {SINK_ENDPOINT}."
    )


def test_show_status_names_the_setting_that_turns_telemetry_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STYRMIN_TELEMETRY", "0")

    assert show_status_message(TelemetrySettings()) == (
        "Telemetry is off in this container (STYRMIN_TELEMETRY=0). "
        "With the same settings, the task worker sends no report."
    )
