from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Sequence
from uuid import UUID

from loguru import logger

from styrmin_backend.agent.service.kubernetes.velero.resources import VeleroBackupHook
from styrmin_backend.db.models import (
    Backup,
    BackupStatus,
    DeploymentState,
    Restore,
    RestoreStatus,
)
from styrmin_backend.services.backup.strategies.action import ActionBackupStrategy
from styrmin_backend.services.backup.strategies.base import BackupStrategy
from styrmin_backend.services.backup.strategies.disk import DiskSnapshotStrategy
from styrmin_backend.services.backup.strategies.mariadb import MariadbBackupStrategy
from styrmin_backend.services.backup.strategies.mongodb import MongodbBackupStrategy
from styrmin_backend.services.backup.strategies.neo4j import Neo4jBackupStrategy
from styrmin_backend.services.backup.strategies.postgres import PostgresBackupStrategy
from styrmin_backend.services.exceptions import (
    BackupAlreadyInProgressError,
    BackupNotFoundError,
    InternalDeploymentError,
    RestoreAlreadyInProgressError,
    RestoreNotFoundError,
)

if TYPE_CHECKING:
    from styrmin_backend.services.unit_of_work import UnitOfWork

# Default timeout values (seconds)
DEFAULT_BACKUP_TIMEOUT: int = 3600  # 1 hour
DEFAULT_RESTORE_TIMEOUT: int = 7200  # 2 hours

STRATEGY_MAP: dict[str, type[BackupStrategy]] = {
    "disk": DiskSnapshotStrategy,
    "mariadb": MariadbBackupStrategy,
    "mongodb": MongodbBackupStrategy,
    "postgres": PostgresBackupStrategy,
    "neo4j": Neo4jBackupStrategy,
    "action": ActionBackupStrategy,
}


def get_strategy(kind: str) -> BackupStrategy:
    """Get the backup strategy for a given backup kind."""
    strategy_cls = STRATEGY_MAP.get(kind)
    if strategy_cls is None:
        raise ValueError(f"Unknown backup kind: {kind}")
    return strategy_cls()


async def create_backup(
    instance_id: UUID,
    uow: UnitOfWork,
    name: str | None = None,
    velero_namespace: str = "styrmin",
    target_namespace: str = "",
    component_configs: dict[str, dict[str, Any]] | None = None,
    timeout: int = DEFAULT_BACKUP_TIMEOUT,
) -> Backup:
    """Create a new on-demand backup for an application instance."""
    async with uow:
        existing = await uow.backups.has_in_progress_backup(instance_id)
        if existing:
            raise BackupAlreadyInProgressError(
                existing_backup_id=str(existing.id),
            )

        hooks: list[VeleroBackupHook] = []
        component_statuses: dict[str, dict[str, str]] = {}

        if component_configs:
            for comp_name, comp_config in component_configs.items():
                kind = comp_config.get("kind", "disk")
                strategy = get_strategy(kind)
                comp_hooks = strategy.get_hooks(
                    namespace=target_namespace,
                    component_name=comp_name,
                    config=comp_config,
                )
                hooks.extend(comp_hooks)
                component_statuses[comp_name] = {"status": "pending", **comp_config}

        metadata = {"timeout": timeout}

        backup = Backup(
            name=name or "placeholder",
            status=BackupStatus.PENDING,
            instance_id=instance_id,
            component_statuses=component_statuses or None,
            metadata_=metadata,
        )

        backup = await uow.backups.create(backup)

        if name is None:
            backup.name = f"styrmin-{backup.id}"

        await uow.commit()
        await uow.session.refresh(backup)  # Load server-generated fields

        logger.info(
            f"Created backup {backup.id} ({backup.name}) for instance {instance_id}"
        )
        return backup


async def get_backup(backup_id: UUID, uow: UnitOfWork) -> Backup:
    """Get a backup by ID."""
    async with uow:
        backup = await uow.backups.get(backup_id)
        if backup is None:
            raise BackupNotFoundError(f"Backup {backup_id} not found")
        return backup


async def get_backups(
    instance_id: UUID,
    uow: UnitOfWork,
    status: BackupStatus | None = None,
) -> Sequence[Backup]:
    """Get all backups for an instance."""
    async with uow:
        return await uow.backups.get_by_instance_id(instance_id, status=status)


async def delete_backup(backup_id: UUID, uow: UnitOfWork) -> None:
    """Delete a backup and associated data."""
    async with uow:
        backup = await uow.backups.get(backup_id)
        if backup is None:
            raise BackupNotFoundError(f"Backup {backup_id} not found")

        restores = await uow.restores.get_by_backup_id(backup_id)
        for restore in restores:
            await uow.restores.delete(restore)

        await uow.backups.delete(backup)
        await uow.commit()

        logger.info(f"Deleted backup {backup_id} ({backup.name})")


async def update_backup_status(
    backup_id: UUID,
    status: BackupStatus,
    uow: UnitOfWork,
    error_message: str | None = None,
    size_bytes: int | None = None,
    component_statuses: dict | None = None,
) -> Backup:
    """Update backup status after Velero operation completes."""
    async with uow:
        backup = await uow.backups.get(backup_id)
        if backup is None:
            raise BackupNotFoundError(f"Backup {backup_id} not found")

        backup.status = status

        if status == BackupStatus.IN_PROGRESS and backup.started_at is None:
            backup.started_at = datetime.now(timezone.utc)

        if status in (BackupStatus.COMPLETED, BackupStatus.FAILED):
            backup.completed_at = datetime.now(timezone.utc)

        if error_message is not None:
            backup.error_message = error_message
        if size_bytes is not None:
            backup.size_bytes = size_bytes
        if component_statuses is not None:
            backup.component_statuses = component_statuses

        await uow.commit()
        await uow.session.refresh(backup)  # Load server-generated fields
        return backup


async def update_backup_component_status(
    backup_id: UUID,
    component_name: str,
    component_status: str,
    uow: UnitOfWork,
    error_message: str | None = None,
) -> Backup:
    """Update the status of a single component within a backup.

    If any component has failed, the overall backup is marked as FAILED.
    If all components are completed, the overall backup is marked as COMPLETED.
    """
    async with uow:
        backup = await uow.backups.get(backup_id)
        if backup is None:
            raise BackupNotFoundError(f"Backup {backup_id} not found")

        statuses = dict(backup.component_statuses or {})
        entry: dict[str, str] = {"status": component_status}
        if error_message is not None:
            entry["error"] = error_message
        statuses[component_name] = entry
        backup.component_statuses = statuses

        # Derive overall status from component statuses
        all_statuses = [
            s.get("status", "pending") if isinstance(s, dict) else "pending"
            for s in statuses.values()
        ]
        if any(s == "failed" for s in all_statuses):
            backup.status = BackupStatus.FAILED
            backup.completed_at = datetime.now(timezone.utc)
            failed_components = [
                name
                for name, s in statuses.items()
                if isinstance(s, dict) and s.get("status") == "failed"
            ]
            backup.error_message = (
                f"Partial failure: components {failed_components} failed"
            )
            logger.warning(
                f"Backup {backup_id} marked FAILED due to component failures: "
                f"{failed_components}"
            )
        elif all(s == "completed" for s in all_statuses):
            backup.status = BackupStatus.COMPLETED
            backup.completed_at = datetime.now(timezone.utc)

        await uow.commit()
        await uow.session.refresh(backup)  # Load server-generated fields
        return backup


# ---------------------------------------------------------------------------
# Restore operations
# ---------------------------------------------------------------------------


async def create_restore(
    backup_id: UUID,
    target_namespace: str,
    uow: UnitOfWork,
    name: str | None = None,
    target_instance_id: UUID | None = None,
    timeout: int = DEFAULT_RESTORE_TIMEOUT,
) -> tuple[Restore, UUID]:
    """Create a new restore operation from a backup.

    Resolves the target deployment from the backup, blocks restoring an
    internal deployment, blocks a second concurrent restore on the same
    deployment, and flips the deployment to RESTORING in the same
    transaction so the UI reflects the lifecycle immediately.

    Returns:
        Tuple of ``(restore_record, deployment_id)``. The deployment id
        is returned so the caller can dispatch the restore workflow
        without re-resolving it.
    """
    async with uow:
        backup = await uow.backups.get(backup_id)
        if backup is None:
            raise BackupNotFoundError(f"Backup {backup_id} not found")

        # Resolve the target deployment via backup -> instance -> deployment.
        instance = await uow.application_instances.get(backup.instance_id)
        if instance is None or instance.deployment_id is None:
            raise BackupNotFoundError(
                f"Backup {backup_id} has no associated deployment"
            )
        deployment_id = instance.deployment_id

        deployment = await uow.deployments.find(deployment_id)
        if deployment is None:
            raise BackupNotFoundError(
                f"Backup {backup_id}: deployment {deployment_id} not found"
            )

        if deployment.internal:
            raise InternalDeploymentError(
                f"Cannot restore internal deployment {deployment_id}"
            )

        # Concurrency guard: block a second restore on the same deployment.
        if deployment.status == DeploymentState.RESTORING:
            existing = await uow.restores.get_by_target_namespace(
                target_namespace, status=RestoreStatus.IN_PROGRESS
            )
            existing_id = str(existing[0].id) if existing else "unknown"
            raise RestoreAlreadyInProgressError(existing_restore_id=existing_id)

        # Same-backup guard (preserved from prior behavior).
        existing_restores = await uow.restores.get_by_backup_id(
            backup_id, status=RestoreStatus.IN_PROGRESS
        )
        if existing_restores:
            raise RestoreAlreadyInProgressError(
                existing_restore_id=str(existing_restores[0].id),
            )

        restore = Restore(
            name=name or "placeholder",
            status=RestoreStatus.PENDING,
            target_namespace=target_namespace,
            backup_id=backup_id,
            target_instance_id=target_instance_id,
            metadata_={"timeout": timeout},
        )

        restore = await uow.restores.create(restore)

        if name is None:
            restore.name = f"styrmin-{restore.id}"

        # Flip the deployment into RESTORING so the UI/API reflect it
        # immediately. The CRD status patch happens in the restore workflow
        # (which has K8s access).
        deployment.status = DeploymentState.RESTORING
        await uow.deployments.save(deployment)

        await uow.commit()
        await uow.session.refresh(restore)  # Load server-generated fields

        logger.info(
            f"Created restore {restore.id} ({restore.name}) "
            f"from backup {backup_id} to namespace {target_namespace}"
        )
        return restore, deployment_id


async def get_restore(restore_id: UUID, uow: UnitOfWork) -> Restore:
    """Get a restore by ID."""
    async with uow:
        restore = await uow.restores.get(restore_id)
        if restore is None:
            raise RestoreNotFoundError(f"Restore {restore_id} not found")
        return restore


async def get_restores(
    backup_id: UUID,
    uow: UnitOfWork,
    status: RestoreStatus | None = None,
) -> Sequence[Restore]:
    """Get all restores for a backup."""
    async with uow:
        return await uow.restores.get_by_backup_id(backup_id, status=status)


async def update_restore_status(
    restore_id: UUID,
    status: RestoreStatus,
    uow: UnitOfWork,
    error_message: str | None = None,
    component_statuses: dict | None = None,
) -> Restore:
    """Update restore status after Velero operation completes."""
    async with uow:
        restore = await uow.restores.get(restore_id)
        if restore is None:
            raise RestoreNotFoundError(f"Restore {restore_id} not found")

        restore.status = status

        if status == RestoreStatus.IN_PROGRESS and restore.started_at is None:
            restore.started_at = datetime.now(timezone.utc)

        if status in (RestoreStatus.COMPLETED, RestoreStatus.FAILED):
            restore.completed_at = datetime.now(timezone.utc)

        if error_message is not None:
            restore.error_message = error_message
        if component_statuses is not None:
            restore.component_statuses = component_statuses

        await uow.commit()
        await uow.session.refresh(restore)  # Load server-generated fields
        return restore


async def update_restore_component_status(
    restore_id: UUID,
    component_name: str,
    component_status: str,
    uow: UnitOfWork,
    error_message: str | None = None,
) -> Restore:
    """Update the status of a single component within a restore.

    If any component has failed, the overall restore is marked as FAILED.
    If all components are completed, the overall restore is marked as COMPLETED.
    """
    async with uow:
        restore = await uow.restores.get(restore_id)
        if restore is None:
            raise RestoreNotFoundError(f"Restore {restore_id} not found")

        statuses = dict(restore.component_statuses or {})
        entry: dict[str, str] = {"status": component_status}
        if error_message is not None:
            entry["error"] = error_message
        statuses[component_name] = entry
        restore.component_statuses = statuses

        # Derive overall status from component statuses
        all_statuses = [
            s.get("status", "pending") if isinstance(s, dict) else "pending"
            for s in statuses.values()
        ]
        if any(s == "failed" for s in all_statuses):
            restore.status = RestoreStatus.FAILED
            restore.completed_at = datetime.now(timezone.utc)
            failed_components = [
                name
                for name, s in statuses.items()
                if isinstance(s, dict) and s.get("status") == "failed"
            ]
            restore.error_message = (
                f"Partial failure: components {failed_components} failed"
            )
            logger.warning(
                f"Restore {restore_id} marked FAILED due to component failures: "
                f"{failed_components}"
            )
        elif all(s == "completed" for s in all_statuses):
            restore.status = RestoreStatus.COMPLETED
            restore.completed_at = datetime.now(timezone.utc)

        await uow.commit()
        await uow.session.refresh(restore)  # Load server-generated fields
        return restore
