"""The telemetry line the server logs on every start (spec 020, FR-010, research D17)."""

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
        "To view it, run 'styrmin telemetry show'. "
        "To turn telemetry off, set STYRMIN_TELEMETRY_ENABLED=false "
        "(Helm value styrmin.telemetry.enabled=false) or DO_NOT_TRACK=1."
    )
