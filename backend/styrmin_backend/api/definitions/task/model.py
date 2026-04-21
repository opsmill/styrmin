from __future__ import annotations

from datetime import datetime
from uuid import UUID

import strawberry

from styrmin_backend.api.definitions.deployment.model import Deployment
from styrmin_backend.api.resolvers import resolve_related
from styrmin_backend.api.scalars import JSON
from styrmin_backend.domain.models import Task as TaskEntity
from styrmin_backend.services.exceptions import DeploymentNotFoundError


@strawberry.type
class Task:
    id: UUID
    type: str
    status: str
    message: str | None = None
    parameters: JSON | None = None
    deployment_id: UUID | None = None
    created_on: datetime | None = None
    updated_on: datetime | None = None

    instance: strawberry.Private[TaskEntity]

    @strawberry.field
    async def deployment(self, info: strawberry.Info) -> Deployment | None:
        if self.deployment_id is None:
            return None
        return await resolve_related(
            info,
            "deployments",
            self.deployment_id,
            Deployment,
            DeploymentNotFoundError,
            method="find",
        )

    @classmethod
    def from_instance(cls, instance: TaskEntity) -> Task:
        return cls(
            id=instance.id,
            type=instance.type,
            status=instance.status,
            instance=instance,
            deployment_id=instance.deployment_id,
            message=instance.message,
            parameters=instance.parameters,
            created_on=instance.created_on,
            updated_on=instance.updated_on,
        )
