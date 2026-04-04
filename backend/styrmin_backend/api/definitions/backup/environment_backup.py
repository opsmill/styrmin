from __future__ import annotations

from datetime import datetime
from uuid import UUID

import strawberry

from styrmin_backend.api.definitions.backup.backup import Backup as BackupType
from styrmin_backend.api.definitions.backup.restore import Restore as RestoreType
from styrmin_backend.api.definitions.environment.model import (
    Environment as EnvironmentType,
)
from styrmin_backend.api.resolvers import resolve_related
from styrmin_backend.db.models import EnvironmentBackup as EnvironmentBackupModel
from styrmin_backend.db.models import EnvironmentRestore as EnvironmentRestoreModel
from styrmin_backend.services.exceptions import (
    EnvironmentBackupNotFoundError,
    EnvironmentNotFoundError,
)


@strawberry.type
class EnvironmentBackup:
    id: UUID
    name: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    metadata: strawberry.scalars.JSON | None = None
    max_concurrency: int
    timeout: int
    created_on: datetime
    updated_on: datetime | None = None

    db_model: strawberry.Private[EnvironmentBackupModel]

    @strawberry.field
    async def environment(self, info: strawberry.Info) -> EnvironmentType:
        return await resolve_related(
            info,
            "environments",
            self.db_model.environment_id,
            EnvironmentType,
            EnvironmentNotFoundError,
        )

    @strawberry.field
    async def backups(self, info: strawberry.Info) -> list[BackupType]:
        from sqlmodel import select
        from styrmin_backend.db.models import Backup

        uow = info.context["uow"]
        async with uow:
            result = await uow.session.exec(
                select(Backup).where(Backup.environment_backup_id == self.id)
            )
            return [BackupType.from_instance(b) for b in result.all()]

    @strawberry.field
    async def restores(self, info: strawberry.Info) -> list["EnvironmentRestore"]:

        uow = info.context["uow"]
        async with uow:
            items = await uow.environment_restores.get_by_environment_backup_id(self.id)
            return [EnvironmentRestore.from_instance(r) for r in items]

    @strawberry.field
    async def backup_count(self, info: strawberry.Info) -> int:
        from sqlmodel import select, func
        from styrmin_backend.db.models import Backup

        uow = info.context["uow"]
        async with uow:
            result = await uow.session.exec(
                select(func.count()).where(Backup.environment_backup_id == self.id)
            )
            return result.one()

    @strawberry.field
    async def completed_count(self, info: strawberry.Info) -> int:
        from sqlmodel import select, func
        from styrmin_backend.db.models import Backup, BackupStatus

        uow = info.context["uow"]
        async with uow:
            result = await uow.session.exec(
                select(func.count()).where(
                    Backup.environment_backup_id == self.id,
                    Backup.status == BackupStatus.COMPLETED,
                )
            )
            return result.one()

    @strawberry.field
    async def failed_count(self, info: strawberry.Info) -> int:
        from sqlmodel import select, func
        from styrmin_backend.db.models import Backup, BackupStatus

        uow = info.context["uow"]
        async with uow:
            result = await uow.session.exec(
                select(func.count()).where(
                    Backup.environment_backup_id == self.id,
                    Backup.status == BackupStatus.FAILED,
                )
            )
            return result.one()

    @classmethod
    def from_instance(cls, instance: EnvironmentBackupModel) -> EnvironmentBackup:
        return cls(
            id=instance.id,
            name=instance.name,
            status=instance.status.value,
            started_at=instance.started_at,
            completed_at=instance.completed_at,
            error_message=instance.error_message,
            metadata=instance.metadata_,
            max_concurrency=instance.max_concurrency,
            timeout=instance.timeout,
            created_on=instance.created_on,  # type: ignore[arg-type]
            updated_on=instance.updated_on,
            db_model=instance,
        )


@strawberry.type
class EnvironmentRestore:
    id: UUID
    name: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    metadata: strawberry.scalars.JSON | None = None
    created_on: datetime
    updated_on: datetime | None = None

    db_model: strawberry.Private[EnvironmentRestoreModel]

    @strawberry.field
    async def environment_backup(self, info: strawberry.Info) -> EnvironmentBackup:
        return await resolve_related(
            info,
            "environment_backups",
            self.db_model.environment_backup_id,
            EnvironmentBackup,
            EnvironmentBackupNotFoundError,
        )

    @strawberry.field
    async def restores(self, info: strawberry.Info) -> list[RestoreType]:
        from sqlmodel import select
        from styrmin_backend.db.models import Restore

        uow = info.context["uow"]
        async with uow:
            result = await uow.session.exec(
                select(Restore).where(Restore.environment_restore_id == self.id)
            )
            return [RestoreType.from_instance(r) for r in result.all()]

    @strawberry.field
    async def restore_count(self, info: strawberry.Info) -> int:
        from sqlmodel import select, func
        from styrmin_backend.db.models import Restore

        uow = info.context["uow"]
        async with uow:
            result = await uow.session.exec(
                select(func.count()).where(Restore.environment_restore_id == self.id)
            )
            return result.one()

    @strawberry.field
    async def completed_count(self, info: strawberry.Info) -> int:
        from sqlmodel import select, func
        from styrmin_backend.db.models import Restore, RestoreStatus

        uow = info.context["uow"]
        async with uow:
            result = await uow.session.exec(
                select(func.count()).where(
                    Restore.environment_restore_id == self.id,
                    Restore.status == RestoreStatus.COMPLETED,
                )
            )
            return result.one()

    @strawberry.field
    async def failed_count(self, info: strawberry.Info) -> int:
        from sqlmodel import select, func
        from styrmin_backend.db.models import Restore, RestoreStatus

        uow = info.context["uow"]
        async with uow:
            result = await uow.session.exec(
                select(func.count()).where(
                    Restore.environment_restore_id == self.id,
                    Restore.status == RestoreStatus.FAILED,
                )
            )
            return result.one()

    @classmethod
    def from_instance(cls, instance: EnvironmentRestoreModel) -> EnvironmentRestore:
        return cls(
            id=instance.id,
            name=instance.name,
            status=instance.status.value,
            started_at=instance.started_at,
            completed_at=instance.completed_at,
            error_message=instance.error_message,
            metadata=instance.metadata_,
            created_on=instance.created_on,  # type: ignore[arg-type]
            updated_on=instance.updated_on,
            db_model=instance,
        )
