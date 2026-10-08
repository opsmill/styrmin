"""Daily Prefect flow that sends the anonymous telemetry report (spec 020, research D8, D14)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from prefect import flow
from prefect.logging import get_run_logger
from prefect.runtime import flow_run as flow_run_ctx

from styrmin_backend import config
from styrmin_backend.services.telemetry.payload import build_report_data
from styrmin_backend.services.telemetry.sender import send_report
from styrmin_backend.services.unit_of_work import get_unit_of_work

LATE_RUN_LIMIT = timedelta(hours=1)


@flow(name="send_telemetry_report")
async def send_telemetry_report_flow() -> bool:
    """Send one report. Return True when the endpoint accepted it; never raise, so the run ends Completed."""
    log = get_run_logger()
    settings = config.SETTINGS.telemetry

    disabled_by = settings.disabled_by()
    if disabled_by is not None:
        log.debug("Telemetry is off (%s); no report sent", disabled_by)
        return False

    # A run with no scheduled time counts as on time.
    scheduled = flow_run_ctx.scheduled_start_time
    if scheduled is not None and datetime.now(UTC) - scheduled > LATE_RUN_LIMIT:
        log.debug(
            "Run scheduled at %s started more than %s late; a missed report is not sent later",
            scheduled.isoformat(),
            LATE_RUN_LIMIT,
        )
        return False

    try:
        async with get_unit_of_work() as uow:
            data = await build_report_data(uow)
            await uow.commit()
        return await send_report(data, settings.endpoint, log)
    except Exception as error:  # noqa: BLE001 - send failures are logged at debug in send_report
        log.warning(
            "Could not send the telemetry report: %s: %s", type(error).__name__, error
        )
        return False
