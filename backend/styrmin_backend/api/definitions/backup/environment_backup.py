"""GraphQL types for the environment-level backup parent record.

The defining property of this surface is that ``status`` is a **field
resolver, not a column** (research.md D2): it is recomputed on every read from
the constituent ``Backup`` rows plus the recorded creation errors, which is
what makes a parent status that contradicts its constituents structurally
impossible (spec FR-004 / SC-003).

``constituents`` is the second derived projection: it joins the captured
``deployment_snapshots`` against the linked backups and the recorded errors so
every eligible deployment shows up exactly once, as one of

* a live constituent backup,
* an attributable creation error (spec FR-005), or
* a gap — neither backup nor error — left by a constituent that was deleted
  individually after the snapshot was taken (spec US3).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

import strawberry

from styrmin_backend.api.definitions.backup.backup import Backup as BackupType
from styrmin_backend.api.definitions.environment.model import (
    Environment as EnvironmentType,
)
from styrmin_backend.api.resolvers import resolve_related
from styrmin_backend.api.scalars import JSON
from styrmin_backend.db.models import EnvironmentBackup as EnvironmentBackupModel
from styrmin_backend.services.backup.environment import (
    ConstituentError,
    DeploymentSnapshot as DeploymentSnapshotModel,
    EnvironmentOperationStatus,
    derive_environment_operation_status,
)
from styrmin_backend.services.exceptions import EnvironmentNotFoundError

if TYPE_CHECKING:
    # Type-check-only: ``environment_restore`` imports this module at runtime
    # for its own ``environmentBackup`` field, so the pairing is a cycle unless
    # one direction stays deferred. ``strawberry.lazy`` resolves the annotation
    # at schema-build time.
    from styrmin_backend.api.definitions.backup.environment_restore import (
        EnvironmentRestore,
    )

# NOTE: ``EnvironmentOperationStatus`` is one Python enum shared by both
# parents, but ``strawberry.enum`` attaches its definition to the class, so it
# can only be registered under one GraphQL name. The backup surface claims
# ``EnvironmentBackupStatus``; the restore surface (contracts/graphql.md
# ``EnvironmentRestoreStatus``) must therefore declare its own enum mirror
# rather than re-registering this one.
EnvironmentBackupStatus = strawberry.enum(
    EnvironmentOperationStatus, name="EnvironmentBackupStatus"
)


@strawberry.type(
    description=(
        "The declared state of one deployment captured at backup time — "
        "enough to recreate it later (clone readiness)."
    )
)
class DeploymentSnapshot:
    deployment_id: UUID
    deployment_name: str
    instance_id: UUID
    driver_name: str
    driver_version: str
    driver_fingerprint: str | None
    application_version: str
    config: JSON | None
    parameters: JSON | None

    @classmethod
    def from_model(cls, snapshot: DeploymentSnapshotModel) -> DeploymentSnapshot:
        return cls(
            deployment_id=snapshot.deployment_id,
            deployment_name=snapshot.deployment_name,
            instance_id=snapshot.instance_id,
            driver_name=snapshot.driver_name,
            driver_version=snapshot.driver_version,
            driver_fingerprint=snapshot.driver_fingerprint,
            application_version=snapshot.application_version,
            config=snapshot.config,
            parameters=snapshot.parameters,
        )


@strawberry.type(
    description=(
        "One eligible deployment's outcome in the snapshot. ``backup`` is set "
        "when a constituent backup exists, ``error`` when creation failed. "
        "Both null means the constituent was deleted individually after the "
        "snapshot was taken — the gap is deliberately visible."
    )
)
class EnvironmentBackupConstituent:
    deployment_id: UUID
    deployment_name: str
    backup: BackupType | None
    error: str | None


@strawberry.type
class EnvironmentBackup:
    id: UUID
    name: str
    created_on: datetime
    updated_on: datetime | None = None
    environment_id: UUID

    db_model: strawberry.Private[EnvironmentBackupModel]

    @strawberry.field(
        description=(
            "Derived from the constituent backups and recorded creation "
            "errors on every read — never stored, so it cannot contradict "
            "its constituents. An environment with no eligible deployments "
            "yields a config-only snapshot that is COMPLETED immediately."
        )
    )
    def status(self) -> EnvironmentBackupStatus:  # type: ignore[valid-type]
        return derive_environment_operation_status(
            [backup.status for backup in self.db_model.backups],
            error_count=len(self.db_model.constituent_errors or []),
        )

    @strawberry.field(description="Environment config captured at backup time.")
    def environment_config(self) -> JSON | None:
        return self.db_model.environment_config

    @strawberry.field(
        description=(
            "Per-deployment declared state captured at backup time (clone readiness)."
        )
    )
    def deployment_snapshots(self) -> list[DeploymentSnapshot]:
        return [
            DeploymentSnapshot.from_model(DeploymentSnapshotModel.model_validate(raw))
            for raw in self.db_model.deployment_snapshots or []
        ]

    @strawberry.field(
        description=(
            "One entry per eligible deployment: its constituent backup, its "
            "creation error, or neither when the constituent was deleted."
        )
    )
    def constituents(self) -> list[EnvironmentBackupConstituent]:
        # Constituent backups join to snapshots on the instance they backed
        # up; errors join on the deployment, because a constituent that failed
        # at creation never got an instance-scoped row.
        backups_by_instance = {
            backup.instance_id: backup for backup in self.db_model.backups
        }
        errors_by_deployment = {
            error.deployment_id: error.error
            for error in (
                ConstituentError.model_validate(raw)
                for raw in self.db_model.constituent_errors or []
            )
        }

        constituents: list[EnvironmentBackupConstituent] = []
        for raw in self.db_model.deployment_snapshots or []:
            snapshot = DeploymentSnapshotModel.model_validate(raw)
            backup = backups_by_instance.get(snapshot.instance_id)
            constituents.append(
                EnvironmentBackupConstituent(
                    deployment_id=snapshot.deployment_id,
                    deployment_name=snapshot.deployment_name,
                    backup=BackupType.from_instance(backup) if backup else None,
                    error=errors_by_deployment.get(snapshot.deployment_id),
                )
            )
        return constituents

    @strawberry.field(
        description="Coordinated restores performed from this snapshot, newest first."
    )
    def restores(
        self,
    ) -> list[
        Annotated[
            "EnvironmentRestore",
            strawberry.lazy(
                "styrmin_backend.api.definitions.backup.environment_restore"
            ),
        ]
    ]:
        # Imported inside the resolver: ``environment_restore`` imports this
        # module for its own ``environmentBackup`` field, so a module-level
        # import here would be a cycle. ``strawberry.lazy`` above is what lets
        # the annotation resolve at schema-build time.
        from styrmin_backend.api.definitions.backup.environment_restore import (
            EnvironmentRestore,
        )

        return [
            EnvironmentRestore.from_instance(environment_restore)
            for environment_restore in sorted(
                self.db_model.restores,
                key=lambda restore: restore.created_on,  # type: ignore[arg-type,return-value]
                reverse=True,
            )
        ]

    @strawberry.field
    async def environment(self, info: strawberry.Info) -> EnvironmentType:
        return await resolve_related(
            info,
            "environments",
            self.environment_id,
            EnvironmentType,
            EnvironmentNotFoundError,
        )

    @classmethod
    def from_instance(cls, instance: EnvironmentBackupModel) -> EnvironmentBackup:
        return cls(
            id=instance.id,
            name=instance.name,
            created_on=instance.created_on,  # type: ignore[arg-type]
            updated_on=instance.updated_on,
            environment_id=instance.environment_id,
            db_model=instance,
        )
