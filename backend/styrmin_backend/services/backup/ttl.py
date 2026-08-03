"""Backup retention TTL: the built-in default, its validation rule, and the
deepest-wins scope resolution.

Single home for the retention rule (016-backup-retention-ttl):

* :data:`DEFAULT_BACKUP_TTL` is the one place the built-in ``720h`` retention
  is spelled out. The Velero builders take the TTL as a required input, so no
  layer below this module carries a fallback literal.
* :func:`validate_backup_ttl` is imported by the ``backup_ttl`` field validator
  on ``BaseConfigSection``, which every config surface (cluster create,
  environment create/update, deploy, deployment update) funnels through — so
  one rule rejects a malformed value on all five surfaces before any write.
* :func:`resolve_backup_ttl` answers "which retention applies to this backup?"
  as a pure function over the three scopes' persisted config dicts, reporting
  the scope it came from for the audit record and the workflow log.

Accepted syntax is a strictly positive Go duration limited to ``h``/``m``/``s``
units and to the magnitude Go can represent — a subset of what Velero's
``spec.ttl`` parses, chosen so every accepted value round-trips through Go's
``time.ParseDuration``. Compounds (``1h30m``) and decimals (``1.5h``) are valid
Go durations and are accepted; there is deliberately no day unit (Go has none,
so ``30d`` would be rejected by Velero at apply time), no bare integer (``720``
is ambiguous), and nothing above :data:`MAX_BACKUP_TTL_HOURS` (Go durations are
int64 nanoseconds, so larger values overflow ``ParseDuration``).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from loguru import logger

# The built-in retention applied when no scope sets a policy. Pinned by
# ``backend/tests/unit/services/test_backup_ttl_resolution.py`` — the single
# home of this literal.
DEFAULT_BACKUP_TTL = "720h"

# Strictly positive Go duration restricted to h/m/s units; one or more
# ``<number><unit>`` components (``720h``, ``1h30m``, ``1.5h``). Case-sensitive:
# ``24H`` is not a Go duration. ``[0-9]`` rather than ``\d`` because ``\d`` is
# Unicode-aware and would admit non-ASCII digits (``"٧٢٠h"``,
# Arabic-Indic 720h) that ``float()`` parses but Go's ``ParseDuration`` does
# not. Anchored with ``\A``/``\Z`` rather than ``^``/``$`` because ``$`` also
# matches immediately before a trailing newline, which let ``"720h\n"`` through
# to Velero as an unparseable ``spec.ttl``. The anchors make the pattern
# self-contained, so a caller reaching for ``.match`` cannot reopen that hole.
BACKUP_TTL_PATTERN: re.Pattern[str] = re.compile(r"\A([0-9]+(\.[0-9]+)?(h|m|s))+\Z")

# Individual ``<number><unit>`` components, used to reject all-zero durations
# (``0h``, ``0h0m0s``) that match the syntax but express no retention, and to
# total the duration for the overflow check.
_BACKUP_TTL_COMPONENT_RE: re.Pattern[str] = re.compile(r"([0-9]+(?:\.[0-9]+)?)(h|m|s)")

# Seconds per accepted unit, for totalling a compound duration.
_BACKUP_TTL_UNIT_SECONDS: dict[str, int] = {"h": 3600, "m": 60, "s": 1}

# Go durations are int64 nanoseconds, so ``time.ParseDuration`` overflows above
# 9223372036854775807ns == 2562047.788...h. Round down to whole hours for a
# bound that is safely inside the representable range: ``2562047h`` parses,
# ``2562048h`` does not. Velero decodes ``spec.ttl`` with ``metav1.Duration``
# (which delegates to ``ParseDuration``), so anything larger would be rejected
# asynchronously at apply time instead of at submission.
MAX_BACKUP_TTL_HOURS = 2562047
_MAX_BACKUP_TTL_SECONDS = MAX_BACKUP_TTL_HOURS * 3600

_INVALID_BACKUP_TTL_MESSAGE = (
    'backup_ttl must be a positive Go duration using h/m/s units, e.g. "720h"'
)

_BACKUP_TTL_TOO_LARGE_MESSAGE = (
    f"backup_ttl must not exceed {MAX_BACKUP_TTL_HOURS}h — Go durations are "
    'int64 nanoseconds, so a larger value cannot be parsed (e.g. "720h")'
)

# Provenance of a resolved TTL: the scope that supplied the value, or
# ``"default"`` when no scope set a policy.
BackupTtlSource = Literal["deployment", "environment", "cluster", "default"]


def validate_backup_ttl(value: str) -> str:
    """Return *value* unchanged if it is a valid backup TTL, else raise.

    Args:
        value: Candidate retention duration, e.g. ``"720h"``.

    Returns:
        The validated value, unchanged (no normalisation — Velero receives
        exactly what the operator wrote).

    Raises:
        ValueError: The value is not a strictly positive ``h``/``m``/``s`` Go
            duration, or it exceeds :data:`MAX_BACKUP_TTL_HOURS`. The message
            names the field and hints the syntax so it stays actionable after
            the config validators wrap it into an ``Invalid*ContextError``.
    """
    # ``fullmatch`` on top of the pattern's own ``\A``/``\Z`` anchors — either
    # alone rejects the trailing-newline case that ``match`` + ``$`` admitted.
    if not isinstance(value, str) or not BACKUP_TTL_PATTERN.fullmatch(value):
        raise ValueError(_INVALID_BACKUP_TTL_MESSAGE)
    components = _BACKUP_TTL_COMPONENT_RE.findall(value)
    # Syntax alone admits ``0h`` / ``0h0m0s``, which Velero would read as "no
    # retention at all". Require at least one non-zero component.
    if not any(float(amount) > 0 for amount, _unit in components):
        raise ValueError(_INVALID_BACKUP_TTL_MESSAGE)
    total_seconds = sum(
        float(amount) * _BACKUP_TTL_UNIT_SECONDS[unit] for amount, unit in components
    )
    if total_seconds > _MAX_BACKUP_TTL_SECONDS:
        raise ValueError(_BACKUP_TTL_TOO_LARGE_MESSAGE)
    return value


def resolve_backup_ttl(
    deployment_config: dict[str, Any] | None,
    environment_config: dict[str, Any] | None,
    cluster_config: dict[str, Any] | None,
) -> tuple[str, BackupTtlSource]:
    """Resolve the retention TTL for a backup, deepest scope wins.

    Precedence is deployment → environment → cluster → built-in default. A
    scope contributes only when its persisted config carries a ``backup_ttl``
    that is a string passing :func:`validate_backup_ttl`; a scope that omits
    the key, stores ``None``, or stores something unusable is transparent and
    resolution falls through to the next one.

    The validity re-check is defence in depth against a value that never
    crossed a config validator — a hand-edited row or a restored dump holding
    the JSON number ``720`` would otherwise reach Velero as ``spec.ttl: "720"``
    and fail the backup asynchronously. Falling through loudly (WARNING naming
    the scope and the value) is safer than raising: a single corrupt row must
    not make backups impossible.

    Args:
        deployment_config: The deployment's persisted ``config`` dict.
        environment_config: The environment's persisted ``config`` dict.
        cluster_config: The cluster's persisted ``config`` dict.

    Returns:
        A ``(ttl, source_scope)`` pair. ``source_scope`` is the scope that
        supplied the value, or ``"default"`` when none did.
    """
    scopes: tuple[tuple[BackupTtlSource, dict[str, Any] | None], ...] = (
        ("deployment", deployment_config),
        ("environment", environment_config),
        ("cluster", cluster_config),
    )
    for scope, config in scopes:
        if not config:
            continue
        value = config.get("backup_ttl")
        if value is None:
            continue
        if not isinstance(value, str):
            logger.warning(
                "Ignoring unusable backup_ttl at {scope} scope: expected a "
                "string, got {type_name} {value!r} — falling through to the "
                "next scope",
                scope=scope,
                type_name=type(value).__name__,
                value=value,
            )
            continue
        try:
            validate_backup_ttl(value)
        except ValueError as exc:
            logger.warning(
                "Ignoring invalid backup_ttl {value!r} at {scope} scope "
                "({reason}) — falling through to the next scope",
                value=value,
                scope=scope,
                reason=exc,
            )
            continue
        return value, scope
    return DEFAULT_BACKUP_TTL, "default"
