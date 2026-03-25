from __future__ import annotations

from datetime import datetime
from uuid import UUID

import strawberry

from styrmin_backend.api.definitions.deployment.model import Deployment
from styrmin_backend.db.models import BackupSchedule as BackupScheduleModel


@strawberry.type
class BackupSchedule:
    id: UUID
    name: str
    enabled: bool
    cron_expression: str
    last_backup_at: datetime | None = None
    next_backup_at: datetime | None = None
    retention_count: int
    prefect_deployment_id: UUID | None = None
    deployment_id: UUID
    created_on: datetime
    updated_on: datetime | None = None

    @strawberry.field
    async def deployment(self, info: strawberry.Info) -> Deployment:
        uow = info.context["uow"]
        async with uow:
            entity = await uow.deployments.find(self.deployment_id)
            if entity is None:
                msg = f"Deployment {self.deployment_id} not found"
                raise ValueError(msg)
            return Deployment.from_instance(entity)

    @classmethod
    def from_instance(cls, instance: BackupScheduleModel) -> BackupSchedule:
        return cls(
            id=instance.id,
            name=instance.name,
            enabled=instance.enabled,
            cron_expression=instance.cron_expression,
            last_backup_at=instance.last_backup_at,
            next_backup_at=instance.next_backup_at,
            retention_count=instance.retention_count,
            prefect_deployment_id=instance.prefect_deployment_id,
            deployment_id=instance.deployment_id,
            created_on=instance.created_on,  # type: ignore[arg-type]
            updated_on=instance.updated_on,
        )
