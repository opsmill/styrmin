"""The daily telemetry flow and its catalogue entry (spec 020, research D14, D16).

The flow body runs through ``Flow.fn`` with the logger, the unit of work, the
payload builder, the sender and the scheduled start time patched in the module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrmin_backend.config import DEFAULT_TELEMETRY_ENDPOINT, TelemetrySettings
from styrmin_backend.workflows.catalogue import PrefectCatalogue
from styrmin_backend.workflows.constants import WorkflowType
from styrmin_backend.workflows.models import PrefectAction
from styrmin_backend.workflows.templates.telemetry import send_telemetry_report_flow
from tests.helpers.unit_of_work import yield_unit_of_work

MODULE = "styrmin_backend.workflows.templates.telemetry"
REPORT_DATA = {"install_id": "0b6f4f0e-6d0e-4a55-9a51-2f8c3f7c9f0d"}


@dataclass
class FlowRun:
    result: bool
    build_report_data: AsyncMock
    send_report: AsyncMock
    uow: MagicMock
    logger: MagicMock


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "STYRMIN_TELEMETRY_ENABLED",
        "STYRMIN_TELEMETRY_ENDPOINT",
        "DO_NOT_TRACK",
    ):
        monkeypatch.delenv(name, raising=False)


async def _run_flow(*, scheduled_start_time: datetime | None) -> FlowRun:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.commit = AsyncMock()
    build_report_data = AsyncMock(return_value=REPORT_DATA)
    send_report = AsyncMock(return_value=True)
    logger = MagicMock()
    settings = MagicMock()
    settings.SETTINGS.telemetry = TelemetrySettings()

    with (
        patch(f"{MODULE}.config", settings),
        patch(f"{MODULE}.get_run_logger", return_value=logger),
        patch(f"{MODULE}.get_unit_of_work", yield_unit_of_work(uow)),
        patch(f"{MODULE}.build_report_data", build_report_data),
        patch(f"{MODULE}.send_report", send_report),
        patch(
            f"{MODULE}.flow_run_ctx",
            MagicMock(scheduled_start_time=scheduled_start_time),
        ),
    ):
        result = await send_telemetry_report_flow.fn()

    return FlowRun(
        result=result,
        build_report_data=build_report_data,
        send_report=send_report,
        uow=uow,
        logger=logger,
    )


async def test_on_time_run_sends_the_built_data_to_the_default_endpoint() -> None:
    run = await _run_flow(scheduled_start_time=datetime.now(UTC))

    assert run.result is True
    run.build_report_data.assert_awaited_once_with(run.uow)
    run.uow.commit.assert_awaited_once()
    run.send_report.assert_awaited_once_with(
        REPORT_DATA, DEFAULT_TELEMETRY_ENDPOINT, run.logger
    )


async def test_run_without_a_scheduled_time_sends() -> None:
    run = await _run_flow(scheduled_start_time=None)

    assert run.result is True
    run.send_report.assert_awaited_once()


async def test_run_that_starts_61_minutes_late_sends_nothing() -> None:
    run = await _run_flow(
        scheduled_start_time=datetime.now(UTC) - timedelta(minutes=61)
    )

    assert run.result is False
    run.build_report_data.assert_not_awaited()
    run.send_report.assert_not_awaited()
    run.logger.debug.assert_called_once()
    run.logger.warning.assert_not_called()


async def test_run_that_starts_59_minutes_late_sends() -> None:
    run = await _run_flow(
        scheduled_start_time=datetime.now(UTC) - timedelta(minutes=59)
    )

    assert run.result is True
    run.send_report.assert_awaited_once()


async def test_catalogue_entry_is_internal_with_a_daily_cron() -> None:
    definition = PrefectCatalogue().get_workflow_definition(
        PrefectAction.SEND_TELEMETRY_REPORT
    )

    assert definition.type == WorkflowType.INTERNAL
    assert definition.full_name == "send_telemetry_report/send_telemetry_report"
    definition.validate_workflow()

    payload = await definition.to_deployment()
    (schedule,) = payload["schedules"]
    assert schedule.schedule.cron == "43 2 * * *"
    assert schedule.schedule.timezone in {None, "UTC"}
