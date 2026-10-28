"""Re-export of ``styrmin_sdk.driver_format.context.models.services``.

The module moved to the SDK, which the server, the agent and styrmin-driver share
(ADR-0089). This path keeps the backend's imports working.
"""

from styrmin_sdk.driver_format.context.models.services import (
    ServiceReference,
)

__all__ = [
    "ServiceReference",
]
