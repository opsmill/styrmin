from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

import strawberry

from styrmin_backend.api.scalars import JSON
from styrmin_backend.db.models import Cluster as ClusterModel

if TYPE_CHECKING:
    from styrmin_backend.api.definitions.environment.model import Environment


@strawberry.type
class Cluster:
    id: UUID
    name: str
    config: JSON
    capabilities: JSON
    created_on: datetime
    updated_on: datetime | None = None

    instance: strawberry.Private[ClusterModel]

    @strawberry.field
    def environments(
        self,
    ) -> list[
        Annotated[
            "Environment",
            strawberry.lazy("styrmin_backend.api.definitions.environment.model"),
        ]
    ]:
        from styrmin_backend.api.definitions.environment.model import Environment

        return [Environment.from_instance(env) for env in self.instance.environments]

    @classmethod
    def from_instance(cls, instance: ClusterModel) -> Cluster:
        return cls(
            id=instance.id,
            name=instance.name,
            instance=instance,
            config=instance.config,
            capabilities=instance.capabilities,
            created_on=instance.created_on,  # type: ignore[arg-type]
            updated_on=instance.updated_on,
        )
