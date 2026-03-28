from __future__ import annotations

from datetime import datetime
from uuid import UUID

import strawberry

from styrmin_backend.api.definitions.deployment.model import Deployment
from styrmin_backend.api.resolvers import resolve_related
from styrmin_backend.db.models import BackupSchedule as BackupScheduleModel
from styrmin_backend.services.exceptions import DeploymentNotFoundError


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
        return await resolve_related(
            info,
            "deployments",
            self.deployment_id,
            Deployment,
            DeploymentNotFoundError,
            method="find",
        )

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
