from __future__ import annotations

from datetime import datetime
from uuid import UUID

import strawberry

from styrmin_backend.api.definitions.backup.backup import Backup
from styrmin_backend.api.resolvers import resolve_related
from styrmin_backend.db.models import Restore as RestoreModel
from styrmin_backend.services.exceptions import BackupNotFoundError


@strawberry.type
class ComponentRestoreStatus:
    component_name: str
    status: str
    error_message: str | None = None


@strawberry.type
class Restore:
    id: UUID
    name: str
    status: str
    created_on: datetime
    updated_on: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    target_namespace: str
    error_message: str | None = None
    backup_id: UUID
    target_instance_id: UUID | None = None

    instance: strawberry.Private[RestoreModel]

    @strawberry.field
    async def backup(self, info: strawberry.Info) -> Backup:
        return await resolve_related(
            info,
            "backups",
            self.backup_id,
            Backup,
            BackupNotFoundError,
        )

    @strawberry.field
    def component_statuses(self) -> list[ComponentRestoreStatus] | None:
        statuses = self.instance.component_statuses
        if not statuses:
            return None
        return [
            ComponentRestoreStatus(
                component_name=name,
                status=data.get("status", "unknown"),
                error_message=data.get("error_message"),
            )
            for name, data in statuses.items()
        ]

    @classmethod
    def from_instance(cls, instance: RestoreModel) -> Restore:
        return cls(
            id=instance.id,
            name=instance.name,
            status=instance.status.value,
            created_on=instance.created_on,  # type: ignore[arg-type]
            updated_on=instance.updated_on,
            started_at=instance.started_at,
            completed_at=instance.completed_at,
            target_namespace=instance.target_namespace,
            error_message=instance.error_message,
            backup_id=instance.backup_id,
            target_instance_id=instance.target_instance_id,
            instance=instance,
        )
