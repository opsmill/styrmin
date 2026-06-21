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
"""

from __future__ import annotations

import pytest
from styrminctl.telemetry import eligibility


@pytest.fixture(autouse=True)
def _force_interactive_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the eligibility TTY probe report an interactive terminal by default."""
    monkeypatch.setattr(eligibility, "_stderr_is_tty", lambda: True)
