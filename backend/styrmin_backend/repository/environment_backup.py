from abc import ABC, abstractmethod
from typing import Sequence
from uuid import UUID

from sqlmodel import select

from styrmin_backend.db.models import EnvironmentBackup, EnvironmentBackupStatus
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class EnvironmentBackupRepository(BaseRepository[EnvironmentBackup], ABC):
    """Repository specific to environment backups."""

    @abstractmethod
    async def get_by_environment_id(
        self,
        environment_id: UUID,
        status: EnvironmentBackupStatus | None = None,
    ) -> Sequence[EnvironmentBackup]:
        raise NotImplementedError()


class SQLModelEnvironmentBackupRepository(
    BaseSQLModelRepository[EnvironmentBackup], EnvironmentBackupRepository
):
    """The async SQLModel environment backup repository."""

    model_class = EnvironmentBackup

    async def get_by_environment_id(
        self,
        environment_id: UUID,
        status: EnvironmentBackupStatus | None = None,
    ) -> Sequence[EnvironmentBackup]:
        """Get environment backups for an environment, optionally filtered by status."""
        statement = select(self.model_class).where(
            self.model_class.environment_id == environment_id
        )
        if status is not None:
            statement = statement.where(self.model_class.status == status)
        statement = statement.order_by(self.model_class.created_on.desc())  # type: ignore[union-attr]
        result = await self.session.exec(statement)
        return result.all()
