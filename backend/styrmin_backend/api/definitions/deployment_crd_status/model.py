from __future__ import annotations

from datetime import datetime
from uuid import UUID

import strawberry

from styrmin_backend.db.models import DeploymentCrdStatus as DeploymentCrdStatusModel


@strawberry.type
class CrdConditionType:
    type: str
    status: str
    reason: str | None = None
    message: str | None = None
    last_transition_time: datetime | None = None


@strawberry.type
class ManagedResourceCountsType:
    network_policies: int = 0
    secrets: int = 0
    helm_releases: int = 0
    services: int = 0
    middlewares: int = 0

    @classmethod
    def from_dict(cls, data: dict | None) -> ManagedResourceCountsType | None:
        if data is None:
            return None
        return cls(
            network_policies=data.get("networkPolicies", 0),
            secrets=data.get("secrets", 0),
            helm_releases=data.get("helmReleases", 0),
            services=data.get("services", 0),
            middlewares=data.get("middlewares", 0),
        )


@strawberry.type
class DeploymentCrdStatusType:
    id: UUID
    deployment_id: UUID
    phase: str
    message: str | None = None
    conditions: list[CrdConditionType] = strawberry.field(default_factory=list)
    managed_resource_counts: ManagedResourceCountsType | None = None
    last_polled_at: datetime | None = None
    created_on: datetime | None = None
    updated_on: datetime | None = None

    @classmethod
    def from_instance(
        cls, instance: DeploymentCrdStatusModel
    ) -> DeploymentCrdStatusType:
        conditions = []
        for cond in instance.conditions or []:
            conditions.append(
                CrdConditionType(
                    type=cond.get("type", ""),
                    status=cond.get("status", "Unknown"),
                    reason=cond.get("reason"),
                    message=cond.get("message"),
                    last_transition_time=None,
                )
            )

        return cls(
            id=instance.id,
            deployment_id=instance.deployment_id,
            phase=instance.phase,
            message=instance.message,
            conditions=conditions,
            managed_resource_counts=ManagedResourceCountsType.from_dict(
                instance.managed_resource_counts
            ),
            last_polled_at=instance.last_polled_at,
            created_on=instance.created_on,
            updated_on=instance.updated_on,
        )


@strawberry.input
class CrdConditionInput:
    type: str
    status: str
    reason: str | None = None
    message: str | None = None
    last_transition_time: datetime | None = None


@strawberry.input
class ManagedResourceCountsInput:
    network_policies: int = 0
    secrets: int = 0
    helm_releases: int = 0
    services: int = 0
    middlewares: int = 0


@strawberry.input
class DeploymentCrdStatusReportInput:
    deployment_id: UUID
    phase: str
    display_state: str | None = None
    message: str | None = None
    conditions: list[CrdConditionInput] | None = None
    managed_resource_counts: ManagedResourceCountsInput | None = None


@strawberry.type
class ReportCrdStatusesResponse:
    success: bool
    message: str
    statuses_updated: int
    deployments_updated: int
