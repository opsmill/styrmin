"""Re-export of ``styrmin_sdk.driver_format.models.resources.driver``.

The module moved to the SDK, which the server, the agent and styrmin-driver share
(ADR-0089). This path keeps the backend's imports working.
"""

from styrmin_sdk.driver_format.models.resources.driver import (
    _CONTAINER_NAME_MAX_LENGTH,
    _CONTAINER_NAME_RE,
    _HTTP_URL,
    ArbitrarySectionModel,
    Components,
    DriverSpec,
    Helm,
    HelmSettings,
    Identifier,
    Info,
    InfoLink,
    LabelIdentifier,
    Metadata,
    Specification,
    _link_problem,
    _url_problem,
)

__all__ = [
    "ArbitrarySectionModel",
    "Components",
    "DriverSpec",
    "Helm",
    "HelmSettings",
    "Identifier",
    "Info",
    "InfoLink",
    "LabelIdentifier",
    "Metadata",
    "Specification",
    "_CONTAINER_NAME_MAX_LENGTH",
    "_CONTAINER_NAME_RE",
    "_HTTP_URL",
    "_link_problem",
    "_url_problem",
]
