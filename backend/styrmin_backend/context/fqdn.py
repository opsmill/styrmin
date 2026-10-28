"""Re-export of ``styrmin_sdk.driver_format.context.fqdn``.

The module moved to the SDK, which the server, the agent and styrmin-driver share
(ADR-0089). This path keeps the backend's imports working.
"""

from styrmin_sdk.driver_format.context.fqdn import (
    _DEFAULT_PORTS,
    _DNS_MAX_LABEL_LENGTH,
    _combine_labels,
    compute_external_url,
    compute_human_readable_fqdn,
    compute_primary_fqdn,
    to_fqdn_label,
)

__all__ = [
    "compute_external_url",
    "compute_human_readable_fqdn",
    "compute_primary_fqdn",
    "to_fqdn_label",
    "_DEFAULT_PORTS",
    "_DNS_MAX_LABEL_LENGTH",
    "_combine_labels",
]
