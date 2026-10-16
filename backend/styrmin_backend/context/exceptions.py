class ContextError(Exception):
    """Base class for exceptions in this module."""


class InvalidClusterContextError(ContextError):
    """The cluster context is invalid."""


class InvalidEnvironmentContextError(ContextError):
    """The environment context is invalid."""


class InvalidApplicationContextError(ContextError):
    """The application context is invalid."""


class InvalidDeploymentContextError(ContextError):
    """The instance context is invalid."""


class InvalidContextError(ContextError):
    """The context is invalid."""


# Re-export scheduling-related service errors so the resolvers package can
# raise them under a consistent import path (FR-003, FR-005, FR-001d).
from styrmin_backend.services.exceptions import (  # noqa: E402
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
