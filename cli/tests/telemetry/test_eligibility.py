"""Unit tests for the FR-014 config rungs of :func:`should_emit` (T019/US2, T024/US3).

Covers FR-014's configuration rungs — ``STYRMIN_TELEMETRY=0``, ``DO_NOT_TRACK=1``,
the persisted ``enabled=false`` flag (US2), and the ``CI`` / non-TTY-``stderr``
automation rungs (US3) — each independently suppressing emission, plus env
opt-out overriding a persisted ``enabled=true`` and the FR-014 precedence
ordering. The command-eligibility rung (T016) is tested elsewhere; here we drive
an eligible route and vary only the config/automation levers.

The autouse ``_force_interactive_stderr`` fixture (``conftest.py``) makes the
suite's pre-existing "interactive terminal" assumption explicit; the US3 tests
inject ``is_tty`` into :func:`effective_state` directly to isolate the CI and
non-TTY rungs.

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
from styrminctl.telemetry import eligibility
from styrminctl.telemetry.eligibility import effective_state, is_eligible_command, should_emit
from styrminctl.telemetry.store import TelemetryStore

# An eligible command route (real command, no help/version, not the telemetry group).
ELIGIBLE_TOKENS = ["clusters", "list"]


# -- command-eligibility rung (FR-015), tested directly against the real app ---


@pytest.mark.parametrize(
    "tokens",
    [
        ["telemetry", "status"],  # the opt-out command group
        ["telemetry", "disable"],
        ["--version"],  # version screen
        ["--help"],  # help screens
        ["-h"],
        [],  # empty route → bare help screen
        # Shell-completion command registered by register_install_completion_command()
        # (see cli_commands.py); Cyclopts exposes it as the ``--install-completion`` token.
        ["--install-completion"],
    ],
)
def test_ineligible_routes_return_false(tokens: list[str]) -> None:
    assert is_eligible_command(app, tokens) is False


def test_eligible_route_returns_true() -> None:
    assert is_eligible_command(app, ELIGIBLE_TOKENS) is True


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


# -- rung: CI detected (US3, T024) ------------------------------------------
#
# These tests pass ``is_tty=True`` so that an *enabled* result is attributable
# to the CI rung alone, isolated from the non-TTY rung that follows it.


@pytest.mark.parametrize("ci_value", ["true", "1", "True", "yes", "anything"])
def test_ci_truthy_suppresses_emit(store: TelemetryStore, ci_value: str) -> None:
    env = {"CI": ci_value}
    assert should_emit(app=app, tokens=ELIGIBLE_TOKENS, store=store, env=env) is False
    enabled, reason = effective_state(store=store, env=env, is_tty=True)
    assert enabled is False
    assert reason == "non-interactive: CI detected"


@pytest.mark.parametrize("ci_value", ["", "0", "false", "False"])
def test_ci_falsey_does_not_suppress(store: TelemetryStore, ci_value: str) -> None:
    # Falsey CI values (and unset) are treated as "not CI" and leave emission on.
    env = {"CI": ci_value}
    assert should_emit(app=app, tokens=ELIGIBLE_TOKENS, store=store, env=env) is True
    assert effective_state(store=store, env=env, is_tty=True) == (True, "default; interactive terminal")


def test_ci_unset_does_not_suppress(store: TelemetryStore) -> None:
    assert should_emit(app=app, tokens=ELIGIBLE_TOKENS, store=store, env={}) is True
    assert effective_state(store=store, env={}, is_tty=True) == (True, "default; interactive terminal")


# -- rung: stderr is not a TTY (US3, T024) ----------------------------------


def test_non_tty_stderr_suppresses_emit(store: TelemetryStore) -> None:
    enabled, reason = effective_state(store=store, env={}, is_tty=False)
    assert enabled is False
    assert reason == "non-interactive: stderr is not a TTY"


def test_should_emit_reads_stderr_isatty(store: TelemetryStore, monkeypatch: pytest.MonkeyPatch) -> None:
    # ``should_emit`` has no ``is_tty`` knob: it must defer to the real
    # ``sys.stderr.isatty()`` probe. Force the probe false and assert no emit;
    # force it true and assert emit (the autouse fixture already forces true,
    # so we override it explicitly here for both directions).
    monkeypatch.setattr(eligibility, "_stderr_is_tty", lambda: False)
    assert should_emit(app=app, tokens=ELIGIBLE_TOKENS, store=store, env={}) is False
    assert effective_state(store=store, env={}) == (False, "non-interactive: stderr is not a TTY")

    monkeypatch.setattr(eligibility, "_stderr_is_tty", lambda: True)
    assert should_emit(app=app, tokens=ELIGIBLE_TOKENS, store=store, env={}) is True
    assert effective_state(store=store, env={}) == (True, "default; interactive terminal")


# -- precedence + restoration: both rungs cleared => emit (FR-014) ----------


def test_ci_reported_before_non_tty(store: TelemetryStore) -> None:
    # When both CI is set AND stderr is non-TTY, CI is the first failing rung.
    env = {"CI": "true"}
    assert effective_state(store=store, env=env, is_tty=False) == (False, "non-interactive: CI detected")


def test_both_automation_rungs_restored_emits(store: TelemetryStore) -> None:
    # CI unset/falsey AND stderr is a TTY => emit (the US3 happy path).
    enabled, reason = effective_state(store=store, env={"CI": "0"}, is_tty=True)
    assert enabled is True
    assert reason == "default; interactive terminal"
    assert should_emit(app=app, tokens=ELIGIBLE_TOKENS, store=store, env={"CI": "0"}) is True
