"""Exception types for the per-service ingress override (#598, contracts/graphql-and-manifest.md).

Every exception subclasses :class:`ServiceError` (Constitution §IV) and carries a stable
``error_code`` that the GraphQL ``StructuredErrorExtension`` projects onto ``extensions.code``.
"""

from __future__ import annotations

from typing import Any

from styrmin_backend.services.exceptions import ServiceError


class DuplicateServiceNameError(ServiceError):
    """The ``services`` input list contains the same driver service name twice.

    Detected before the list is flattened to the stored ``dict`` keyed on the driver
    service name, so the second row cannot silently replace the first.
    """

    error_code = "DUPLICATE_SERVICE_NAME"
    default_message = "Duplicate service name in input list"

    def __init__(self, message: str = "", name: str = "") -> None:
        self.name = name
        super().__init__(
            message
            or (
                f"Service name {name!r} appears more than once in the services "
                "list; remove the duplicate before submitting."
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {"name": self.name}
