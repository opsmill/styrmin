from abc import ABC, abstractmethod
from typing import Sequence
from uuid import UUID

from sqlmodel import select

from styrmin_backend.db.models import Backup, BackupStatus
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class BackupRepository(BaseRepository[Backup], ABC):
    """Repository specific to backups."""

    @abstractmethod
    async def get_by_instance_id(
        self, instance_id: UUID, status: BackupStatus | None = None
    ) -> Sequence[Backup]:
        raise NotImplementedError()

    @abstractmethod
    async def has_in_progress_backup(self, instance_id: UUID) -> Backup | None:
        raise NotImplementedError()


class SQLModelBackupRepository(BaseSQLModelRepository[Backup], BackupRepository):
    """The async SQLModel backup repository."""

    model_class = Backup

    async def get_by_instance_id(
        self, instance_id: UUID, status: BackupStatus | None = None
    ) -> Sequence[Backup]:
        """Get backups for an instance, optionally filtered by status."""
        statement = select(self.model_class).where(
            self.model_class.instance_id == instance_id
        )
        if status is not None:
            statement = statement.where(self.model_class.status == status)
        statement = statement.order_by(self.model_class.created_on.desc())  # type: ignore[union-attr]
        result = await self.session.exec(statement)
        return result.all()

    async def has_in_progress_backup(self, instance_id: UUID) -> Backup | None:
        """Check if there is an in-progress backup for the given instance."""
        statement = select(self.model_class).where(
            self.model_class.instance_id == instance_id,
            self.model_class.status == BackupStatus.IN_PROGRESS,
        )
        result = await self.session.exec(statement)
        return result.first()
