from typing import Any, Generic, Type, TypeVar

from pydantic import ValidationError

from styrmin_backend.services.driver.models.resources.actions import ActionsSpec
from styrmin_backend.services.driver.models.resources.code import ActionsCode
from styrmin_backend.services.driver.models.resources.driver import DriverSpec
from styrmin_backend.services.driver.models.structure.resource import Role

from .exceptions import DeserializationError

ModelType = TypeVar("ModelType", DriverSpec, ActionsSpec, ActionsCode)


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


class DriverSpecDeserializer(Deserializer[DriverSpec]):
    model = DriverSpec

    def deserialize(self, data: Any) -> DriverSpec:
        try:
            return super().deserialize(data)
        except ValidationError as err:
            raise DeserializationError(
                f"The driver specification is invalid: {err!s}"
            ) from err


class ActionsSpecDeserializer(Deserializer[ActionsSpec]):
    model = ActionsSpec

    def deserialize(self, data: Any) -> ActionsSpec:
        try:
            return super().deserialize(data)
        except ValidationError as err:
            raise DeserializationError(
                f"The actions specification is invalid: {err!s}"
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
        case Role.ACTIONS_SPEC:
            return ActionsSpecDeserializer()
        case Role.VALUES_TEMPLATE | Role.ACTIONS_CODE:
            return None
        case _:
            raise ValueError(f"Unsupported role: {role!r}")
