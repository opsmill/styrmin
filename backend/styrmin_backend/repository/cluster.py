from abc import ABC, abstractmethod
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy.orm import selectinload
from sqlmodel import func, select

from styrmin_backend.db.models import Cluster
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class ClusterRepository(BaseRepository[Cluster], ABC):
    """Repository specific to clusters."""

    @abstractmethod
    async def get_by_name(self, name: str) -> Cluster | None:
        raise NotImplementedError()

    @abstractmethod
    async def count(self) -> int:
        """Return the number of clusters."""
        raise NotImplementedError()


class SQLModelClusterRepository(BaseSQLModelRepository[Cluster], ClusterRepository):
    """The async SQLmodel cluster repository."""

    model_class = Cluster

    def _eager_load_options(self) -> list[Any]:
        """Return options for eager loading all relationships."""
        return [
            selectinload(self.model_class.environments),  # type: ignore[arg-type]
        ]

    async def get(self, id: UUID) -> Cluster | None:
        """Get a cluster by its ID with relationships eagerly loaded."""
        statement = (
            select(self.model_class)
            .where(self.model_class.id == id)
            .options(*self._eager_load_options())
        )
        result = await self.session.exec(statement)
        return result.first()

    async def get_all(self) -> Sequence[Cluster]:
        """Get all clusters with relationships eagerly loaded."""
        statement = select(self.model_class).options(*self._eager_load_options())
        result = await self.session.exec(statement)
        return result.all()

    async def get_by_name(self, name: str) -> Cluster | None:
        """Get a cluster by its name."""
        statement = (
            select(self.model_class)
            .where(self.model_class.name == name)
            .options(*self._eager_load_options())
        )
        result = await self.session.exec(statement)
        return result.first()

    async def count(self) -> int:
        """Return the number of clusters without loading them."""
        result = await self.session.exec(
            select(func.count()).select_from(self.model_class)
        )
        return result.one()
