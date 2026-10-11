from typing import Any, Generic, Type, TypeVar

from pydantic import ValidationError

from styrmin_backend.services.driver.models.resources.code import ActionsCode
from styrmin_backend.services.driver.models.resources.driver import DriverSpec
from styrmin_backend.services.driver.models.structure.resource import Role

from .exceptions import DeserializationError

ModelType = TypeVar("ModelType", DriverSpec, ActionsCode)


class Deserializer(Generic[ModelType]):
    """The abstract serializer class."""

    model: Type[ModelType]

    def deserialize(self, data: Any) -> ModelType:
        """Serialize the object."""
        try:
            return self.model(**data)
        except TypeError as err:
            raise DeserializationError(
                f"Provided data is not of expected type: {err!s}"
            ) from err


def _field_path(loc: tuple[int | str, ...]) -> str:
    """``("spec", "info", "links", 0)`` -> ``spec.info.links[0]``."""
    path = ""
    for part in loc:
        path += f"[{part}]" if isinstance(part, int) else f".{part}" if path else part
    return path


def format_validation_error(err: ValidationError) -> str:
    """One line per invalid field: its path, the problem and the value found."""
    lines = []
    for error in err.errors(include_url=False):
        found = error.get("input")
        shown = error["type"] != "missing" and isinstance(found, (str, int, float))
        suffix = f" (found {found!r})" if shown else ""
        lines.append(f"- {_field_path(error['loc'])}: {error['msg']}{suffix}")
    return "\n".join(lines)


class DriverSpecDeserializer(Deserializer[DriverSpec]):
    model = DriverSpec

    def deserialize(self, data: Any) -> DriverSpec:
        try:
            return super().deserialize(data)
        except ValidationError as err:
            raise DeserializationError(
                f"The driver specification is invalid:\n{format_validation_error(err)}"
            ) from err


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
