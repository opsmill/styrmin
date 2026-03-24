from abc import ABC, abstractmethod
from typing import Generic, Sequence, TypeVar
from uuid import UUID

ModelType = TypeVar("ModelType")


class BaseRepository(ABC, Generic[ModelType]):
    """The base repository class with async methods."""

    @abstractmethod
    async def create(self, entity: ModelType) -> ModelType:
        """Create a new entity."""

    @abstractmethod
    async def get(self, id: UUID) -> ModelType | None:
        """Get an entity by its ID."""

    @abstractmethod
    async def get_all(self) -> Sequence[ModelType]:
        """Get all entities."""

    @abstractmethod
    async def delete(self, entity: ModelType) -> None:
        """Delete an entity."""
