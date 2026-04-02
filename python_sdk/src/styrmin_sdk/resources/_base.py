"""Base resource with shared transport reference."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel

from styrmin_sdk.exceptions import OperationFailedError, ResourceAlreadyExistsError, ResourceNotFoundError

if TYPE_CHECKING:
    from styrmin_sdk._transport import Transport

type JsonValue = dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None

_T = TypeVar("_T", bound=BaseModel)


@dataclass
class BaseResource:
    _transport: Transport = field(repr=False)

    @staticmethod
    def _parse(outer_type: type[BaseModel], data: dict[str, Any], field_name: str, inner_type: type[_T]) -> _T:
        """Validate data with the generated outer wrapper type and extract the inner field.

        The generated outer types have Optional inner fields (because GraphQL allows
        null on error), but after _check_graphql_errors the field is guaranteed non-None.
        """
        validated = outer_type.model_validate(data)
        result = getattr(validated, field_name)
        if not isinstance(result, inner_type):
            msg = f"Expected '{inner_type.__name__}' for '{field_name}' in {outer_type.__name__}, got {type(result).__name__}"
            raise TypeError(msg)
        return result

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
