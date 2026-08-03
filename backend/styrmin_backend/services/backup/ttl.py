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
units — the subset Velero's ``spec.ttl`` parses that is meaningful for backup
retention. Compounds (``1h30m``) and decimals (``1.5h``) are valid Go durations
and are accepted; there is deliberately no day unit (Go has none, so ``30d``
would be rejected by Velero at apply time) and no bare integer (``720`` is
ambiguous).
"""

from __future__ import annotations

import re
from typing import Any, Literal

# The built-in retention applied when no scope sets a policy. Pinned by
# ``backend/tests/unit/services/test_backup_ttl_resolution.py`` — the single
# home of this literal.
DEFAULT_BACKUP_TTL = "720h"

# Strictly positive Go duration restricted to h/m/s units; one or more
# ``<number><unit>`` components (``720h``, ``1h30m``, ``1.5h``). Case-sensitive:
# ``24H`` is not a Go duration.
BACKUP_TTL_PATTERN: re.Pattern[str] = re.compile(r"^(\d+(\.\d+)?(h|m|s))+$")

# Individual ``<number><unit>`` components, used to reject all-zero durations
# (``0h``, ``0h0m0s``) that match the syntax but express no retention.
_BACKUP_TTL_COMPONENT_RE: re.Pattern[str] = re.compile(r"(\d+(?:\.\d+)?)(h|m|s)")

_INVALID_BACKUP_TTL_MESSAGE = (
    'backup_ttl must be a positive Go duration using h/m/s units, e.g. "720h"'
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
            duration. The message names the field and hints the syntax so it
            stays actionable after the config validators wrap it into an
            ``Invalid*ContextError``.
    """
    if not isinstance(value, str) or not BACKUP_TTL_PATTERN.match(value):
        raise ValueError(_INVALID_BACKUP_TTL_MESSAGE)
    # Syntax alone admits ``0h`` / ``0h0m0s``, which Velero would read as "no
    # retention at all". Require at least one non-zero component.
    if not any(
        float(amount) > 0 for amount, _unit in _BACKUP_TTL_COMPONENT_RE.findall(value)
    ):
        raise ValueError(_INVALID_BACKUP_TTL_MESSAGE)
    return value


def resolve_backup_ttl(
    deployment_config: dict[str, Any] | None,
    environment_config: dict[str, Any] | None,
    cluster_config: dict[str, Any] | None,
) -> tuple[str, BackupTtlSource]:
    """Resolve the retention TTL for a backup, deepest scope wins.

    Precedence is deployment → environment → cluster → built-in default. A
    scope contributes only when its persisted config carries a non-null
    ``backup_ttl``; a scope that omits the key (or stores ``None``) is
    transparent and resolution falls through to the next one.

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
        if value is not None:
            return str(value), scope
    return DEFAULT_BACKUP_TTL, "default"
