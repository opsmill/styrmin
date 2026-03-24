from abc import ABC, abstractmethod

from sqlmodel import select

from styrmin_backend.db.models import HelmRepository
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class HelmRepositoryRepository(BaseRepository[HelmRepository], ABC):
    """Repository specific to Helm repositories."""

    @abstractmethod
    async def get_by_url(self, url: str) -> HelmRepository | None:
        """Get a helm repository by its URL."""
        raise NotImplementedError


class SQLModelHelmRepositoryRepository(
    BaseSQLModelRepository[HelmRepository], HelmRepositoryRepository
):
    """The async SQLmodel helm repository repository."""

    model_class = HelmRepository

    async def get_by_url(self, url: str) -> HelmRepository | None:
        """Get a helm repository by its URL."""
        statement = select(self.model_class).where(self.model_class.url == url)
        result = await self.session.exec(statement)
        return result.first()
