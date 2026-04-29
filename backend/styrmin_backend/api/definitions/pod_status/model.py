from __future__ import annotations

from datetime import datetime
from uuid import UUID

import strawberry

from styrmin_backend.api.scalars import JSON
from styrmin_backend.db.models import PodPhase as PodPhaseDB
from styrmin_backend.db.models import PodStatus as PodStatusModel

PodPhaseType = strawberry.enum(PodPhaseDB, name="PodPhase")


@strawberry.type
class PodStatus:
    id: UUID
    deployment_id: UUID
    pod_name: str
    namespace: str
    phase: PodPhaseType  # type: ignore[valid-type]
    ready: bool
    restart_count: int
    container_statuses: JSON
    node_name: str | None = None
    component_name: str | None = None
    started_at: datetime | None = None
    last_polled_at: datetime | None = None
    created_on: datetime | None = None
    updated_on: datetime | None = None

    instance: strawberry.Private[PodStatusModel]

    @classmethod
    def from_instance(cls, instance: PodStatusModel) -> PodStatus:
        return cls(
            id=instance.id,
            deployment_id=instance.deployment_id,
            pod_name=instance.pod_name,
            namespace=instance.namespace,
            phase=PodPhaseType(instance.phase.value),  # type: ignore[call-arg]
            ready=instance.ready,
            restart_count=instance.restart_count,
            container_statuses=instance.container_statuses or [],
            node_name=instance.node_name,
            component_name=instance.component_name,
            started_at=instance.started_at,
            last_polled_at=instance.last_polled_at,
            created_on=instance.created_on,
            updated_on=instance.updated_on,
            instance=instance,
        )


@strawberry.input
class PodStatusInput:
    pod_name: str
    namespace: str
    phase: PodPhaseType  # type: ignore[valid-type]
    ready: bool
    restart_count: int
    container_statuses: JSON | None = None
    node_name: str | None = None
    component_name: str | None = None
    started_at: datetime | None = None


@strawberry.input
class DeploymentPodStatusReport:
    deployment_id: UUID
    pods: list[PodStatusInput]


@strawberry.type
class ReportPodStatusesResponse:
    success: bool
    message: str
    pods_updated: int
    pods_removed: int
