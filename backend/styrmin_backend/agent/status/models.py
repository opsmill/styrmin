"""Pydantic models matching the GraphQL types used by the status reporter.

These models serve as a contract between the agent and the backend GraphQL API.
If the schema changes, validation failures here surface the mismatch at test
time rather than silently in production.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PodPhase(str, Enum):
    """Must match the GraphQL ``PodPhase`` enum exactly."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Pod status report (mutation ReportPodStatuses)
# ---------------------------------------------------------------------------


class PodStatusData(BaseModel):
    """Matches GraphQL ``PodStatusInput``."""

    model_config = ConfigDict(populate_by_name=True)

    pod_name: str = Field(alias="podName")
    namespace: str
    phase: PodPhase
    ready: bool
    restart_count: int = Field(alias="restartCount")
    container_statuses: list[dict] | None = Field(
        default=None, alias="containerStatuses"
    )
    node_name: str | None = Field(default=None, alias="nodeName")
    component_name: str | None = Field(default=None, alias="componentName")
    started_at: str | None = Field(default=None, alias="startedAt")


class DeploymentPodStatusReport(BaseModel):
    """Matches GraphQL ``DeploymentPodStatusReport`` input."""

    model_config = ConfigDict(populate_by_name=True)

    deployment_id: str = Field(alias="deploymentId")
    pods: list[PodStatusData]


class ReportPodStatusesResponse(BaseModel):
    """Matches GraphQL ``ReportPodStatusesResponse`` type."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool
    message: str
    pods_updated: int = Field(alias="podsUpdated")
    pods_removed: int = Field(alias="podsRemoved")


# ---------------------------------------------------------------------------
# Deployment status report (mutation ReportDeploymentStatuses)
# ---------------------------------------------------------------------------


class CrdConditionData(BaseModel):
    """Matches GraphQL ``CrdConditionInput``."""

    model_config = ConfigDict(populate_by_name=True)

    type: str
    status: str
    reason: str | None = None
    message: str | None = None
    last_transition_time: str | None = Field(default=None, alias="lastTransitionTime")


class ManagedResourceCountsData(BaseModel):
    """Matches GraphQL ``ManagedResourceCountsInput``."""

    model_config = ConfigDict(populate_by_name=True)

    network_policies: int = Field(default=0, alias="networkPolicies")
    secrets: int = Field(default=0, alias="secrets")
    helm_releases: int = Field(default=0, alias="helmReleases")
    services: int = Field(default=0, alias="services")
    middlewares: int = Field(default=0, alias="middlewares")


class DeploymentStatusReport(BaseModel):
    """Matches GraphQL ``DeploymentStatusReportInput``."""

    model_config = ConfigDict(populate_by_name=True)

    deployment_id: str = Field(alias="deploymentId")
    instance_id: str | None = Field(default=None, alias="instanceId")
    phase: str
    display_state: str = Field(default="Deploying", alias="displayState")
    message: str | None = None
    conditions: list[CrdConditionData] | None = None
    managed_resource_counts: ManagedResourceCountsData | None = Field(
        default=None, alias="managedResourceCounts"
    )


class ReportDeploymentStatusesResponse(BaseModel):
    """Matches GraphQL ``ReportDeploymentStatusesResponse`` type."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool
    message: str
    statuses_updated: int = Field(alias="statusesUpdated")
    deployments_updated: int = Field(alias="deploymentsUpdated")


# ---------------------------------------------------------------------------
# Deployment list query (query ListDeploymentsForStatus)
# ---------------------------------------------------------------------------


class DeploymentForStatus(BaseModel):
    id: str
    status: str


class EnvironmentForStatus(BaseModel):
    deployments: list[DeploymentForStatus]


# ---------------------------------------------------------------------------
# Generic GraphQL response wrapper
# ---------------------------------------------------------------------------


class GraphQLResponse(BaseModel):
    """Thin wrapper for raw GraphQL JSON responses."""

    data: dict | None = None
    errors: list[dict] | None = None
