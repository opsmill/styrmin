"""This module provides input models for computing the Styrmin context.

It was implemented at a time the context was understood to have to be computed on Styrmin worker side.
This would ease the process of passing a large number of parameters to the worker prefect flow.

Since the context is now computed on the server side, these models are not relevant anymore.
They are, however, still in use.
"""

from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, RootModel

from .config import (
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
)


class ConfigInput(BaseModel):
    cluster: ClusterConfig
    environment: EnvironmentConfig
    deployment: DeploymentConfig


class InstanceInput(BaseModel):
    namespace: str
    release_reference: str
    deployment_id: UUID


class ChartInput(BaseModel):
    id: UUID
    name: str
    version: str
    values_template: str


class RepositoryInput(BaseModel):
    id: UUID
    url: str


class ApplicationInput(BaseModel):
    name: str
    version: str
    chart: ChartInput
    repository: RepositoryInput


class Label(RootModel):
    root: dict[str, str]


class IdentifierInput(BaseModel):
    label: Label


class ComponentConfigInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    identifier: IdentifierInput


class ComponentInput(BaseModel):
    config: ComponentConfigInput
    name: str
    enabled: bool


class UtilityKindInput(Enum):
    INGRESS = "ingress"
    SERVICE_DISCOVERY = "service-discovery"


class UtilityInput(BaseModel):
    kind: UtilityKindInput


class ContextInput(BaseModel):
    config: ConfigInput
    instance: InstanceInput
    application: ApplicationInput
    components: list[ComponentInput]
    labels: dict[str, Any] = Field(default_factory=dict)
    utilities: list[UtilityInput] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    environment_name: str = ""
    # Names the bound driver version in log messages only (``driver_version_label``).
    driver_version: str = ""
