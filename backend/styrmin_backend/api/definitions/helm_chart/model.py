from __future__ import annotations

from uuid import UUID

import strawberry

from styrmin_backend.db.models import HelmChart as HelmChartModel


@strawberry.type
class HelmChart:
    id: UUID
    name: str
    version: str
    value_template: str

    instance: strawberry.Private[HelmChartModel]

    @strawberry.field
    def repository(self) -> str:
        return self.instance.repository.url

    @classmethod
    def from_instance(cls, instance: HelmChartModel) -> HelmChart:
        return cls(
            id=instance.id,
            name=instance.name,
            version=instance.version,
            instance=instance,
            value_template=instance.values_template,
        )
