"""GraphQL types for the environment-level restore record.

Symmetric with ``environment_backup.py``: ``status`` is a **field resolver,
not a column** (research.md D2), recomputed on every read from the constituent
``Restore`` rows plus the recorded skips, so a parent status that contradicts
its constituents is structurally impossible (spec FR-004 / SC-003).

``skippedConstituents`` is the other half of the contract: every constituent
that was *not* restored is listed here with its deployment name and one of the
uniform skip reasons — zero silent skips (spec FR-007 / SC-004).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

import strawberry

from styrmin_backend.api.definitions.backup.environment_backup import (
    EnvironmentBackup as EnvironmentBackupType,
)
from styrmin_backend.api.definitions.backup.restore import Restore as RestoreType
from styrmin_backend.api.resolvers import resolve_related
from styrmin_backend.db.models import EnvironmentRestore as EnvironmentRestoreModel
from styrmin_backend.services.backup.environment import (
    SkippedConstituent as SkippedConstituentModel,
    derive_environment_operation_status,
)
from styrmin_backend.services.exceptions import EnvironmentBackupNotFoundError


@strawberry.enum(
    name="EnvironmentRestoreStatus",
    description=(
        "Derived status of an environment restore. Mirrors "
        "``EnvironmentBackupStatus`` — both project the same service-layer "
        "``EnvironmentOperationStatus``."
    ),
)
class EnvironmentRestoreStatus(str, Enum):
    """The GraphQL mirror of :class:`EnvironmentOperationStatus`.

    ``strawberry.enum`` binds one GraphQL name per Python class, and the
    backup surface already registered the shared
    :class:`EnvironmentOperationStatus` as ``EnvironmentBackupStatus``. The
    contract (contracts/graphql.md) names a separate
    ``EnvironmentRestoreStatus`` type, so this is a deliberate mirror rather
    than a second registration of the same class. The members are asserted to
    match one-for-one in
    ``backend/tests/unit/services/backup/test_environment_backup.py`` so the
    two cannot drift apart.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


@strawberry.type(
    description=(
        "A constituent that was not restored, attributed by deployment name "
        "and reason. Reasons come from a fixed vocabulary: backup failed at "
        "creation, backup not completed, backup deleted, backup expired, "
        "deployment no longer exists, deployment busy with another restore."
    )
)
class SkippedConstituent:
    deployment_id: UUID
    deployment_name: str
    reason: str

    @classmethod
    def from_model(cls, skipped: SkippedConstituentModel) -> SkippedConstituent:
        return cls(
            deployment_id=skipped.deployment_id,
            deployment_name=skipped.deployment_name,
            reason=skipped.reason,
        )


@strawberry.type
class EnvironmentRestore:
    id: UUID
    created_on: datetime
    updated_on: datetime | None = None
    environment_backup_id: UUID

    db_model: strawberry.Private[EnvironmentRestoreModel]

    @strawberry.field(
        description=(
            "Derived from the constituent restores and the recorded skips on "
            "every read — never stored, so it cannot contradict its "
            "constituents. A restore that skipped everything and restored "
            "nothing is FAILED; a restore with nothing to do at all "
            "(no constituents, no skips) is COMPLETED."
        )
    )
    def status(self) -> EnvironmentRestoreStatus:
        derived = derive_environment_operation_status(
            [restore.status for restore in self.db_model.restores],
            error_count=len(self.db_model.skipped_constituents or []),
        )
        return EnvironmentRestoreStatus(derived.value)

    @strawberry.field(description="Constituent restores dispatched by this operation.")
    def restores(self) -> list[RestoreType]:
        return [
            RestoreType.from_instance(restore) for restore in self.db_model.restores
        ]

    @strawberry.field(
        description=(
            "Constituents not restored, each with its deployment name and "
            "reason (zero silent skips)."
        )
    )
    def skipped_constituents(self) -> list[SkippedConstituent]:
        return [
            SkippedConstituent.from_model(SkippedConstituentModel.model_validate(raw))
            for raw in self.db_model.skipped_constituents or []
        ]

    @strawberry.field
    async def environment_backup(self, info: strawberry.Info) -> EnvironmentBackupType:
        return await resolve_related(
            info,
            "environment_backups",
            self.environment_backup_id,
            EnvironmentBackupType,
            EnvironmentBackupNotFoundError,
        )

    @classmethod
    def from_instance(cls, instance: EnvironmentRestoreModel) -> EnvironmentRestore:
        return cls(
            id=instance.id,
            created_on=instance.created_on,  # type: ignore[arg-type]
            updated_on=instance.updated_on,
            environment_backup_id=instance.environment_backup_id,
            db_model=instance,
        )
