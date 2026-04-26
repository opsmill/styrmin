from abc import ABC, abstractmethod
from typing import Sequence
from uuid import UUID

from sqlmodel import select

from styrmin_backend.db.models import Restore, RestoreStatus
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class RestoreRepository(BaseRepository[Restore], ABC):
    """Repository specific to restores."""

    @abstractmethod
    async def get_by_backup_id(
        self, backup_id: UUID, status: RestoreStatus | None = None
    ) -> Sequence[Restore]:
        raise NotImplementedError()

    @abstractmethod
    async def get_by_target_namespace(
        self, target_namespace: str, status: RestoreStatus | None = None
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

    async def get_by_target_namespace(
        self, target_namespace: str, status: RestoreStatus | None = None
    ) -> Sequence[Restore]:
        """Get restores targeting a namespace, optionally filtered by status."""
        statement = select(self.model_class).where(
            self.model_class.target_namespace == target_namespace
        )
        if status is not None:
            statement = statement.where(self.model_class.status == status)
        statement = statement.order_by(self.model_class.created_on.desc())  # type: ignore[union-attr]
        result = await self.session.exec(statement)
        return result.all()
