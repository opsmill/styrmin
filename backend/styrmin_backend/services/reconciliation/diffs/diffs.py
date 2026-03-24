from abc import ABC, abstractmethod
from typing import Union, Any
from uuid import UUID

from pydantic import BaseModel

from styrmin_backend.domain.models import Instance
from typing_extensions import Self

CreateReturn = Union[
    "ApplicationVersionChange",
    "ContextChange",
    "ApplicationDriverVersionChange",
]
CreateArg = Union[str, dict, UUID]


class DiffEntry(BaseModel, ABC):
    """Base class for diff entries."""

    @classmethod
    @abstractmethod
    def create(cls, current_value: Any, new_value: Any) -> CreateReturn:
        """Set the current value of the diff."""
        pass


class ApplicationVersionChange(DiffEntry):
    """Version change diff."""

    current_value: str
    new_value: str

    @classmethod
    def create(cls, current_value: str, new_value: str) -> Self:
        """Set the current value of the diff."""
        if isinstance(current_value, str) and isinstance(new_value, str):
            return cls(
                current_value=current_value,
                new_value=new_value,
            )
        else:
            raise ValueError("Current value must be a string.")


class ApplicationDriverVersionChange(DiffEntry):
    """Application driver version change diff."""

    current_value: UUID
    new_value: UUID

    @classmethod
    def create(cls, current_value: UUID, new_value: UUID) -> Self:
        """Set the current value of the diff."""
        if isinstance(current_value, UUID) and isinstance(new_value, UUID):
            return cls(
                current_value=current_value,
                new_value=new_value,
            )
        else:
            raise ValueError("Current and New value must be a UUID.")


class ContextChange(DiffEntry):
    """Context change diff."""

    current_value: dict
    new_value: dict

    @classmethod
    def create(cls, current_value: dict, new_value: dict) -> Self:
        """Set the current value of the diff."""
        if isinstance(current_value, dict) and isinstance(new_value, dict):
            return cls(
                current_value=current_value,
                new_value=new_value,
            )
        else:
            raise ValueError("Current value must be a dictionary.")


class Diff(BaseModel):
    instance: Instance


class InstanceCreation(Diff):
    """The current instance is None and the new one is not."""


class InstanceDeletion(Diff):
    """The current instance is not None and the new one is."""


class InstanceUpdate(Diff):
    diffs: list[DiffEntry]


class DiffReport(BaseModel):
    """Diff report."""

    diff: Diff | None
    raw: dict | None
