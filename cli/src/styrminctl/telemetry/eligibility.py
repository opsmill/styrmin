"""Telemetry eligibility ladder.

:func:`should_emit` is a pure predicate over the FR-014/FR-015 rungs. It is built
incrementally:

* **T016 (this MVP)** — *command eligibility only*: an invocation is eligible
  unless its route is the ``telemetry`` command group, the ``--version`` /
  ``version`` path, a ``--help`` / ``-h`` invocation, an empty route (the bare
  help screen), or the shell-completion command registered by
  ``register_install_completion_command()``.
* **T021 (US2)** — env opt-out (``STYRMIN_TELEMETRY=0`` / ``DO_NOT_TRACK=1``) and
  the persisted ``enabled`` flag.
* **T025 (US3)** — the ``CI`` and non-TTY rungs.

The signature already accepts ``store`` and ``env`` so the later rungs slot in
without changing call sites (see :func:`styrminctl.telemetry.runtime.run`).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from cyclopts import App

    from .store import TelemetryStore

#: First-token command routes that never emit telemetry (FR-015).
_INELIGIBLE_ROOT_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "telemetry",  # the opt-out command group itself (registered in US2/T023)
        "--version",
        "version",
        "--help",
        "-h",
        # Shell-completion command(s) installed by register_install_completion_command().
        "--install-completion",
    }
)

#: Option-like tokens that, when present anywhere, mark the invocation ineligible
#: (a help/version screen rather than a real command).
_INELIGIBLE_TOKENS: Final[frozenset[str]] = frozenset({"--help", "-h", "--version"})


def is_eligible_command(app: App, tokens: Sequence[str]) -> bool:
    """Return whether the resolved command route is telemetry-eligible (FR-015).

    Resolves the route via Cyclopts ``parse_commands`` (a closed set, never raw
    ``sys.argv`` slicing). An empty route, a help/version screen, the
    ``telemetry`` group, and the completion command are all ineligible.
    """
    # A help/version flag anywhere short-circuits to ineligible even when it
    # trails a real sub-command (e.g. ``clusters --help`` renders help, not a run).
    if any(token in _INELIGIBLE_TOKENS for token in tokens):
        return False

    command_tokens, _apps, _unused = app.parse_commands(list(tokens))
    if not command_tokens:
        return False  # empty route → bare help screen
    first = command_tokens[0]
    return first not in _INELIGIBLE_ROOT_COMMANDS


def should_emit(
    *,
    app: App,
    tokens: Sequence[str],
    store: TelemetryStore,  # noqa: ARG001 - consumed by the persisted rung in US2/T021
    env: Mapping[str, str] = os.environ,  # noqa: ARG001 - consumed by env/CI rungs in US2/US3
) -> bool:
    """Return whether telemetry should be emitted for this invocation.

    MVP scope (T016): command eligibility only. ``store`` and ``env`` are part of
    the stable signature so US2/US3 can add the persisted, env, CI, and non-TTY
    rungs without touching the call site.
    """
    return is_eligible_command(app, tokens)
