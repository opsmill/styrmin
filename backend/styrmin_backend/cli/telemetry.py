"""Telemetry commands for Styrmin CLI (spec 020, FR-013).

``styrmin telemetry show`` prints the data of the next daily report. It never sends it.
"""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from cyclopts import App

from styrmin_backend import config
from styrmin_backend.db.utils import get_async_engine
from styrmin_backend.services.telemetry.payload import build_report_data
from styrmin_backend.services.telemetry.state import show_status_message
from styrmin_backend.services.unit_of_work import get_unit_of_work

telemetry_app = App(name="telemetry", help="Telemetry commands.")


async def _read_report_data() -> dict[str, Any]:
    """Build the report data; commit, because the install ID may be created here."""
    try:
        async with get_unit_of_work() as uow:
            data = await build_report_data(uow)
            await uow.commit()
    finally:
        await get_async_engine().dispose()
    return data


@telemetry_app.command
def show(
    config_file: Path | None = None,
) -> None:
    """Print the data of the next telemetry report as JSON. Nothing is sent.

    Args:
        config_file: Path to configuration file.
    """
    config.SETTINGS.initialize_and_exit(str(config_file) if config_file else None)
    print(show_status_message(config.SETTINGS.telemetry), file=sys.stderr)

    try:
        # Standard output carries only the JSON; other output (e.g. SQL echo) goes to stderr.
        with redirect_stdout(sys.stderr):
            data = asyncio.run(_read_report_data())
    except Exception as error:
        # One line (contract): SQLAlchemy appends the SQL and a help link on later lines.
        reason = str(error).partition("\n")[0]
        print(
            f"Could not read the telemetry report: {reason}. "
            "Check that you run this command in the server container.",
            file=sys.stderr,
        )
        raise SystemExit(1) from error

    print(json.dumps(data, indent=2))
