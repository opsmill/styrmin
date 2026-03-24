"""Base resource with shared transport reference."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from styrmin_sdk.exceptions import OperationFailedError, ResourceAlreadyExistsError, ResourceNotFoundError

if TYPE_CHECKING:
    from styrmin_sdk._transport import Transport

type JsonValue = dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None


@dataclass
class BaseResource:
    _transport: Transport = field(repr=False)

    @staticmethod
    def _check_graphql_errors(result: dict[str, Any]) -> None:
        """Raise the appropriate SDK exception if the result contains GraphQL errors."""
        errors = result.get("errors")
        if not errors:
            return

        error = errors[0]
        message = error.get("message", "Unknown error")
        extensions = error.get("extensions", {})
        code = extensions.get("code", "")

        if code == "NOT_FOUND":
            raise ResourceNotFoundError(message, code)
        if code == "ALREADY_EXISTS":
            raise ResourceAlreadyExistsError(message, code)
        raise OperationFailedError(message, code)
