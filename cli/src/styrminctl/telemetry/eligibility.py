"""Telemetry eligibility ladder.

:func:`should_emit` is a pure predicate over the FR-014/FR-015 rungs. It is built
incrementally:

* **T016 (MVP)** — *command eligibility only*: an invocation is eligible
  unless its route is the ``telemetry`` command group, the ``--version`` /
  ``version`` path, a ``--help`` / ``-h`` invocation, an empty route (the bare
  help screen), or the shell-completion command registered by
  ``register_install_completion_command()``.
* **T021 (US2, this layer)** — env opt-out (``STYRMIN_TELEMETRY=0`` /
  ``DO_NOT_TRACK=1``) and the persisted ``enabled`` flag, with env opt-out taking
  precedence over a persisted ``enabled=true``.
* **T025 (US3)** — the ``CI`` and non-TTY rungs.

The signature already accepts ``store`` and ``env`` so the later rungs slot in
without changing call sites (see :func:`styrminctl.telemetry.runtime.run`).

Reason reporting (FR-016): :func:`effective_state` returns ``(enabled, reason)``
for the configuration rungs and is the single source of truth shared by
:func:`should_emit` and the ``telemetry status`` command. It reports the **first
failing rung in FR-014 order** (env ``STYRMIN_TELEMETRY`` → ``DO_NOT_TRACK`` →
persisted flag). US3 (T025) extends it with the CI and non-TTY rungs by
appending further checks **before** the final default-enabled return.
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

#: Environment variable names for the two env opt-out levers (FR-014).
_STYRMIN_TELEMETRY_ENV: Final[str] = "STYRMIN_TELEMETRY"
_DO_NOT_TRACK_ENV: Final[str] = "DO_NOT_TRACK"


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


def effective_state(
    *,
    store: TelemetryStore,
    env: Mapping[str, str] = os.environ,
) -> tuple[bool, str]:
    """Return the effective telemetry ``(enabled, reason)`` for the config rungs.

    This resolves the **configuration** levers in FR-014 precedence order and
    reports the first one that disables telemetry — env ``STYRMIN_TELEMETRY=0``
    first, then ``DO_NOT_TRACK=1``, then the persisted ``enabled=false`` flag.
    Env opt-out beats a persisted ``enabled=true``. When none disables, the
    state is enabled with the default reason.

    It deliberately does **not** consider command eligibility (the ``status``
    command is itself ineligible but still reports the state that *would* apply
    to an eligible command — see ``contracts/cli-telemetry-command.md``). The
    reason strings are LOCKED to that contract; US3 (T025) appends the CI and
    non-TTY rungs **before** the final default-enabled return.

    Never raises: :class:`TelemetryStore` reads are best-effort.
    """
    if env.get(_STYRMIN_TELEMETRY_ENV) == "0":
        return (False, "STYRMIN_TELEMETRY=0")
    if env.get(_DO_NOT_TRACK_ENV) == "1":
        return (False, "DO_NOT_TRACK=1")
    if not store.is_enabled():
        return (False, "persisted opt-out via 'telemetry disable'")
    return (True, "default; interactive terminal")


def should_emit(
    *,
    app: App,
    tokens: Sequence[str],
    store: TelemetryStore,
    env: Mapping[str, str] = os.environ,
) -> bool:
    """Return whether telemetry should be emitted for this invocation.

    Emits iff the command is eligible (FR-015) **and** the configuration rungs
    all permit it (FR-014): ``STYRMIN_TELEMETRY ≠ 0`` ∧ ``DO_NOT_TRACK ≠ 1`` ∧
    persisted flag not disabled, with env opt-out taking precedence over a
    persisted ``enabled=true``. The CI and non-TTY rungs are added in US3
    (T025) inside :func:`effective_state`.
    """
    if not is_eligible_command(app, tokens):
        return False
    enabled, _reason = effective_state(store=store, env=env)
    return enabled
