"""CRD spec and status Python models for StyrminDeployment.

Pydantic models matching the StyrminDeployment CRD schema defined in
helm/styrmin/templates/operator/styrmin-deployment-crd.yaml.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DeploymentPhase(StrEnum):
    """Deployment lifecycle phases."""

    PENDING = "Pending"
    CREATING_PREREQUISITES = "CreatingPrerequisites"
    CREATING_HELM_RELEASE = "CreatingHelmRelease"
    CREATING_SERVICES = "CreatingServices"
    READY = "Ready"
    FAILED = "Failed"
    DELETING = "Deleting"


class ConditionStatus(StrEnum):
    TRUE = "True"
    FALSE = "False"
    UNKNOWN = "Unknown"


class ConditionType(StrEnum):
    """Standard condition types for StyrminDeployment status."""

    NETWORK_POLICIES_READY = "NetworkPoliciesReady"
    SECRETS_READY = "SecretsReady"
    HELM_RELEASE_READY = "HelmReleaseReady"
    SERVICES_READY = "ServicesReady"
    MIDDLEWARES_READY = "MiddlewaresReady"
    READY = "Ready"


class DeploymentCondition(BaseModel):
    """A single condition in the StyrminDeployment status."""

    model_config = ConfigDict(populate_by_name=True)

    type: str
    status: ConditionStatus = ConditionStatus.UNKNOWN
    reason: str = ""
    message: str = ""
    last_transition_time: str = Field(
        default="",
        alias="lastTransitionTime",
    )


class ManagedResourceCounts(BaseModel):
    """Counts of managed resources by type."""

    network_policies: int = Field(default=0, alias="networkPolicies")
    secrets: int = 0
    helm_releases: int = Field(default=0, alias="helmReleases")
    services: int = 0
    middlewares: int = 0


class HelmChartSpec(BaseModel):
    """Helm chart specification embedded in CRD."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    name: str = ""
    version: str = ""
    values_template: str = ""


class HelmRepositorySpec(BaseModel):
    """Helm repository specification embedded in CRD."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    url: str = ""


class HelmSpec(BaseModel):
    """Helm chart + repository specs embedded in CRD."""

    chart: HelmChartSpec = Field(default_factory=HelmChartSpec)
    repository: HelmRepositorySpec = Field(default_factory=HelmRepositorySpec)


class StyrminDeploymentSpec(BaseModel):
    """The spec section of a StyrminDeployment CRD."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    deployment_id: str = Field(alias="deploymentId")
    release_reference: str = Field(alias="releaseReference")
    app_name: str = Field(alias="appName")
    app_version: str = Field(alias="appVersion")
    context: dict[str, Any] = Field(default_factory=dict)
    helm: HelmSpec = Field(default_factory=HelmSpec)
    labels: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)


class StyrminDeploymentStatus(BaseModel):
    """The status section of a StyrminDeployment CRD."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    phase: DeploymentPhase = DeploymentPhase.PENDING
    message: str = ""
    conditions: list[DeploymentCondition] = Field(default_factory=list)
    managed_resources: ManagedResourceCounts = Field(
        default_factory=ManagedResourceCounts,
        alias="managedResources",
    )
