"""Image-reference grammar and ``{{ app.version }}`` substitution (018, research D-006 to D-008).

The grammar follows distribution/reference: ``[domain[:port]/]path[:tag][@algorithm:hex]``,
with an explicit tag or digest required. ``frontend/src/lib/image-reference.ts`` mirrors it;
both test suites read ``frontend/src/lib/image-reference.vectors.json``.
"""

from __future__ import annotations

import re

from styrmin_backend.services.image_overrides.exceptions import (
    ImageReferenceReason,
    InvalidImageReferenceError,
)

# ASCII whitespace only, so the token matches the same strings in Python and the frontend.
APP_VERSION_TOKEN_RE = re.compile(r"\{\{\s*app\.version\s*\}\}", re.ASCII)
PLACEHOLDER_VERSION = "0"
NAME_MAX_LENGTH = 255

_TEMPLATE_MARKERS = ("{{", "}}", "{%", "%}")

_ALPHANUMERIC = r"[a-z0-9]+"
_PATH_COMPONENT = rf"{_ALPHANUMERIC}(?:(?:[._]|__|-+){_ALPHANUMERIC})*"
_DOMAIN_COMPONENT = r"(?:[a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9])"
_HOST = rf"(?:{_DOMAIN_COMPONENT}(?:\.{_DOMAIN_COMPONENT})*|\[[a-fA-F0-9:]+\])"
_NAME = rf"(?:{_HOST}(?::[0-9]+)?/)?{_PATH_COMPONENT}(?:/{_PATH_COMPONENT})*"
_TAG = r"\w[\w.-]{0,127}"
_DIGEST = r"[A-Za-z][A-Za-z0-9]*(?:[-_+.][A-Za-z][A-Za-z0-9]*)*:[0-9a-fA-F]{32,}"
# Matched with fullmatch: "$" would accept a trailing newline. re.ASCII keeps \w to [A-Za-z0-9_].
_REFERENCE_RE = re.compile(
    rf"(?P<name>{_NAME})(?::(?P<tag>{_TAG}))?(?:@(?P<digest>{_DIGEST}))?", re.ASCII
)


def substitute_app_version(ref: str, version: str) -> str:
    """Replace every ``{{ app.version }}`` token (inner whitespace optional) with ``version``."""
    return APP_VERSION_TOKEN_RE.sub(lambda _match: version, ref)


def has_app_version_token(ref: str) -> bool:
    """Return whether ``ref`` contains at least one ``{{ app.version }}`` token."""
    return APP_VERSION_TOKEN_RE.search(ref) is not None


def _check_resolved(resolved: str) -> ImageReferenceReason | None:
    """Return why a fully substituted reference is invalid, or ``None`` when it is valid."""
    if any(marker in resolved for marker in _TEMPLATE_MARKERS):
        return "template_expression"
    match = _REFERENCE_RE.fullmatch(resolved)
    if match is None or len(match.group("name")) > NAME_MAX_LENGTH:
        return "grammar"
    if match.group("tag") is None and match.group("digest") is None:
        return "missing_tag_or_digest"
    return None


def _require_string(ref: object, component_name: str | None) -> str:
    if not isinstance(ref, str):
        raise InvalidImageReferenceError(
            reason="grammar",
            reference=repr(ref),
            component_name=component_name,
            detail=f"expected a string, got {type(ref).__name__}",
        )
    return ref


def _validate(
    ref: str, *, version: str, component_name: str | None, report_version: bool
) -> str:
    has_token = has_app_version_token(ref)
    resolved = substitute_app_version(ref, version)
    reason = _check_resolved(resolved)
    if reason is None:
        return resolved
    placeholder_valid = (
        _check_resolved(substitute_app_version(ref, PLACEHOLDER_VERSION)) is None
    )
    if has_token and version != PLACEHOLDER_VERSION and placeholder_valid:
        reason = "after_substitution"
    raise InvalidImageReferenceError(
        reason=reason,
        reference=ref,
        component_name=component_name,
        application_version=version if has_token and report_version else None,
        resolved_reference=resolved,
    )


def validate_reference(
    ref: str, *, version: str, component_name: str | None = None
) -> str:
    """Validate ``ref`` against ``version`` and return the resolved reference.

    Checks run in order: template expressions left after substitution, grammar, then an explicit
    tag or digest. A reference that is valid with the placeholder version but not with ``version``
    fails with reason ``after_substitution``. Raises :class:`InvalidImageReferenceError`.
    """
    ref = _require_string(ref, component_name)
    return _validate(
        ref, version=version, component_name=component_name, report_version=True
    )


def validate_stored_reference(
    ref: object, *, component_name: str | None = None
) -> str | None:
    """Validate a stored override with the placeholder version and return it unchanged.

    ``None`` (no override) passes through, so this can back a ``mode="before"`` field validator.
    """
    if ref is None:
        return None
    stored = _require_string(ref, component_name)
    _validate(
        stored,
        version=PLACEHOLDER_VERSION,
        component_name=component_name,
        report_version=False,
    )
    return stored
