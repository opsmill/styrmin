from __future__ import annotations

from uuid import UUID

import strawberry

from styrmin_backend.db.models import Action as ActionModel


@strawberry.type
class Action:
    id: UUID
    name: str
    description: str
    location: str

    image: str | None = None

    instance: strawberry.Private[ActionModel]

    @classmethod
    def from_instance(cls, instance: ActionModel) -> Action:
        return cls(
            id=instance.id,
            name=instance.name,
            instance=instance,
            image=instance.image,
            description=instance.description,
            location=instance.location,
        )
