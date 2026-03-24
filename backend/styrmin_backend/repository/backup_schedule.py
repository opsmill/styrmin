from abc import ABC, abstractmethod
from typing import Sequence
from uuid import UUID

from sqlmodel import select

from styrmin_backend.db.models import BackupSchedule
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class BackupScheduleRepository(BaseRepository[BackupSchedule], ABC):
    """Repository specific to backup schedules."""

    @abstractmethod
    async def get_by_deployment_id(
        self, deployment_id: UUID
    ) -> Sequence[BackupSchedule]:
        raise NotImplementedError()


class SQLModelBackupScheduleRepository(
    BaseSQLModelRepository[BackupSchedule], BackupScheduleRepository
):
    """The async SQLModel backup schedule repository."""

    model_class = BackupSchedule

    async def get_by_deployment_id(
        self, deployment_id: UUID
    ) -> Sequence[BackupSchedule]:
        """Get backup schedules for a deployment."""
        statement = select(self.model_class).where(
            self.model_class.deployment_id == deployment_id
        )
        result = await self.session.exec(statement)
        return result.all()
