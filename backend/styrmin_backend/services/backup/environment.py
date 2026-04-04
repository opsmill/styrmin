"""Environment-level backup and restore service functions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Sequence
from uuid import UUID

from loguru import logger

from sqlmodel import select

from styrmin_backend.db.models import (
    Backup,
    BackupStatus,
    Deployment,
    EnvironmentBackup,
    EnvironmentBackupStatus,
    EnvironmentRestore,
    EnvironmentRestoreStatus,
    Restore,
    RestoreStatus,
)
from styrmin_backend.services.exceptions import (
    EnvironmentBackupNotFoundError,
    EnvironmentBackupOperationInProgressError,
    EnvironmentBackupValidationError,
    EnvironmentNotFoundError,
    EnvironmentRestoreNotFoundError,
)

if TYPE_CHECKING:
    from styrmin_backend.services.unit_of_work import UnitOfWork


async def create_environment_backup(
    environment_id: UUID,
    uow: UnitOfWork,
    name: str | None = None,
    max_concurrency: int = 5,
    timeout: int = 3600,
) -> EnvironmentBackup:
    """Create a coordinated backup of all active instances in an environment."""
    async with uow:
        # Validate environment exists
        environment = await uow.environments.get(environment_id)
        if environment is None:
            raise EnvironmentNotFoundError()

        # FR-012: Environment must have a BackupStorageLocation
        if environment.backup_storage_location_id is None:
            raise EnvironmentBackupValidationError(
                "Environment does not have a backup storage location assigned"
            )

        # Find all deployments with active instances
        result = await uow.session.exec(
            select(Deployment).where(Deployment.environment_id == environment_id)
        )
        deployments = result.all()
        active_instances = []
        skipped_instances = []

        for deployment in deployments:
            if deployment.active_application_instance_id is None:
                continue
            instance = await uow.application_instances.get(
                deployment.active_application_instance_id
            )
            if instance is None:
                continue

            # FR-011: Skip instances with in-progress backups
            existing = await uow.backups.has_in_progress_backup(instance.id)
            if existing:
                skipped_instances.append(
                    {
                        "instance_id": str(instance.id),
                        "deployment_name": deployment.name,
                        "reason": "backup_in_progress",
                    }
                )
                continue

            active_instances.append((deployment, instance))

        # FR-013: Must have at least one active instance to back up
        if not active_instances:
            raise EnvironmentBackupValidationError(
                "No active application instances available for backup in this environment"
            )

        # Create EnvironmentBackup record
        env_backup = EnvironmentBackup(
            name=name or "placeholder",
            status=EnvironmentBackupStatus.PENDING,
            environment_id=environment_id,
            max_concurrency=max_concurrency,
            timeout=timeout,
            metadata_={
                "skipped_instances": skipped_instances,
                "constituent_count": len(active_instances),
                "completed_count": 0,
                "failed_count": 0,
            },
        )
        env_backup = await uow.environment_backups.create(env_backup)

        if name is None:
            env_backup.name = f"env-backup-{env_backup.id}"

        # Create constituent Backup records for each active instance
        for deployment, instance in active_instances:
            backup = Backup(
                name=f"styrmin-{env_backup.id}-{instance.id}",
                status=BackupStatus.PENDING,
                instance_id=instance.id,
                environment_backup_id=env_backup.id,
                metadata_={"timeout": timeout},
            )
            await uow.backups.create(backup)

        await uow.commit()
        await uow.session.refresh(env_backup)

        logger.info(
            f"Created environment backup {env_backup.id} ({env_backup.name}) "
            f"for environment {environment_id} with {len(active_instances)} constituents"
        )
        return env_backup


async def update_environment_backup_status(
    environment_backup_id: UUID,
    uow: UnitOfWork,
    status: EnvironmentBackupStatus | None = None,
    error_message: str | None = None,
) -> EnvironmentBackup:
    """Recompute and update parent status from constituent backup statuses."""
    async with uow:
        env_backup = await uow.environment_backups.get(environment_backup_id)
        if env_backup is None:
            raise EnvironmentBackupNotFoundError()

        if status is not None:
            env_backup.status = status
        else:
            # Aggregate status from constituent backups
            result = await uow.session.exec(
                select(Backup).where(
                    Backup.environment_backup_id == environment_backup_id
                )
            )
            constituent_backups = list(result.all())

            statuses = [b.status for b in constituent_backups]

            if not statuses:
                env_backup.status = EnvironmentBackupStatus.FAILED
            elif all(s == BackupStatus.COMPLETED for s in statuses):
                env_backup.status = EnvironmentBackupStatus.COMPLETED
            elif all(s == BackupStatus.FAILED for s in statuses):
                env_backup.status = EnvironmentBackupStatus.FAILED
            elif all(s == BackupStatus.PENDING for s in statuses):
                env_backup.status = EnvironmentBackupStatus.PENDING
            elif any(
                s in (BackupStatus.PENDING, BackupStatus.IN_PROGRESS) for s in statuses
            ):
                env_backup.status = EnvironmentBackupStatus.IN_PROGRESS
            else:
                # Mix of COMPLETED and FAILED
                env_backup.status = EnvironmentBackupStatus.PARTIALLY_FAILED

        if (
            env_backup.status == EnvironmentBackupStatus.IN_PROGRESS
            and env_backup.started_at is None
        ):
            env_backup.started_at = datetime.now(timezone.utc)

        if env_backup.status in (
            EnvironmentBackupStatus.COMPLETED,
            EnvironmentBackupStatus.PARTIALLY_FAILED,
            EnvironmentBackupStatus.FAILED,
        ):
            env_backup.completed_at = datetime.now(timezone.utc)

        if error_message is not None:
            env_backup.error_message = error_message

        await uow.commit()
        await uow.session.refresh(env_backup)
        return env_backup


async def create_environment_restore(
    environment_backup_id: UUID,
    uow: UnitOfWork,
) -> EnvironmentRestore:
    """Create a coordinated restore from a completed/partially-completed environment backup."""
    async with uow:
        env_backup = await uow.environment_backups.get(environment_backup_id)
        if env_backup is None:
            raise EnvironmentBackupNotFoundError()

        # Validate source backup status
        if env_backup.status not in (
            EnvironmentBackupStatus.COMPLETED,
            EnvironmentBackupStatus.PARTIALLY_FAILED,
        ):
            raise EnvironmentBackupValidationError(
                f"Cannot restore from environment backup with status '{env_backup.status.value}'. "
                "Only COMPLETED or PARTIALLY_FAILED backups can be restored."
            )

        # Check no concurrent restore in progress
        existing_restores = await uow.environment_restores.get_by_environment_backup_id(
            environment_backup_id, status=EnvironmentRestoreStatus.IN_PROGRESS
        )
        if existing_restores:
            raise EnvironmentBackupOperationInProgressError(
                "A restore is already in progress for this environment backup"
            )

        # Create EnvironmentRestore record
        env_restore = EnvironmentRestore(
            name="placeholder",
            status=EnvironmentRestoreStatus.PENDING,
            environment_backup_id=environment_backup_id,
            metadata_={
                "skipped_backups": [],
                "constituent_count": 0,
                "completed_count": 0,
                "failed_count": 0,
            },
        )
        env_restore = await uow.environment_restores.create(env_restore)
        env_restore.name = f"env-restore-{env_restore.id}"

        # Create constituent Restore records for COMPLETED backups only
        result = await uow.session.exec(
            select(Backup).where(Backup.environment_backup_id == environment_backup_id)
        )
        constituent_backups = list(result.all())

        skipped_backups = []
        restore_count = 0

        for backup in constituent_backups:
            if backup.status != BackupStatus.COMPLETED:
                skipped_backups.append(
                    {
                        "backup_id": str(backup.id),
                        "reason": "backup_not_completed",
                    }
                )
                continue

            # Resolve target namespace from backup's instance -> deployment
            instance = await uow.application_instances.get(backup.instance_id)
            deployment_id = instance.deployment_id if instance else None
            target_namespace = f"styrmin-{deployment_id}" if deployment_id else ""

            restore = Restore(
                name=f"styrmin-{env_restore.id}-{backup.id}",
                status=RestoreStatus.PENDING,
                target_namespace=target_namespace,
                backup_id=backup.id,
                environment_restore_id=env_restore.id,
                target_instance_id=backup.instance_id,
                metadata_={"timeout": 7200},
            )
            await uow.restores.create(restore)
            restore_count += 1

        env_restore.metadata_ = {
            "skipped_backups": skipped_backups,
            "constituent_count": restore_count,
            "completed_count": 0,
            "failed_count": 0,
        }

        await uow.commit()
        await uow.session.refresh(env_restore)

        logger.info(
            f"Created environment restore {env_restore.id} ({env_restore.name}) "
            f"from environment backup {environment_backup_id} with {restore_count} constituents"
        )
        return env_restore


async def update_environment_restore_status(
    environment_restore_id: UUID,
    uow: UnitOfWork,
    status: EnvironmentRestoreStatus | None = None,
    error_message: str | None = None,
) -> EnvironmentRestore:
    """Recompute and update parent status from constituent restore statuses."""
    async with uow:
        env_restore = await uow.environment_restores.get(environment_restore_id)
        if env_restore is None:
            raise EnvironmentRestoreNotFoundError()

        if status is not None:
            env_restore.status = status
        else:
            result = await uow.session.exec(
                select(Restore).where(
                    Restore.environment_restore_id == environment_restore_id
                )
            )
            constituent_restores = list(result.all())

            statuses = [r.status for r in constituent_restores]

            if not statuses:
                env_restore.status = EnvironmentRestoreStatus.FAILED
            elif all(s == RestoreStatus.COMPLETED for s in statuses):
                env_restore.status = EnvironmentRestoreStatus.COMPLETED
            elif all(s == RestoreStatus.FAILED for s in statuses):
                env_restore.status = EnvironmentRestoreStatus.FAILED
            elif all(s == RestoreStatus.PENDING for s in statuses):
                env_restore.status = EnvironmentRestoreStatus.PENDING
            elif any(
                s in (RestoreStatus.PENDING, RestoreStatus.IN_PROGRESS)
                for s in statuses
            ):
                env_restore.status = EnvironmentRestoreStatus.IN_PROGRESS
            else:
                env_restore.status = EnvironmentRestoreStatus.PARTIALLY_FAILED

        if (
            env_restore.status == EnvironmentRestoreStatus.IN_PROGRESS
            and env_restore.started_at is None
        ):
            env_restore.started_at = datetime.now(timezone.utc)

        if env_restore.status in (
            EnvironmentRestoreStatus.COMPLETED,
            EnvironmentRestoreStatus.PARTIALLY_FAILED,
            EnvironmentRestoreStatus.FAILED,
        ):
            env_restore.completed_at = datetime.now(timezone.utc)

        if error_message is not None:
            env_restore.error_message = error_message

        await uow.commit()
        await uow.session.refresh(env_restore)
        return env_restore


async def get_environment_backup(
    environment_backup_id: UUID, uow: UnitOfWork
) -> EnvironmentBackup:
    """Get an environment backup by ID."""
    async with uow:
        env_backup = await uow.environment_backups.get(environment_backup_id)
        if env_backup is None:
            raise EnvironmentBackupNotFoundError()
        return env_backup


async def get_environment_backups(
    environment_id: UUID,
    uow: UnitOfWork,
    status: EnvironmentBackupStatus | None = None,
) -> Sequence[EnvironmentBackup]:
    """Get all environment backups for an environment."""
    async with uow:
        return await uow.environment_backups.get_by_environment_id(
            environment_id, status=status
        )


async def get_environment_restore(
    environment_restore_id: UUID, uow: UnitOfWork
) -> EnvironmentRestore:
    """Get an environment restore by ID."""
    async with uow:
        env_restore = await uow.environment_restores.get(environment_restore_id)
        if env_restore is None:
            raise EnvironmentRestoreNotFoundError()
        return env_restore


async def get_environment_restores(
    environment_backup_id: UUID,
    uow: UnitOfWork,
    status: EnvironmentRestoreStatus | None = None,
) -> Sequence[EnvironmentRestore]:
    """Get all environment restores for an environment backup."""
    async with uow:
        return await uow.environment_restores.get_by_environment_backup_id(
            environment_backup_id, status=status
        )


async def delete_environment_backup(
    environment_backup_id: UUID, uow: UnitOfWork
) -> None:
    """Delete an environment backup and cascade to all constituents."""
    async with uow:
        env_backup = await uow.environment_backups.get(environment_backup_id)
        if env_backup is None:
            raise EnvironmentBackupNotFoundError()

        # FR-010: Check no in-progress operations
        result = await uow.session.exec(
            select(Backup).where(
                Backup.environment_backup_id == environment_backup_id,
                Backup.status.in_([BackupStatus.PENDING, BackupStatus.IN_PROGRESS]),  # type: ignore[attr-defined]
            )
        )
        in_progress_backups = result.all()
        if in_progress_backups:
            raise EnvironmentBackupOperationInProgressError(
                "Cannot delete environment backup while constituent backups are in progress"
            )

        # Check for in-progress restores across all constituent restores
        result = await uow.session.exec(
            select(Restore).where(
                Restore.environment_restore_id.isnot(None),  # type: ignore[union-attr]
                Restore.status.in_([RestoreStatus.PENDING, RestoreStatus.IN_PROGRESS]),  # type: ignore[attr-defined]
            )
        )
        # Filter to restores that belong to this environment backup's env restores
        env_restore_ids_result = await uow.session.exec(
            select(EnvironmentRestore.id).where(
                EnvironmentRestore.environment_backup_id == environment_backup_id
            )
        )
        env_restore_ids = set(env_restore_ids_result.all())

        result = await uow.session.exec(
            select(Restore).where(
                Restore.environment_restore_id.in_(env_restore_ids),  # type: ignore[union-attr]
                Restore.status.in_([RestoreStatus.PENDING, RestoreStatus.IN_PROGRESS]),  # type: ignore[attr-defined]
            )
        )
        in_progress_restores = result.all()
        if in_progress_restores:
            raise EnvironmentBackupOperationInProgressError(
                "Cannot delete environment backup while constituent restores are in progress"
            )

        await uow.environment_backups.delete(env_backup)
        await uow.commit()

        logger.info(f"Deleted environment backup {environment_backup_id}")
