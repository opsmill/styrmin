"""Re-export of ``styrmin_sdk.driver_format.context.validation.image_overrides.reference``.

The module moved to the SDK, which the server, the agent and styrmin-driver share
(ADR-0089). This path keeps the backend's imports working.
"""

from styrmin_sdk.driver_format.context.validation.image_overrides.reference import (
    _ALPHANUMERIC,
    _DIGEST,
    _DOMAIN_COMPONENT,
    _HOST,
    _NAME,
    _PATH_COMPONENT,
    _REFERENCE_RE,
    _TAG,
    _TEMPLATE_MARKERS,
    APP_VERSION_TOKEN_RE,
    NAME_MAX_LENGTH,
    PLACEHOLDER_VERSION,
    _check_resolved,
    _require_string,
    _validate,
    has_app_version_token,
    substitute_app_version,
    validate_reference,
    validate_stored_reference,
)

__all__ = [
    "APP_VERSION_TOKEN_RE",
    "NAME_MAX_LENGTH",
    "PLACEHOLDER_VERSION",
    "has_app_version_token",
    "substitute_app_version",
    "validate_reference",
    "validate_stored_reference",
    "_ALPHANUMERIC",
    "_DIGEST",
    "_DOMAIN_COMPONENT",
    "_HOST",
    "_NAME",
    "_PATH_COMPONENT",
    "_REFERENCE_RE",
    "_TAG",
    "_TEMPLATE_MARKERS",
    "_check_resolved",
    "_require_string",
    "_validate",
]
