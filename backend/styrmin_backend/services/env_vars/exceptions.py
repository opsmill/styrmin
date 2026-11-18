"""Re-export of ``styrmin_sdk.driver_format.context.validation.env_vars.exceptions``.

The module moved to the SDK, which the server, the agent and styrmin-driver share
(ADR-0089). This path keeps the backend's imports working.
"""

from styrmin_sdk.driver_format.context.validation.env_vars.exceptions import (
    ComponentContainerNotDeclaredError,
    ComponentContainerSlot,
    DriverEnvVarDocComponentMismatchError,
    DriverEnvVarDocLevelMismatchError,
    DuplicateComponentNameError,
    DuplicateEnvVarNameError,
    EnvVarSizeLimitExceededError,
    InvalidEnvVarNameError,
    InvalidEnvVarValueError,
    UnknownComponentEnvVarError,
)

__all__ = [
    "ComponentContainerNotDeclaredError",
    "ComponentContainerSlot",
    "DriverEnvVarDocComponentMismatchError",
    "DriverEnvVarDocLevelMismatchError",
    "DuplicateComponentNameError",
    "DuplicateEnvVarNameError",
    "EnvVarSizeLimitExceededError",
    "InvalidEnvVarNameError",
    "InvalidEnvVarValueError",
    "UnknownComponentEnvVarError",
]
