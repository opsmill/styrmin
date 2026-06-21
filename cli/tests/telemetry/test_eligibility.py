"""Unit tests for the env + persisted rungs of :func:`should_emit` (T019, US2).

Covers FR-014's configuration rungs — ``STYRMIN_TELEMETRY=0``, ``DO_NOT_TRACK=1``,
and the persisted ``enabled=false`` flag — each independently suppressing
emission, plus env opt-out overriding a persisted ``enabled=true``. The
command-eligibility rung (T016) and the CI/non-TTY rungs (US3/T025) are tested
elsewhere; here we drive an eligible route and vary only the config levers.

``effective_state`` (the shared reason helper) is exercised directly for reason
strings; ``should_emit`` is exercised for the boolean ladder.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# The real Cyclopts ``App`` (the unwrapped inner app). The public ``cli.app`` is
# an ``_AuthBoundaryApp`` wrapper; the telemetry runtime resolves eligibility
# against this inner app (see ``cli._AuthBoundaryApp.__call__``), so the
# command-route closed set used here matches production exactly.
from styrminctl.cli_commands import app
from styrminctl.telemetry.eligibility import effective_state, should_emit
from styrminctl.telemetry.store import TelemetryStore

# An eligible command route (real command, no help/version, not the telemetry group).
ELIGIBLE_TOKENS = ["clusters", "list"]


@pytest.fixture
def store(tmp_path: Path) -> TelemetryStore:
    """A store rooted at a writable tmp dir so persisted-flag tests round-trip."""
    return TelemetryStore(path=tmp_path / "styrminctl" / "telemetry.json")


# -- baseline: eligible + no opt-out => emit --------------------------------


def test_eligible_command_with_no_opt_out_emits(store: TelemetryStore) -> None:
    assert should_emit(app=app, tokens=ELIGIBLE_TOKENS, store=store, env={}) is True
    enabled, reason = effective_state(store=store, env={})
    assert enabled is True
    assert reason == "default; interactive terminal"


# -- rung: STYRMIN_TELEMETRY=0 ----------------------------------------------


def test_styrmin_telemetry_zero_suppresses_emit(store: TelemetryStore) -> None:
    env = {"STYRMIN_TELEMETRY": "0"}
    assert should_emit(app=app, tokens=ELIGIBLE_TOKENS, store=store, env=env) is False
    enabled, reason = effective_state(store=store, env=env)
    assert enabled is False
    assert reason == "STYRMIN_TELEMETRY=0"


def test_styrmin_telemetry_nonzero_does_not_suppress(store: TelemetryStore) -> None:
    # Only the exact value "0" disables; "1" (or anything else) leaves it on.
    env = {"STYRMIN_TELEMETRY": "1"}
    assert should_emit(app=app, tokens=ELIGIBLE_TOKENS, store=store, env=env) is True


# -- rung: DO_NOT_TRACK=1 ----------------------------------------------------


def test_do_not_track_one_suppresses_emit(store: TelemetryStore) -> None:
    env = {"DO_NOT_TRACK": "1"}
    assert should_emit(app=app, tokens=ELIGIBLE_TOKENS, store=store, env=env) is False
    enabled, reason = effective_state(store=store, env=env)
    assert enabled is False
    assert reason == "DO_NOT_TRACK=1"


# -- rung: persisted enabled=false ------------------------------------------


def test_persisted_disabled_suppresses_emit(store: TelemetryStore) -> None:
    store.set_enabled(False)
    assert should_emit(app=app, tokens=ELIGIBLE_TOKENS, store=store, env={}) is False
    enabled, reason = effective_state(store=store, env={})
    assert enabled is False
    assert reason == "persisted opt-out via 'telemetry disable'"


# -- precedence: env opt-out beats a persisted enabled=true -----------------


def test_env_opt_out_overrides_persisted_enabled_true(store: TelemetryStore) -> None:
    store.set_enabled(True)  # explicitly persisted as enabled
    assert store.is_enabled() is True

    # STYRMIN_TELEMETRY=0 wins over the persisted enabled=true.
    env_styrmin = {"STYRMIN_TELEMETRY": "0"}
    assert should_emit(app=app, tokens=ELIGIBLE_TOKENS, store=store, env=env_styrmin) is False
    assert effective_state(store=store, env=env_styrmin) == (False, "STYRMIN_TELEMETRY=0")

    # DO_NOT_TRACK=1 likewise wins over the persisted enabled=true.
    env_dnt = {"DO_NOT_TRACK": "1"}
    assert should_emit(app=app, tokens=ELIGIBLE_TOKENS, store=store, env=env_dnt) is False
    assert effective_state(store=store, env=env_dnt) == (False, "DO_NOT_TRACK=1")


# -- precedence ordering: STYRMIN_TELEMETRY reported before DO_NOT_TRACK -----


def test_styrmin_telemetry_reported_before_do_not_track(store: TelemetryStore) -> None:
    env = {"STYRMIN_TELEMETRY": "0", "DO_NOT_TRACK": "1"}
    # FR-014 order: STYRMIN_TELEMETRY is the first failing rung.
    assert effective_state(store=store, env=env) == (False, "STYRMIN_TELEMETRY=0")
