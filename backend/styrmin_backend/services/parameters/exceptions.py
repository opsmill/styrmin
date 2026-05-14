"""Exception types for deployment-parameter handling.

Every exception subclasses :class:`ServiceError` (Constitution §IV) and carries
a stable ``error_code`` that the GraphQL ``StructuredErrorExtension`` projects
onto ``extensions.code``. Codes match ``data-model.md`` §3.
"""

from __future__ import annotations

from typing import Any

from styrmin_backend.services.exceptions import ServiceError


class DuplicateParameterNameError(ServiceError):
    """A single ``parameters`` input list contains the same name more than once.

    Detected before the list is flattened to the persisted ``dict[str, Any]``
    shape so the typed error code reaches the GraphQL boundary intact
    (FR-009).
    """

    error_code = "DUPLICATE_PARAMETER_NAME"
    default_message = "Duplicate parameter name in input list"

    def __init__(
        self,
        message: str = "",
        name: str = "",
    ) -> None:
        self.name = name
        super().__init__(
            message
            or (
                f"Parameter name {name!r} appears more than once in the input "
                "list; remove the duplicate before submitting."
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {"name": self.name}
