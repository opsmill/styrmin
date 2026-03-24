"""Backup storage location model."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class BackupStorageLocation(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    id: UUID
    name: str
    endpoint: str
    bucket: str
    region: str
    created_on: datetime
    updated_on: datetime | None = None
    environment_count: int
