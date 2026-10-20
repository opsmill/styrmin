from abc import ABC, abstractmethod
from typing import Sequence
from uuid import UUID

from sqlmodel import select

from styrmin_backend.db.models import (
    ApplicationInstance,
    Backup,
    Restore,
    RestoreStatus,
)
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.environment_backup import (
    NON_TERMINAL_RESTORE_STATUSES,
)
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class RestoreRepository(BaseRepository[Restore], ABC):
    """Repository specific to restores."""

    @abstractmethod
    async def get_by_backup_id(
        self, backup_id: UUID, status: RestoreStatus | None = None
    ) -> Sequence[Restore]:
        raise NotImplementedError()

    @abstractmethod
    async def get_non_terminal_by_target_namespace(
        self, target_namespace: str
    ) -> Sequence[Restore]:
        raise NotImplementedError()

    @abstractmethod
    async def get_non_terminal_by_source_deployment_id(
        self, deployment_id: UUID
    ) -> Sequence[Restore]:
        raise NotImplementedError()


class SQLModelRestoreRepository(BaseSQLModelRepository[Restore], RestoreRepository):
    """The async SQLModel restore repository."""

    model_class = Restore

    async def get_by_backup_id(
        self, backup_id: UUID, status: RestoreStatus | None = None
    ) -> Sequence[Restore]:
        """Get restores for a backup, optionally filtered by status."""
        statement = select(self.model_class).where(
            self.model_class.backup_id == backup_id
        )
        if status is not None:
            statement = statement.where(self.model_class.status == status)
        statement = statement.order_by(self.model_class.created_on.desc())  # type: ignore[union-attr]
        result = await self.session.exec(statement)
        return result.all()

    async def get_non_terminal_by_target_namespace(
        self, target_namespace: str
    ) -> Sequence[Restore]:
        """Get the non-terminal restores that target a namespace, newest first."""
        statement = (
            select(self.model_class)
            .where(self.model_class.target_namespace == target_namespace)
            .where(self.model_class.status.in_(NON_TERMINAL_RESTORE_STATUSES))  # type: ignore[attr-defined]
            .order_by(self.model_class.created_on.desc())  # type: ignore[union-attr]
        )
        result = await self.session.exec(statement)
        return result.all()

    async def get_non_terminal_by_source_deployment_id(
        self, deployment_id: UUID
    ) -> Sequence[Restore]:
        """Get non-terminal restores of backups taken from *deployment_id*.

        Matches on the backup's instance rather than on ``target_namespace``,
        so a restore is found whatever namespace it was created with.
        """
        statement = (
            select(self.model_class)
            .join(Backup, Backup.id == self.model_class.backup_id)  # type: ignore[arg-type]
            .join(
                ApplicationInstance,
                ApplicationInstance.id == Backup.instance_id,  # type: ignore[arg-type]
            )
            .where(ApplicationInstance.deployment_id == deployment_id)
            .where(self.model_class.status.in_(NON_TERMINAL_RESTORE_STATUSES))  # type: ignore[attr-defined]
            .order_by(self.model_class.created_on.desc())  # type: ignore[union-attr]
        )
        result = await self.session.exec(statement)
        return result.all()
