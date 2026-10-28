"""Re-export of ``styrmin_sdk.driver_format.models.resources._shared``.

The module moved to the SDK, which the server, the agent and styrmin-driver share
(ADR-0089). This path keeps the backend's imports working.
"""

from styrmin_sdk.driver_format.models.resources._shared import (
    Kind,
)

__all__ = [
    "Kind",
]
