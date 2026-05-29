"""
Obsolete payloads models. To be removed when extracted properly.
"""

from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class UtilityKind(str, Enum):
    """Enum for the different utility kinds."""

    INGRESS = "ingress"
    SERVICE_DISCOVERY = "service-discovery"


class HelmChartPayload(BaseModel):
    """Helm chart payload model."""

    helm_chart_id: UUID
    helm_chart_name: str
    helm_chart_version: str
    helm_repository_id: UUID
    helm_repository_url: str
    values_template: str


class UtilityPayload(BaseModel):
    """Utility payload model."""

    utility_kind: UtilityKind


class ApplicationInfoPayload(BaseModel):
    """Application info payload model."""

    name: str
    version: str


class ApplicationPayload(BaseModel):
    """Application payload model."""

    instance_id: UUID
    info: ApplicationInfoPayload

    helm_chart: HelmChartPayload


class ContextPayload(BaseModel):
    """Context payload model."""

    application: ApplicationPayload
    environment: dict
    cluster: dict
    config: dict
    components: dict | None = None


class HookDeploymentsPayload(BaseModel):
    """Hook deployments payload model."""

    core_hook: UUID
    pre_hook: UUID | None = None
    post_hook: UUID | None = None
