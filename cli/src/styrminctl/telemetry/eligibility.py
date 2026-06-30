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
persisted flag → ``CI`` → non-TTY ``stderr``). The CI and non-TTY rungs (T025)
are checked **before** the final default-enabled return.
"""

from __future__ import annotations

import os
import sys
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

#: Environment variable name for the automation/CI detection rung (FR-014).
_CI_ENV: Final[str] = "CI"

#: ``CI`` values treated as *not* CI. ``CI`` is "truthy" (⇒ automation context,
#: suppress) whenever it is set to any value outside this set. Unset is also
#: not-CI. This matches the common convention where CI providers export
#: ``CI=true``/``CI=1`` and a value of ``0``/``false``/empty means "not CI".
_CI_FALSEY_VALUES: Final[frozenset[str]] = frozenset({"", "0", "false", "False"})


def _is_ci(env: Mapping[str, str]) -> bool:
    """Return whether the ``CI`` env var marks an automation context (FR-014).

    ``CI`` counts as CI when it is set to any value not in
    :data:`_CI_FALSEY_VALUES`; unset means not-CI.
    """
    value = env.get(_CI_ENV)
    if value is None:
        return False
    return value not in _CI_FALSEY_VALUES


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
    is_tty: bool | None = None,
) -> tuple[bool, str]:
    """Return the effective telemetry ``(enabled, reason)`` for the config rungs.

    This resolves the FR-014 levers in precedence order and reports the first
    one that disables telemetry: env ``STYRMIN_TELEMETRY=0`` → ``DO_NOT_TRACK=1``
    → persisted ``enabled=false`` flag → ``CI`` set/truthy → ``stderr`` is not a
    TTY. Env opt-out beats a persisted ``enabled=true``. When none disables, the
    state is enabled with the default reason.

    ``is_tty`` lets callers inject the terminal-interactivity signal; when left
    as ``None`` it is read from ``sys.stderr.isatty()`` (best-effort — a stream
    without ``isatty`` is treated as non-interactive). ``status`` and
    ``should_emit`` rely on this default, so they need not pass it.

    It deliberately does **not** consider command eligibility (the ``status``
    command is itself ineligible but still reports the state that *would* apply
    to an eligible command — see ``contracts/cli-telemetry-command.md``). The
    reason strings are LOCKED to that contract.

    Never raises: :class:`TelemetryStore` reads are best-effort.
    """
    if env.get(_STYRMIN_TELEMETRY_ENV) == "0":
        return (False, "STYRMIN_TELEMETRY=0")
    if env.get(_DO_NOT_TRACK_ENV) == "1":
        return (False, "DO_NOT_TRACK=1")
    if not store.is_enabled():
        return (False, "persisted opt-out via 'telemetry disable'")
    if _is_ci(env):
        return (False, "non-interactive: CI detected")
    if is_tty is None:
        is_tty = _stderr_is_tty()
    if not is_tty:
        return (False, "non-interactive: stderr is not a TTY")
    return (True, "default; interactive terminal")


def _stderr_is_tty() -> bool:
    """Return whether ``sys.stderr`` is an interactive TTY (best-effort).

    A stream lacking ``isatty`` (e.g. a replaced/dummy stream) is treated as
    non-interactive.
    """
    isatty = getattr(sys.stderr, "isatty", None)
    if isatty is None:
        return False
    return bool(isatty())


def should_emit(
    *,
    app: App,
    tokens: Sequence[str],
    store: TelemetryStore,
    env: Mapping[str, str] = os.environ,
) -> bool:
    """Return whether telemetry should be emitted for this invocation.

    Emits iff the command is eligible (FR-015) **and** every FR-014 rung permits
    it: ``STYRMIN_TELEMETRY ≠ 0`` ∧ ``DO_NOT_TRACK ≠ 1`` ∧ persisted flag not
    disabled ∧ ``CI`` unset/falsey ∧ ``stderr`` is a TTY, with env opt-out
    taking precedence over a persisted ``enabled=true``. The CI and non-TTY
    rungs live in :func:`effective_state` (the TTY signal is read from
    ``sys.stderr.isatty()`` there).
    """
    if not is_eligible_command(app, tokens):
        return False
    enabled, _reason = effective_state(store=store, env=env)
    return enabled
