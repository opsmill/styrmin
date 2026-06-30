"""Shared fixtures for the telemetry test suite.

The FR-014 eligibility ladder gained a non-TTY rung in US3 (T025): emission is
suppressed when ``sys.stderr`` is not an interactive terminal. Under pytest,
``sys.stderr`` is captured and reports ``isatty() == False``, which would flip
every "default; interactive terminal" expectation that predates the rung.

These suites were written assuming an interactive terminal, so this autouse
fixture makes that assumption explicit by forcing the eligibility ladder's
TTY probe (``eligibility._stderr_is_tty``) to report ``True`` for the whole
telemetry suite. Patching the probe rather than ``sys.stderr.isatty`` is robust
against pytest swapping ``sys.stderr`` for capture mid-test. Tests that
specifically exercise the non-TTY rung inject ``is_tty=False`` into
``effective_state`` directly, which bypasses the probe entirely.

The same baseline applies to the FR-014 CI-detection rung: the ladder
short-circuits to "non-interactive: CI detected" whenever ``CI`` is set to a
truthy value, which it is on every CI runner (``CI=true``). That rung fires
*before* the patched TTY probe, so left unstripped it flips every "default;
interactive terminal" expectation — the suite passes locally (``CI`` unset)
but fails under CI. The autouse fixture therefore also clears the CI-context
env vars so the whole suite runs in a deterministic interactive, non-CI
baseline. Tests that specifically exercise the CI rung set ``CI`` themselves.
"""

from __future__ import annotations

import pytest
from styrminctl.telemetry import eligibility


@pytest.fixture(autouse=True)
def _force_interactive_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force an interactive, non-CI eligibility baseline for the whole suite."""
    monkeypatch.setattr(eligibility, "_stderr_is_tty", lambda: True)
    for var in ("CI", "GITHUB_ACTIONS"):
        monkeypatch.delenv(var, raising=False)
