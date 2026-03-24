"""Application driver models."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class HelmChart(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    id: UUID
    name: str
    version: str
    repository: str
    value_template: str


class Action(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    name: str
    location: str
    image: str | None = None


class ComponentConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    id: UUID
    name: str
    config: Any | None = None


class ApplicationDriverVersionSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    id: UUID
    version: str
    supported_versions: str


class ApplicationDriverVersion(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    id: UUID
    application_driver_id: UUID
    version: str
    supported_versions: str
    components: Any | None = None
    component_configs: list[ComponentConfig] = []
    actions: list[Action] = []
    helm_chart: HelmChart | None = None


class ApplicationDriver(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    id: UUID
    name: str
    versions: list[ApplicationDriverVersionSummary] = []
