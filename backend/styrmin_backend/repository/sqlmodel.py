from typing import Sequence, Type, TypeVar
from uuid import UUID

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import StyrminModel
from styrmin_backend.repository.base import BaseRepository

from .exceptions import EntityClassInconsistencyError

ModelType = TypeVar("ModelType", bound=StyrminModel)


class BaseSQLModelRepository(BaseRepository[ModelType]):
    """The async base repository class."""

    model_class: Type[ModelType]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, entity: ModelType) -> ModelType:
        """Create a new entity."""
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def get(self, id: UUID) -> ModelType | None:
        """Get an entity by its ID."""

        result = await self.session.exec(
            select(self.model_class).where(self.model_class.id == id)
        )
        entity = result.first()

        if entity is not None and not isinstance(entity, self.model_class):
            raise EntityClassInconsistencyError(
                f"Expected entity of class {self.model_class}, got {type(entity)}"
            )

        return entity

    async def get_all(self) -> Sequence[ModelType]:
        """Get all entities."""
        result = await self.session.exec(select(self.model_class))
        return result.all()

    async def delete(self, entity: ModelType) -> None:
        """Delete an entity."""
        await self.session.delete(entity)

    async def count(self) -> int:
        """Return the number of entities without loading them."""
        result = await self.session.exec(
            select(func.count()).select_from(self.model_class)
        )
        return result.one()
