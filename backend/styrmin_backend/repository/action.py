from abc import ABC, abstractmethod
from uuid import UUID

from sqlmodel import col, select

from styrmin_backend.db.models import Action
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class ActionRepository(BaseRepository[Action], ABC):
    """Repository specific to Actions."""

    @abstractmethod
    async def list_by_driver_version(self, driver_version_id: UUID) -> list[Action]:
        """Return the declared actions of one driver version, ordered by name."""
        raise NotImplementedError()


class SQLModelActionRepository(BaseSQLModelRepository[Action], ActionRepository):
    """The async SQLmodel Action repository."""

    model_class = Action

    async def list_by_driver_version(self, driver_version_id: UUID) -> list[Action]:
        """Return the declared actions of one driver version, ordered by name."""
        statement = (
            select(self.model_class)
            .where(self.model_class.application_driver_version_id == driver_version_id)
            .order_by(col(self.model_class.name))
        )
        result = await self.session.exec(statement)
        return list(result.all())
