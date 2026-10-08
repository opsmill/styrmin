"""The ``styrmin telemetry show`` command (spec 020, FR-013, contracts/cli-telemetry-show.md)."""

from __future__ import annotations

import ast
import inspect
import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture

from styrmin_backend.cli import telemetry
from styrmin_backend.cli.telemetry import telemetry_app
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
    send_report: AsyncMock


@pytest.fixture
def patched(mocker: MockerFixture) -> Patched:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.commit = AsyncMock()
    engine = MagicMock(dispose=AsyncMock())
    mocker.patch(f"{MODULE}.get_unit_of_work", yield_unit_of_work(uow))
    mocker.patch(f"{MODULE}.get_async_engine", return_value=engine)
    return Patched(
        config=mocker.patch(f"{MODULE}.config"),
        uow=uow,
        build_report_data=mocker.patch(
            f"{MODULE}.build_report_data", AsyncMock(return_value=REPORT_DATA)
        ),
        engine=engine,
        send_report=mocker.patch(
            "styrmin_backend.services.telemetry.sender.send_report", AsyncMock()
        ),
    )


def test_show_prints_only_the_report_data_and_sends_nothing(
    patched: Patched, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        telemetry_app(["show"])

    assert exc_info.value.code == 0
    output = capsys.readouterr()
    assert output.out == json.dumps(REPORT_DATA, indent=2) + "\n"
    assert json.loads(output.out) == REPORT_DATA
    assert output.err == ""
    patched.config.SETTINGS.initialize_and_exit.assert_called_once_with(None)
    patched.build_report_data.assert_awaited_once_with(patched.uow)
    patched.uow.commit.assert_awaited_once()
    patched.engine.dispose.assert_awaited_once()
    patched.send_report.assert_not_awaited()


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
    assert output.err == (
        "Could not read the telemetry report: no such table: installation\n"
    )
    patched.uow.commit.assert_not_awaited()
    patched.engine.dispose.assert_awaited_once()


def test_show_module_does_not_import_the_sender() -> None:
    tree = ast.parse(inspect.getsource(telemetry))
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert "styrmin_backend.services.telemetry.sender" not in imported
    assert not hasattr(telemetry, "send_report")
