from abc import ABC, abstractmethod
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy.orm import selectinload
from sqlmodel import select

from styrmin_backend.db.models import BackupStorageLocation
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class BackupStorageLocationRepository(BaseRepository[BackupStorageLocation], ABC):
    """Repository specific to backup storage locations."""

    @abstractmethod
    async def get_by_name(self, name: str) -> BackupStorageLocation | None:
        raise NotImplementedError()


class SQLModelBackupStorageLocationRepository(
    BaseSQLModelRepository[BackupStorageLocation], BackupStorageLocationRepository
):
    """The async SQLmodel backup storage location repository."""

    model_class = BackupStorageLocation

    def _eager_load_options(self) -> list[Any]:
        """Return options for eager loading all relationships."""
        return [
            selectinload(self.model_class.environments),  # type: ignore[arg-type]
        ]

    async def get(self, id: UUID) -> BackupStorageLocation | None:
        """Get a backup storage location by its ID with relationships eagerly loaded."""
        statement = (
            select(self.model_class)
            .where(self.model_class.id == id)
            .options(*self._eager_load_options())
        )
        result = await self.session.exec(statement)
        return result.first()

    async def get_all(self) -> Sequence[BackupStorageLocation]:
        """Get all backup storage locations with relationships eagerly loaded."""
        statement = select(self.model_class).options(*self._eager_load_options())
        result = await self.session.exec(statement)
        return result.all()

    async def get_by_name(self, name: str) -> BackupStorageLocation | None:
        """Get a backup storage location by its name."""
        statement = (
            select(self.model_class)
            .where(self.model_class.name == name)
            .options(*self._eager_load_options())
        )
        result = await self.session.exec(statement)
        return result.first()
