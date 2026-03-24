from abc import ABC, abstractmethod
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy.orm import selectinload
from sqlmodel import select

from styrmin_backend.db.models import Deployment as DeploymentModel
from styrmin_backend.db.models import Environment
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class EnvironmentRepository(BaseRepository[Environment], ABC):
    """Repository specific to environments."""

    @abstractmethod
    async def get_by_name(self, name: str) -> Environment | None:
        raise NotImplementedError()


class SQLModelEnvironmentRepository(
    BaseSQLModelRepository[Environment], EnvironmentRepository
):
    """The async SQLmodel environment repository."""

    model_class = Environment

    def _eager_load_options(self) -> list[Any]:
        """Return options for eager loading all relationships."""
        return [
            selectinload(self.model_class.cluster),  # type: ignore[arg-type]
            selectinload(self.model_class.backup_storage_location),  # type: ignore[arg-type]
            selectinload(self.model_class.deployments).options(  # type: ignore[arg-type]
                selectinload(DeploymentModel.components),  # type: ignore[arg-type]
                selectinload(DeploymentModel.active_application_instance),  # type: ignore[arg-type]
            ),
        ]

    async def get(self, id: UUID) -> Environment | None:
        """Get an environment by its ID with relationships eagerly loaded."""
        statement = (
            select(self.model_class)
            .where(self.model_class.id == id)
            .options(*self._eager_load_options())
        )
        result = await self.session.exec(statement)
        return result.first()

    async def get_all(self) -> Sequence[Environment]:
        """Get all environments with relationships eagerly loaded."""
        statement = select(self.model_class).options(*self._eager_load_options())
        result = await self.session.exec(statement)
        return result.all()

    async def get_by_name(self, name: str) -> Environment | None:
        """Get an environment by its name."""
        statement = (
            select(self.model_class)
            .where(self.model_class.name == name)
            .options(*self._eager_load_options())
        )
        result = await self.session.exec(statement)
        return result.first()
