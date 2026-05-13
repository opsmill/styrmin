"""Loguru sensitive-field redaction patcher. See ADR-019 §"Password handling"."""

from __future__ import annotations

from typing import Any

REDACTED = "<redacted>"

SENSITIVE_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "password",
        "password_hash",
        "passwordHash",
        "token",
        "raw_token",
        "token_hash",
        "session_token",
        "styrmin_session",
    }
)


def _redact_in_place(payload: Any) -> None:
    if isinstance(payload, dict):
        for key in list(payload):
            if key in SENSITIVE_FIELD_NAMES:
                payload[key] = REDACTED
            else:
                _redact_in_place(payload[key])
    elif isinstance(payload, list):
        for item in payload:
            _redact_in_place(item)


def redact(record: dict[str, Any]) -> None:
    """Loguru ``patcher`` that redacts sensitive fields from ``record["extra"]``.

    The contract is exact-name match against ``SENSITIVE_FIELD_NAMES``. Fields
    are redacted recursively at any nesting depth in ``extra``. Adding a new
    sensitive name is a strictly additive change here — call sites do not need
    to know about the redaction.
    """
    extra = record.get("extra")
    if extra is not None:
        _redact_in_place(extra)
