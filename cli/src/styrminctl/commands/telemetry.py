"""Telemetry opt-out commands: ``telemetry enable | disable | status``.

Wire-level contract: ``specs/015-styrminctl-telemetry/contracts/cli-telemetry-command.md``.

The output wording and exit codes below are LOCKED to that contract. The
``telemetry`` group is itself **ineligible** for telemetry emission (FR-015): it
is listed in ``eligibility._INELIGIBLE_ROOT_COMMANDS`` and registered on the
root app in ``cli_commands.py``.

Every command is best-effort and MUST NOT crash on an unwritable telemetry
directory: :class:`TelemetryStore` swallows I/O errors and falls back to an
ephemeral in-memory ``install_id``, so ``enable`` / ``disable`` / ``status`` all
exit ``0`` even when persistence is impossible (FR-016, FR-017).
"""

from __future__ import annotations

from cyclopts import App

from styrminctl.telemetry.eligibility import effective_state
from styrminctl.telemetry.store import TelemetryStore

telemetry_app = App(name="telemetry", help="Inspect and control anonymous CLI telemetry.")


@telemetry_app.command
def enable() -> None:
    """Persist telemetry ``enabled = true``.

    Note: env opt-outs (``STYRMIN_TELEMETRY=0`` / ``DO_NOT_TRACK=1``) still
    suppress emission at runtime even after ``enable``; ``status`` reflects that.
    """
    TelemetryStore().set_enabled(True)
    print("Telemetry enabled.")


@telemetry_app.command
def disable() -> None:
    """Persist telemetry ``enabled = false``. Idempotent."""
    TelemetryStore().set_enabled(False)
    print("Telemetry disabled.")


@telemetry_app.command
def status() -> None:
    """Print the effective telemetry state and the reason it is on/off.

    Reports the first failing configuration rung in FR-014 order (env beats
    persisted). The state shown is the one that *would* apply to an eligible
    command — ``status`` itself never emits.
    """
    enabled, reason = effective_state(store=TelemetryStore())
    state = "enabled" if enabled else "disabled"
    print(f"Telemetry: {state} ({reason}).")
