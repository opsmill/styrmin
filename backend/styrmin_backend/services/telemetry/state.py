"""Telemetry state lines: logged on every server start and printed by ``styrmin telemetry show``.

Spec 020, FR-010, research D17.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from styrmin_backend.config import TelemetrySettings


def startup_message(settings: TelemetrySettings) -> str:
    """Return the one-line text of contracts/configuration.md ("Startup log line")."""
    disabled_by = settings.disabled_by()
    if disabled_by is not None:
        return f"Telemetry is off ({disabled_by})."
    return (
        f"Telemetry is on: Styrmin sends one anonymous report a day to {settings.endpoint}. "
        "To view it, run 'styrmin telemetry show' in the server container. "
        "To turn telemetry off, set STYRMIN_TELEMETRY_ENABLED=false "
        "(Helm value styrmin.telemetry.enabled=false) or DO_NOT_TRACK=1."
    )


def show_status_message(settings: TelemetrySettings) -> str:
    """Return the line that ``styrmin telemetry show`` prints to standard error.

    The task worker, not this container, sends the report; the Helm chart gives both the same settings.
    """
    disabled_by = settings.disabled_by()
    if disabled_by is not None:
        return (
            f"Telemetry is off in this container ({disabled_by}). "
            "With the same settings, the task worker sends no report."
        )
    return (
        "Telemetry is on in this container. With the same settings, the task worker "
        f"sends this report once a day to {settings.endpoint}."
    )
