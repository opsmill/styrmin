"""Re-export of ``styrmin_sdk.driver_format.context.validation.replicas.exceptions``.

The module moved to the SDK, which the server, the agent and styrmin-driver share
(ADR-0089). This path keeps the backend's imports working.
"""

from styrmin_sdk.driver_format.context.validation.replicas.exceptions import (
    InvalidReplicaCountError,
    ReplicaCountAboveMaximumError,
    SingletonReplicaOverrideError,
    UnknownComponentReplicaOverrideError,
)

__all__ = [
    "InvalidReplicaCountError",
    "ReplicaCountAboveMaximumError",
    "SingletonReplicaOverrideError",
    "UnknownComponentReplicaOverrideError",
]
