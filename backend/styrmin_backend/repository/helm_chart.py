from abc import ABC, abstractmethod
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy.orm import selectinload
from sqlmodel import select

from styrmin_backend.db.models import HelmChart
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class HelmChartRepository(BaseRepository[HelmChart], ABC):
    """Repository specific to Helm charts."""

    @abstractmethod
    async def get_by_name_version(self, name: str, version: str) -> HelmChart | None:
        """Get a helm chart by its name and version."""
        raise NotImplementedError


class SQLModelHelmChartRepository(
    BaseSQLModelRepository[HelmChart], HelmChartRepository
):
    """The async SQLmodel helm chart repository."""

    model_class = HelmChart

    def _eager_load_options(self) -> list[Any]:
        """Return options for eager loading all relationships."""
        return [
            selectinload(self.model_class.repository),  # type: ignore[arg-type]
        ]

    async def get(self, id: UUID) -> HelmChart | None:
        """Get a helm chart by its ID with relationships eagerly loaded."""
        statement = (
            select(self.model_class)
            .where(self.model_class.id == id)
            .options(*self._eager_load_options())
        )
        result = await self.session.exec(statement)
        return result.first()

    async def get_all(self) -> Sequence[HelmChart]:
        """Get all helm charts with relationships eagerly loaded."""
        statement = select(self.model_class).options(*self._eager_load_options())
        result = await self.session.exec(statement)
        return result.all()

    async def get_by_name_version(self, name: str, version: str) -> HelmChart | None:
        """Get a helm chart by its name and version."""
        statement = (
            select(self.model_class)
            .where(self.model_class.name == name)
            .where(self.model_class.version == version)
            .options(*self._eager_load_options())
        )
        result = await self.session.exec(statement)
        return result.first()
