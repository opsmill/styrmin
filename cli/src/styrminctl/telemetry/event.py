"""Telemetry event construction and scrubbing.

``build_event()`` assembles the ordered, closed-set ``data`` payload from the
resolved command route, canonical option names, outcome, error category, and
coarse environment facts, and composes the ``event_id`` (FR-007 to FR-013).

Scrub-by-construction: the ``data`` key set is closed and fixed in insertion
order (load-bearing for the checksum); ``command`` comes from Cyclopts'
``parse_commands`` (a closed set of registered routes, never ``sys.argv``
slicing); ``options`` are the canonical long-form names of explicitly-passed
options only.

Option-name extraction (critique E1) is **token-scan + parameter metadata
only** — it never triggers Cyclopts value conversion and therefore never reads
a ``@file`` option value. Each option-like token (leading ``-``, with any
``=value`` suffix stripped before matching) is mapped to the matching
:class:`~cyclopts.argument.Argument`'s canonical long name via
``ArgumentCollection.match``; positionals and unknown tokens do not match and
are skipped. The resulting names are deduplicated and sorted.

See ``specs/015-styrminctl-telemetry/data-model.md`` and ``research.md``
(R2, R3, R9).
"""

from __future__ import annotations

import platform
from importlib.metadata import version
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from cyclopts import App


def resolve_command(app: App, tokens: Sequence[str]) -> str:
    """Return the space-joined resolved command route (closed set).

    Uses Cyclopts ``parse_commands`` so the value is always a member of the
    registered command tree; never derived from raw ``sys.argv`` slicing.
    """
    command_tokens, _apps, _unused = app.parse_commands(list(tokens))
    return " ".join(command_tokens)


def extract_options(app: App, tokens: Sequence[str]) -> list[str]:
    """Return the canonical long-form names of explicitly-passed options.

    Deduplicated and sorted; positionals and repeat-counts excluded; values
    never read. Extraction is token-scan + parameter metadata only — it must
    NOT trigger value conversion / ``@file`` reads (critique E1).
    """
    _command_tokens, apps, _unused = app.parse_commands(list(tokens))
    # ``apps[-1]`` is the most specific resolved sub-app (or the root app when
    # only the program name resolved).
    resolved = apps[-1]
    argument_collection = resolved.assemble_argument_collection()

    names: set[str] = set()
    for token in tokens:
        if not token.startswith("-"):
            continue  # positional — never an option name
        # Strip an inline ``=value`` so the value is never inspected and the
        # bare option name still matches the parameter metadata.
        name_token = token.split("=", 1)[0]
        try:
            argument, _keys, _implicit = argument_collection.match(name_token)
        except ValueError:
            # Unknown / unmatched token (e.g. an option for a different route,
            # or a positional that happens to start with ``-``). Skip silently;
            # we only emit names that belong to this command's declared set.
            continue
        canonical = _canonical_long_name(argument.names)
        if canonical is not None:
            names.add(canonical)
    return sorted(names)


def _canonical_long_name(option_names: Sequence[str]) -> str | None:
    """Return the first ``--long`` name from an Argument's name tuple.

    Cyclopts orders ``names`` by declaration order, so a short alias may come
    first; the canonical telemetry name is the first ``--`` entry.
    """
    for name in option_names:
        if name.startswith("--"):
            return name
    return None


def _environment_facts() -> dict[str, str]:
    """Return the coarse environment facts (FR-013): os family, versions.

    Never includes kernel string, build, or architecture detail.
    """
    return {
        "styrminctl_version": version("cli"),
        "python_version": platform.python_version(),
        "os_family": platform.system(),
    }


def build_event(
    *,
    app: App,
    tokens: Sequence[str],
    install_id: str,
    outcome: str,
    error_category: str | None,
) -> dict[str, Any]:
    """Assemble the ordered, closed-set ``data`` payload for one invocation.

    The key insertion order is fixed and load-bearing for the envelope checksum
    (FR-007). ``event_id`` is ``install_id[:8]`` + ``"-"`` + the command with
    spaces replaced by underscores (FR-012).
    """
    command = resolve_command(app, tokens)
    options = extract_options(app, tokens)
    event_id = f"{install_id[:8]}-{command.replace(' ', '_')}"
    facts = _environment_facts()

    # Insertion order is intentional and MUST match the contract (FR-007).
    return {
        "event_id": event_id,
        "install_id": install_id,
        "command": command,
        "options": options,
        "outcome": outcome,
        "error_category": error_category,
        "styrminctl_version": facts["styrminctl_version"],
        "python_version": facts["python_version"],
        "os_family": facts["os_family"],
    }
