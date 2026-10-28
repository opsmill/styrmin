from collections.abc import Mapping
from typing import Any, Generic, TypeVar

from pydantic import ValidationError

from styrmin_sdk.driver_format.errors import DeserializationError
from styrmin_sdk.driver_format.models.resources.code import ActionsCode
from styrmin_sdk.driver_format.models.resources.driver import DriverSpec
from styrmin_sdk.driver_format.models.structure.resource import Role

ModelType = TypeVar("ModelType", DriverSpec, ActionsCode)


class Deserializer(Generic[ModelType]):
    """The abstract serializer class."""

    model: type[ModelType]

    def deserialize(self, data: Any) -> ModelType:
        """Serialize the object."""
        if not isinstance(data, Mapping):
            # The message of Python's TypeError would name the module of the model class.
            raise DeserializationError(
                f"Provided data is not of expected type: {self.model.__name__}() argument after ** "
                f"must be a mapping, not {type(data).__name__}"
            )
        try:
            return self.model(**data)
        except TypeError as err:
            raise DeserializationError(f"Provided data is not of expected type: {err!s}") from err


def _field_path(loc: tuple[int | str, ...]) -> str:
    """``("spec", "info", "links", 0)`` -> ``spec.info.links[0]``."""
    path = ""
    for part in loc:
        path += f"[{part}]" if isinstance(part, int) else f".{part}" if path else part
    return path


def validation_error_fields(err: ValidationError) -> list[tuple[tuple[int | str, ...], str]]:
    """Each invalid field: its location, and its path, the problem and the value found."""
    fields = []
    for error in err.errors(include_url=False):
        found = error.get("input")
        shown = error["type"] != "missing" and isinstance(found, (str, int, float))
        suffix = f" (found {found!r})" if shown else ""
        fields.append((tuple(error["loc"]), f"{_field_path(error['loc'])}: {error['msg']}{suffix}"))
    return fields


def format_validation_error(err: ValidationError) -> str:
    """One line per invalid field: its path, the problem and the value found."""
    return "\n".join(f"- {line}" for _loc, line in validation_error_fields(err))


class DriverSpecDeserializer(Deserializer[DriverSpec]):
    model = DriverSpec

    def deserialize(self, data: Any) -> DriverSpec:
        try:
            return super().deserialize(data)
        except ValidationError as err:
            raise DeserializationError(f"The driver specification is invalid:\n{format_validation_error(err)}") from err


def get_deserializer(role: Role) -> Deserializer | None:
    """Get the deserializer based on the role.

    Args:
        role (Role): The role.

    Returns:
        Deserializer: The deserializer.
    """
    match role:
        case Role.DRIVER_SPEC:
            return DriverSpecDeserializer()
        case Role.VALUES_TEMPLATE | Role.ACTIONS_CODE:
            return None
        case _:
            raise ValueError(f"Unsupported role: {role!r}")
