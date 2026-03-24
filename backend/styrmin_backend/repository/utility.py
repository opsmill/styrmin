from abc import ABC, abstractmethod

from sqlmodel import select

from styrmin_backend.db.models import Utility
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class UtilityRepository(BaseRepository[Utility], ABC):
    """Repository specific to utilities."""

    @abstractmethod
    async def get_by_kind(self, kind: str) -> Utility | None:
        """Get a utility by its kind."""
        raise NotImplementedError()


class SQLModelUtilityRepository(BaseSQLModelRepository[Utility], UtilityRepository):
    """The async SQLmodel utility repository."""

    model_class = Utility

    async def get_by_kind(self, kind: str) -> Utility | None:
        """Get a utility by its kind."""
        statement = select(self.model_class).where(self.model_class.kind == kind)
        result = await self.session.exec(statement)
        return result.first()
