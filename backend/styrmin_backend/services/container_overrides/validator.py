"""Re-export of ``styrmin_sdk.driver_format.context.validation.container_overrides.validator``.

The module moved to the SDK, which the server, the agent and styrmin-driver share
(ADR-0089). This path keeps the backend's imports working.
"""

from styrmin_sdk.driver_format.context.validation.container_overrides.validator import (
    CONTAINER_OVERRIDE_BYTE_CAP,
    CONTAINER_OVERRIDE_MAX_ELEMENTS,
    ContainerOverrideField,
    _raise,
    validate_container_override,
)

__all__ = [
    "CONTAINER_OVERRIDE_BYTE_CAP",
    "CONTAINER_OVERRIDE_MAX_ELEMENTS",
    "ContainerOverrideField",
    "validate_container_override",
    "_raise",
]
