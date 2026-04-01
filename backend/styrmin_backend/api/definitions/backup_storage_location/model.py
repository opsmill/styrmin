from __future__ import annotations

from datetime import datetime
from uuid import UUID

import strawberry

from styrmin_backend.db.models import (
    BackupStorageLocation as BackupStorageLocationModel,
)


@strawberry.type
class BackupStorageLocation:
    id: UUID
    name: str
    endpoint: str
    bucket: str
    region: str
    created_on: datetime
    updated_on: datetime | None = None

    instance: strawberry.Private[BackupStorageLocationModel]

    @strawberry.field
    def environment_count(self) -> int:
        return len(self.instance.environments)

    @classmethod
    def from_instance(
        cls, instance: BackupStorageLocationModel
    ) -> BackupStorageLocation:
        return cls(
            id=instance.id,
            name=instance.name,
            endpoint=instance.endpoint,
            bucket=instance.bucket,
            region=instance.region,
            instance=instance,
            created_on=instance.created_on,  # type: ignore[arg-type]
            updated_on=instance.updated_on,
        )
