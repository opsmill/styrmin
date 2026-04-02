"""Application driver models (hand-written — no generated equivalents)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApplicationDriverVersionSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    id: UUID
    version: str
    supported_versions: str


class ApplicationDriver(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    id: UUID
    name: str
    versions: list[ApplicationDriverVersionSummary] = []
