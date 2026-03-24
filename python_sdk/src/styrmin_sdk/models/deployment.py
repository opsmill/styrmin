"""Deployment model."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApplicationInstance(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    id: UUID
    status: str


class Component(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    id: UUID
    name: str
    enabled: bool


class Deployment(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    id: UUID
    name: str
    status: str
    config: Any | None = None
    application_version: str
    application_driver_version_id: UUID
    environment_id: UUID
    application_instance: ApplicationInstance | None = None
    components: list[Component] = []
