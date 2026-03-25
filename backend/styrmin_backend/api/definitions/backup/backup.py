from __future__ import annotations

from datetime import datetime
from uuid import UUID

import strawberry

from styrmin_backend.api.definitions.deployment.model import (
    ApplicationInstance as ApplicationInstanceType,
)
from styrmin_backend.db.models import Backup as BackupModel


@strawberry.type
class ComponentBackupStatus:
    component_name: str
    status: str
    size_bytes: int | None = None
    error_message: str | None = None


@strawberry.type
class Backup:
    id: UUID
    name: str
    status: str
    created_on: datetime
    updated_on: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    size_bytes: int | None = None
    error_message: str | None = None
    instance_id: UUID

    db_model: strawberry.Private[BackupModel]

    @strawberry.field
    async def instance(self, info: strawberry.Info) -> ApplicationInstanceType:
        uow = info.context["uow"]
        async with uow:
            db_instance = await uow.application_instances.get(self.instance_id)
            if db_instance is None:
                msg = f"ApplicationInstance {self.instance_id} not found"
                raise ValueError(msg)
            return ApplicationInstanceType.from_instance(db_instance)

    @strawberry.field
    def component_statuses(self) -> list[ComponentBackupStatus] | None:
        statuses = self.db_model.component_statuses
        if not statuses:
            return None
        return [
            ComponentBackupStatus(
                component_name=name,
                status=data.get("status", "unknown"),
                size_bytes=data.get("size_bytes"),
                error_message=data.get("error_message"),
            )
            for name, data in statuses.items()
        ]

    @classmethod
    def from_instance(cls, instance: BackupModel) -> Backup:
        return cls(
            id=instance.id,
            name=instance.name,
            status=instance.status.value,
            created_on=instance.created_on,  # type: ignore[arg-type]
            updated_on=instance.updated_on,
            started_at=instance.started_at,
            completed_at=instance.completed_at,
            size_bytes=instance.size_bytes,
            error_message=instance.error_message,
            instance_id=instance.instance_id,
            db_model=instance,
        )
