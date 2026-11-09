"""Re-export of ``styrmin_sdk.driver_format.context.exceptions``, plus scheduling errors.

The context errors moved to the SDK (ADR-0089). The scheduling-related service errors
are re-exported here, as before, so the resolvers and their callers can raise them
under one import path (FR-003, FR-005, FR-001d).
"""

from styrmin_sdk.driver_format.context.exceptions import (
    ContextError,
    InvalidApplicationContextError,
    InvalidClusterContextError,
    InvalidContextError,
    InvalidDeploymentContextError,
    InvalidEnvironmentContextError,
)

from styrmin_backend.services.exceptions import (
    InvalidSchedulingConfigError,
    UnclonedDeploymentReferenceError,
    UnknownComponentInConfigError,
    UnresolvableAffinityReferenceError,
)

__all__ = [
    "ContextError",
    "InvalidApplicationContextError",
    "InvalidClusterContextError",
    "InvalidContextError",
    "InvalidDeploymentContextError",
    "InvalidEnvironmentContextError",
    "InvalidSchedulingConfigError",
    "UnclonedDeploymentReferenceError",
    "UnknownComponentInConfigError",
    "UnresolvableAffinityReferenceError",
]
