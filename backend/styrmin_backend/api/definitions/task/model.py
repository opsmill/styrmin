from __future__ import annotations

from uuid import UUID

import strawberry

from styrmin_backend.api.definitions.deployment.model import Deployment
from styrmin_backend.domain.models import Task as TaskEntity


@strawberry.type
class Task:
    id: UUID
    type: str
    status: str
    message: str | None = None
    deployment_id: UUID | None = None

    instance: strawberry.Private[TaskEntity]

    @strawberry.field
    async def deployment(self, info: strawberry.Info) -> Deployment | None:
        if self.deployment_id is None:
            return None
        uow = info.context["uow"]
        async with uow:
            entity = await uow.deployments.find(self.deployment_id)
            if entity is None:
                msg = f"Deployment {self.deployment_id} not found"
                raise ValueError(msg)
            return Deployment.from_instance(entity)

    @classmethod
    def from_instance(cls, instance: TaskEntity) -> Task:
        return cls(
            id=instance.id,
            type=instance.type,
            status=instance.status,
            instance=instance,
            deployment_id=instance.deployment_id,
            message=instance.message,
        )
