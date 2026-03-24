from __future__ import annotations

from uuid import UUID

import strawberry

from styrmin_backend.domain.models import Task as TaskEntity


@strawberry.type
class Task:
    id: UUID
    type: str
    status: str
    message: str | None = None
    deployment_id: UUID | None = None

    instance: strawberry.Private[TaskEntity]

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
