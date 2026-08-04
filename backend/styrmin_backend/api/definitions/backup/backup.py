from __future__ import annotations

from datetime import datetime
from uuid import UUID

import strawberry
from loguru import logger

from styrmin_backend.api.definitions.deployment.model import (
    ApplicationInstance as ApplicationInstanceType,
)
from styrmin_backend.api.resolvers import resolve_related
from styrmin_backend.db.models import Backup as BackupModel
from styrmin_backend.db.models import BackupStatus as BackupStatusDB
from styrmin_backend.services.backup.metadata import read_backup_metadata
from styrmin_backend.services.exceptions import InstanceNotFoundError

BackupStatusType = strawberry.enum(BackupStatusDB, name="BackupStatus")


@strawberry.type
class ComponentBackupStatus:
    component_name: str
    status: str
    size_bytes: int | None = None
    error_message: str | None = None


@strawberry.type
class Backup:
    id: UUID
    name: str
    status: str
    created_on: datetime
    updated_on: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    size_bytes: int | None = None
    error_message: str | None = None
    instance_id: UUID

    db_model: strawberry.Private[BackupModel]

    @strawberry.field
    async def instance(self, info: strawberry.Info) -> ApplicationInstanceType:
        return await resolve_related(
            info,
            "application_instances",
            self.instance_id,
            ApplicationInstanceType,
            InstanceNotFoundError,
        )

    @strawberry.field
    def component_statuses(self) -> list[ComponentBackupStatus] | None:
        statuses = self.db_model.component_statuses
        if not statuses:
            return None
        return [
            ComponentBackupStatus(
                component_name=name,
                status=data.get("status", "unknown"),
                size_bytes=data.get("size_bytes"),
                error_message=data.get("error_message"),
            )
            for name, data in statuses.items()
        ]

    @strawberry.field(
        description=(
            "Retention TTL applied to this backup when it was created "
            '(e.g. ``"2160h"``). Null for backups taken before retention was '
            "recorded."
        )
    )
    def ttl(self) -> str | None:
        # ``read_backup_metadata`` narrows the untyped JSON column to the
        # writer's key contract, so the subscript below is the same key the
        # backup workflow wrote — a misspelling here is a type error, not a
        # field that silently reports null.
        metadata = read_backup_metadata(self.db_model.metadata_)
        if "ttl" not in metadata:
            return None
        value = metadata["ttl"]
        return str(value) if value is not None else None

    @strawberry.field(
        description=(
            "Expiration reported by Velero for this backup. Null when no "
            "expiration was recorded — a backup Velero stored nothing for, or "
            "a backup taken before expiry was recorded. A backup whose status "
            "is FAILED can still carry an expiration: Velero's "
            "PartiallyFailed phase is stored, does expire, and is reported as "
            "FAILED here."
        )
    )
    def expires_at(self) -> datetime | None:
        metadata = read_backup_metadata(self.db_model.metadata_)
        if "expires_at" not in metadata:
            return None
        raw = metadata["expires_at"]
        if raw is None:
            return None
        if not isinstance(raw, str):
            # Same degrade-to-null contract as the unparseable case below, but
            # it means something different: the stored value is not even a
            # timestamp, so it never came from the backup workflow.
            logger.warning(
                "Backup {backup_id} has a non-string expires_at metadata "
                "value {raw!r} ({type_name}); reporting null",
                backup_id=self.id,
                raw=raw,
                type_name=type(raw).__name__,
            )
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            # A malformed stored timestamp must not fail the whole backup
            # query — the field is nullable precisely so partial metadata
            # degrades to "unknown" rather than an error.
            logger.warning(
                "Backup {backup_id} has an unparseable expires_at metadata "
                "value {raw!r}; reporting null",
                backup_id=self.id,
                raw=raw,
            )
            return None

    @classmethod
    def from_instance(cls, instance: BackupModel) -> Backup:
        return cls(
            id=instance.id,
            name=instance.name,
            status=instance.status.value,
            created_on=instance.created_on,  # type: ignore[arg-type]
            updated_on=instance.updated_on,
            started_at=instance.started_at,
            completed_at=instance.completed_at,
            size_bytes=instance.size_bytes,
            error_message=instance.error_message,
            instance_id=instance.instance_id,
            db_model=instance,
        )
