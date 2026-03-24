"""Backup, Restore, and BackupSchedule models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class Backup(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    id: UUID
    name: str
    status: str
    instance_id: UUID
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    size_bytes: int | None = None
    created_on: datetime | None = None
    updated_on: datetime | None = None


class Restore(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    id: UUID
    name: str
    status: str
    backup_id: UUID
    target_namespace: str
    target_instance_id: UUID | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_on: datetime | None = None
    updated_on: datetime | None = None


class BackupSchedule(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    id: UUID
    name: str
    enabled: bool
    cron_expression: str
    retention_count: int
    deployment_id: UUID
    last_backup_at: datetime | None = None
    next_backup_at: datetime | None = None
    prefect_deployment_id: UUID | None = None
    created_on: datetime | None = None
    updated_on: datetime | None = None
