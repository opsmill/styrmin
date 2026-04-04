from abc import ABC, abstractmethod
from typing import Sequence
from uuid import UUID

from sqlmodel import select

from styrmin_backend.db.models import EnvironmentRestore, EnvironmentRestoreStatus
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class EnvironmentRestoreRepository(BaseRepository[EnvironmentRestore], ABC):
    """Repository specific to environment restores."""

    @abstractmethod
    async def get_by_environment_backup_id(
        self,
        environment_backup_id: UUID,
        status: EnvironmentRestoreStatus | None = None,
    ) -> Sequence[EnvironmentRestore]:
        raise NotImplementedError()


class SQLModelEnvironmentRestoreRepository(
    BaseSQLModelRepository[EnvironmentRestore], EnvironmentRestoreRepository
):
    """The async SQLModel environment restore repository."""

    model_class = EnvironmentRestore

    async def get_by_environment_backup_id(
        self,
        environment_backup_id: UUID,
        status: EnvironmentRestoreStatus | None = None,
    ) -> Sequence[EnvironmentRestore]:
        """Get environment restores for an environment backup, optionally filtered by status."""
        statement = select(self.model_class).where(
            self.model_class.environment_backup_id == environment_backup_id
        )
        if status is not None:
            statement = statement.where(self.model_class.status == status)
        statement = statement.order_by(self.model_class.created_on.desc())  # type: ignore[union-attr]
        result = await self.session.exec(statement)
        return result.all()
