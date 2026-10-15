"""Exception types for deployment-parameter handling.

Every exception subclasses :class:`ServiceError` (Constitution §IV) and carries
a stable ``error_code`` that the GraphQL ``StructuredErrorExtension`` projects
onto ``extensions.code``. Codes match ``data-model.md`` §3.
"""

from __future__ import annotations

import json
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


MIGRATION_GUIDE_URL = (
    "https://styrmin.pages.dev/docs/drivers/migrating-replica-parameters"
)


class RetiredParameterValueError(ServiceError):
    """A driver version change keeps a changed value of a parameter the target no longer declares.

    Only a value equal (same type and value) to the current driver version's default is dropped
    on a version change (023 FR-010); any other value raises this error.
    """

    error_code = "RETIRED_PARAMETER_VALUE"
    default_message = (
        "The target driver version no longer declares a parameter this deployment sets"
    )

    def __init__(
        self,
        message: str = "",
        *,
        parameter_name: str = "",
        value: Any = None,
        default: Any = None,
        checked_against: str = "",
    ) -> None:
        self.parameter_name = parameter_name
        self.value = value
        self.default = default
        self.checked_against = checked_against
        super().__init__(
            message
            or (
                f"Parameter {parameter_name!r} is not declared by "
                f"{checked_against or 'the target driver version'}, and this deployment sets "
                f"it to {json.dumps(value, default=str)} "
                f"(default {json.dumps(default, default=str)}). Remove the "
                "parameter or reset it to its default, then change the driver version again. "
                "If it set a replica count, carry the value over as a replica override on the "
                f"component first. See {MIGRATION_GUIDE_URL}"
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {
            "parameter_name": self.parameter_name,
            "value": self.value,
            "default": self.default,
            "checked_against": self.checked_against,
        }
