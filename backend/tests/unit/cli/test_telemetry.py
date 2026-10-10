"""The ``styrmin telemetry show`` command (spec 020, FR-013, contracts/cli-telemetry-show.md)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture

from styrmin_backend.cli.telemetry import telemetry_app
from styrmin_backend.config import DEFAULT_TELEMETRY_ENDPOINT, TelemetrySettings
from tests.helpers.http_sink import serve_sink
from tests.helpers.unit_of_work import yield_unit_of_work

MODULE = "styrmin_backend.cli.telemetry"
REPORT_DATA = {
    "install_id": "0b6f4f0e-6d0e-4a55-9a51-2f8c3f7c9f0d",
    "styrmin_version": "1.2.3",
    "cluster_count": 1,
    "drivers": [{"name": "simple-app", "deployment_count": 2}],
}


@dataclass
class Patched:
    config: MagicMock
    uow: MagicMock
    build_report_data: AsyncMock
    engine: MagicMock


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "STYRMIN_TELEMETRY_ENABLED",
        "STYRMIN_TELEMETRY_ENDPOINT",
        "STYRMIN_TELEMETRY",
        "DO_NOT_TRACK",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def patched(mocker: MockerFixture) -> Patched:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.commit = AsyncMock()
    engine = MagicMock(dispose=AsyncMock())
    mocker.patch(f"{MODULE}.get_unit_of_work", yield_unit_of_work(uow))
    mocker.patch(f"{MODULE}.get_async_engine", return_value=engine)
    config = mocker.patch(f"{MODULE}.config")
    config.SETTINGS.telemetry = TelemetrySettings()
    return Patched(
        config=config,
        uow=uow,
        build_report_data=mocker.patch(
            f"{MODULE}.build_report_data", AsyncMock(return_value=REPORT_DATA)
        ),
        engine=engine,
    )


def test_show_prints_the_report_data_to_stdout_and_the_state_to_stderr(
    patched: Patched, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        telemetry_app(["show"])

    assert exc_info.value.code == 0
    output = capsys.readouterr()
    assert output.out == json.dumps(REPORT_DATA, indent=2) + "\n"
    assert json.loads(output.out) == REPORT_DATA
    assert output.err == (
        "Telemetry is on in this container. With the same settings, the task worker "
        f"sends this report once a day to {DEFAULT_TELEMETRY_ENDPOINT}.\n"
    )
    patched.config.SETTINGS.initialize_and_exit.assert_called_once_with(None)
    patched.build_report_data.assert_awaited_once_with(patched.uow)
    patched.uow.commit.assert_awaited_once()
    patched.engine.dispose.assert_awaited_once()


def test_show_sends_no_request_to_the_endpoint(
    patched: Patched, capsys: pytest.CaptureFixture[str]
) -> None:
    with serve_sink() as sink:
        patched.config.SETTINGS.telemetry = TelemetrySettings(endpoint=sink.url)

        with pytest.raises(SystemExit) as exc_info:
            telemetry_app(["show"])

    assert exc_info.value.code == 0
    assert sink.url in capsys.readouterr().err
    assert sink.requests == []


def test_show_says_when_telemetry_is_off(
    patched: Patched,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    patched.config.SETTINGS.telemetry = TelemetrySettings()

    with pytest.raises(SystemExit) as exc_info:
        telemetry_app(["show"])

    assert exc_info.value.code == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == REPORT_DATA
    assert output.err == (
        "Telemetry is off in this container (DO_NOT_TRACK=1). "
        "With the same settings, the task worker sends no report.\n"
    )


def test_show_loads_the_given_config_file(patched: Patched) -> None:
    with pytest.raises(SystemExit) as exc_info:
        telemetry_app(["show", "--config-file", "/etc/styrmin/styrmin.toml"])

    assert exc_info.value.code == 0
    patched.config.SETTINGS.initialize_and_exit.assert_called_once_with(
        "/etc/styrmin/styrmin.toml"
    )


def test_show_prints_one_error_line_and_exits_1_when_the_database_fails(
    patched: Patched, capsys: pytest.CaptureFixture[str]
) -> None:
    patched.build_report_data.side_effect = RuntimeError(
        "no such table: installation\n[SQL: INSERT INTO installation]"
    )

    with pytest.raises(SystemExit) as exc_info:
        telemetry_app(["show"])

    assert exc_info.value.code == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.splitlines()[-1] == (
        "Could not read the telemetry report: no such table: installation. "
        "Check that you run this command in the server container."
    )
    patched.uow.commit.assert_not_awaited()
    patched.engine.dispose.assert_awaited_once()
