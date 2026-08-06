"""Repositories for the environment-level backup and restore parent records.

Neither parent stores a status column (see ``services/backup/environment.py``),
so "is an environment-level operation in progress?" is answered by an EXISTS
query over the *constituent* rows rather than by reading a parent column — the
guard can therefore never disagree with reality.
"""

from abc import ABC, abstractmethod
from typing import Sequence
from uuid import UUID

from sqlmodel import select

from styrmin_backend.db.models import (
    Backup,
    BackupStatus,
    EnvironmentBackup,
    EnvironmentRestore,
    Restore,
    RestoreStatus,
)
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository

#: Constituent backup states that keep an environment backup non-terminal.
NON_TERMINAL_BACKUP_STATUSES = (BackupStatus.PENDING, BackupStatus.IN_PROGRESS)

#: Constituent restore states that keep an environment restore non-terminal.
NON_TERMINAL_RESTORE_STATUSES = (RestoreStatus.PENDING, RestoreStatus.IN_PROGRESS)


class EnvironmentBackupRepository(BaseRepository[EnvironmentBackup], ABC):
    """Repository specific to environment backups."""

    @abstractmethod
    async def get_by_environment_id(
        self, environment_id: UUID
    ) -> Sequence[EnvironmentBackup]:
        """Get the environment backups of an environment, newest first."""
        raise NotImplementedError()

    @abstractmethod
    async def has_in_progress_environment_backup(
        self, environment_id: UUID
    ) -> EnvironmentBackup | None:
        """Return the environment backup with a non-terminal constituent, if any."""
        raise NotImplementedError()


class EnvironmentRestoreRepository(BaseRepository[EnvironmentRestore], ABC):
    """Repository specific to environment restores."""

    @abstractmethod
    async def get_by_environment_backup_id(
        self, environment_backup_id: UUID
    ) -> Sequence[EnvironmentRestore]:
        """Get the environment restores of an environment backup, newest first."""
        raise NotImplementedError()

    @abstractmethod
    async def has_in_progress_environment_restore(
        self, environment_id: UUID
    ) -> EnvironmentRestore | None:
        """Return the environment restore with a non-terminal constituent, if any."""
        raise NotImplementedError()


class SQLModelEnvironmentBackupRepository(
    BaseSQLModelRepository[EnvironmentBackup], EnvironmentBackupRepository
):
    """The async SQLModel environment backup repository."""

    model_class = EnvironmentBackup

    async def get_by_environment_id(
        self, environment_id: UUID
    ) -> Sequence[EnvironmentBackup]:
        """Get the environment backups of an environment, newest first."""
        statement = (
            select(self.model_class)
            .where(self.model_class.environment_id == environment_id)
            .order_by(self.model_class.created_on.desc())  # type: ignore[union-attr]
        )
        result = await self.session.exec(statement)
        return result.all()

    async def has_in_progress_environment_backup(
        self, environment_id: UUID
    ) -> EnvironmentBackup | None:
        """Return the environment backup with a non-terminal constituent, if any.

        An environment backup counts as in progress iff at least one linked
        ``Backup`` row is ``PENDING`` or ``IN_PROGRESS``. A parent with no
        constituents at all (config-only backup) is therefore never in progress.
        """
        statement = (
            select(self.model_class)
            .where(self.model_class.environment_id == environment_id)
            .where(
                select(Backup.id)
                .where(Backup.environment_backup_id == self.model_class.id)
                .where(Backup.status.in_(NON_TERMINAL_BACKUP_STATUSES))  # type: ignore[attr-defined]
                .exists()
            )
            .order_by(self.model_class.created_on.desc())  # type: ignore[union-attr]
        )
        result = await self.session.exec(statement)
        return result.first()


class SQLModelEnvironmentRestoreRepository(
    BaseSQLModelRepository[EnvironmentRestore], EnvironmentRestoreRepository
):
    """The async SQLModel environment restore repository."""

    model_class = EnvironmentRestore

    async def get_by_environment_backup_id(
        self, environment_backup_id: UUID
    ) -> Sequence[EnvironmentRestore]:
        """Get the environment restores of an environment backup, newest first."""
        statement = (
            select(self.model_class)
            .where(self.model_class.environment_backup_id == environment_backup_id)
            .order_by(self.model_class.created_on.desc())  # type: ignore[union-attr]
        )
        result = await self.session.exec(statement)
        return result.all()

    async def has_in_progress_environment_restore(
        self, environment_id: UUID
    ) -> EnvironmentRestore | None:
        """Return the environment restore with a non-terminal constituent, if any.

        The environment is reached through the parent environment backup —
        ``EnvironmentRestore`` has no ``environment_id`` of its own.
        """
        statement = (
            select(self.model_class)
            .join(
                EnvironmentBackup,
                EnvironmentBackup.id == self.model_class.environment_backup_id,  # type: ignore[arg-type]
            )
            .where(EnvironmentBackup.environment_id == environment_id)
            .where(
                select(Restore.id)
                .where(Restore.environment_restore_id == self.model_class.id)
                .where(Restore.status.in_(NON_TERMINAL_RESTORE_STATUSES))  # type: ignore[attr-defined]
                .exists()
            )
            .order_by(self.model_class.created_on.desc())  # type: ignore[union-attr]
        )
        result = await self.session.exec(statement)
        return result.first()
