"""Re-export of ``styrmin_sdk.driver_format.models.resources.services``.

The module moved to the SDK, which the server, the agent and styrmin-driver share
(ADR-0089). This path keeps the backend's imports working.
"""

from styrmin_sdk.driver_format.models.resources.services import (
    _DNS_LABEL_RE,
    ServiceDefinition,
    ServiceKind,
    ServiceScope,
    validate_dns_label,
    validate_service_names_unique,
)

__all__ = [
    "ServiceDefinition",
    "ServiceKind",
    "ServiceScope",
    "validate_dns_label",
    "validate_service_names_unique",
    "_DNS_LABEL_RE",
]
