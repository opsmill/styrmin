"""Validators for deployment environment variables.

Hosts the input-shape validation that runs at the GraphQL mutation boundary
and inside Pydantic field validators on the config models. Keeps every rule
from FR-006..FR-011 in one place so the shape is consistent across:

* per-input-scope validation (``EnvironmentConfig.env_vars`` /
  ``DeploymentConfig.env_vars`` / per-component blocks);
* the input-list duplicate-name check that runs **before** the dict is
  constructed (FR-009).

Size accounting choice: the per-scope 256 KiB cap and the per-value 64 KiB
cap are computed as raw UTF-8 byte sums (``len(s.encode("utf-8"))``) rather
than via ``json.dumps`` — JSON delimiters and quoting overhead would make the
budget shift with serialisation choices and the user-facing limit should
reflect the payload itself. For per-scope totals the formula is
``sum(len(k.encode("utf-8")) + len(v.encode("utf-8")) for k, v in mapping.items())``.
The same formula is reused by the resolver's post-merge cap (FR-008a).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from typing import Any

from styrmin_sdk.driver_format.context.validation.env_vars.exceptions import (
    DuplicateEnvVarNameError,
    EnvVarSizeLimitExceededError,
    InvalidEnvVarNameError,
    InvalidEnvVarValueError,
)

logger = logging.getLogger(__name__)

# FR-006: POSIX-style env var name regex.
_ENV_VAR_NAME_RE: re.Pattern[str] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# FR-011: families that warrant a soft warning (no rejection) — operators
# may legitimately want to set ``LD_LIBRARY_PATH`` for a niche use case but
# overriding ``PATH`` blindly tends to brick containers, so we log a hint.
_RISKY_ENV_VAR_NAME_RE: re.Pattern[str] = re.compile(r"^(PATH|LD_.*|PYTHONPATH|RUBYLIB|NODE_PATH|JAVA_TOOL_OPTIONS)$")

# FR-007: 64 KiB per value.
PER_VALUE_BYTE_CAP: int = 64 * 1024  # 65536
# FR-008: per-scope 100 entries.
PER_SCOPE_ENTRY_CAP: int = 100
# FR-008: per-scope 256 KiB total serialised payload.
PER_SCOPE_BYTE_CAP: int = 256 * 1024  # 262144


def _utf8_bytes(value: str) -> int:
    return len(value.encode("utf-8"))


def _serialised_dict_bytes(mapping: Mapping[str, str]) -> int:
    """Return the per-scope byte budget for *mapping*.

    See module docstring for the choice (raw UTF-8 sum, no JSON overhead).
    """
    return sum(_utf8_bytes(k) + _utf8_bytes(v) for k, v in mapping.items())


def validate_env_var_name(name: str, scope: str | None = None) -> None:
    """Validate a single env var *name*.

    Raises :class:`InvalidEnvVarNameError` when the regex fails. Emits a
    ``logger.warning("env_var_potentially_risky_name ...")`` when the name
    matches the risky family (FR-011 soft warning, no rejection).
    """
    if not _ENV_VAR_NAME_RE.match(name):
        raise InvalidEnvVarNameError(name=name, scope=scope)
    if _RISKY_ENV_VAR_NAME_RE.match(name):
        logger.warning(
            "env_var_potentially_risky_name name=%s scope=%s",
            name,
            scope,
        )


def validate_env_var_value(name: str, value: str, scope: str | None = None) -> None:
    """Validate a single env var *value* against the per-value byte cap.

    Type-checks *value* at the entry point (FR-008..FR-011 / 011-US3): a
    non-string ``value`` raises :class:`InvalidEnvVarValueError` BEFORE any
    UTF-8 encoding so the JSON config write path surfaces a typed code at the
    GraphQL boundary instead of an ``AttributeError`` 500. Note that ``bool``
    is a subclass of ``int`` (not ``str``) and ``bytes`` defines ``.encode()``
    but is not ``str`` — both are correctly rejected by ``isinstance(value,
    str)``.

    Empty string is accepted (FR-007). Values whose UTF-8 encoding exceeds
    :data:`PER_VALUE_BYTE_CAP` raise :class:`EnvVarSizeLimitExceededError`
    with ``name`` and ``bytes`` populated.
    """
    if not isinstance(value, str):
        raise InvalidEnvVarValueError(
            name=name,
            value_type=type(value).__name__,
            scope=scope,
        )
    size = _utf8_bytes(value)
    if size > PER_VALUE_BYTE_CAP:
        raise EnvVarSizeLimitExceededError(
            scope=scope or "",
            name=name,
            bytes=size,
            cap=PER_VALUE_BYTE_CAP,
        )


def validate_env_vars_dict(scope: str, mapping: Mapping[str, str]) -> dict[str, str]:
    """Validate *mapping* against every input-scope rule and return a plain dict.

    Enforces, in order:

    1. Per-scope entry-count cap (FR-008).
    2. Per-key name regex (FR-006) and per-value byte cap (FR-007), with the
       risky-name warning interleaved (FR-011).
    3. Per-scope serialised byte cap (FR-008).

    The returned ``dict`` is a fresh copy so callers (e.g. Pydantic field
    validators) can safely mutate it.
    """
    if len(mapping) > PER_SCOPE_ENTRY_CAP:
        raise EnvVarSizeLimitExceededError(
            scope=scope,
            entries=len(mapping),
            cap=PER_SCOPE_ENTRY_CAP,
        )

    out: dict[str, str] = {}
    for name, value in mapping.items():
        validate_env_var_name(name, scope=scope)
        validate_env_var_value(name, value, scope=scope)
        out[name] = value

    total_bytes = _serialised_dict_bytes(out)
    if total_bytes > PER_SCOPE_BYTE_CAP:
        raise EnvVarSizeLimitExceededError(
            scope=scope,
            bytes=total_bytes,
            cap=PER_SCOPE_BYTE_CAP,
        )
    return out


def validate_env_vars_input_list(
    items: Iterable[Any],
    scope: str,
) -> dict[str, str]:
    """Validate an input list of name/value entries and return a deduped dict.

    *items* may be:

    * an iterable of ``(name, value)`` tuples, or
    * an iterable of ``Mapping[str, str]`` objects with ``name`` and ``value``
      keys (e.g. the eventual ``EnvVarInput`` Strawberry type — currently
      accepted via duck typing because the GraphQL input type lands in the
      US1 phase), or
    * an iterable of objects exposing ``name`` and ``value`` attributes.

    Duplicate names within a single input list raise
    :class:`DuplicateEnvVarNameError` **before** the dict is built (FR-009),
    so the caller never observes a silently-deduped payload. After dedup the
    full set of dict-level rules from :func:`validate_env_vars_dict` runs.
    """
    seen: dict[str, str] = {}
    for item in items:
        name, value = _extract_name_value(item)
        if name in seen:
            raise DuplicateEnvVarNameError(name=name, scope=scope)
        seen[name] = value
    return validate_env_vars_dict(scope, seen)


def _extract_name_value(item: Any) -> tuple[str, str]:
    if isinstance(item, tuple) and len(item) == 2:
        return str(item[0]), str(item[1])
    if isinstance(item, Mapping):
        return str(item["name"]), str(item["value"])
    name = getattr(item, "name", None)
    value = getattr(item, "value", None)
    if name is None or value is None:
        raise TypeError(
            "validate_env_vars_input_list items must be (name, value) tuples, "
            "Mapping with 'name'/'value' keys, or objects with .name/.value "
            f"attributes; got {type(item).__name__}."
        )
    return str(name), str(value)
