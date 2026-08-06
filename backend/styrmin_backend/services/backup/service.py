from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, NamedTuple, Sequence
from uuid import UUID, uuid4

from loguru import logger

from styrmin_backend.agent.service.kubernetes.velero.resources import VeleroBackupHook
from styrmin_backend.db.models import (
    Backup,
    BackupStatus,
    DeploymentState,
    Restore,
    RestoreStatus,
)
from styrmin_backend.services.backup.metadata import BackupMetadata
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


class BackupTarget(NamedTuple):
    """The ``create_backup`` arguments derived from an application instance.

    ``deployment_id`` is what the caller needs to dispatch ``EXECUTE_BACKUP``;
    it is ``None`` when the instance could not be resolved at all.
    """

    deployment_id: UUID | None
    target_namespace: str
    component_configs: dict[str, dict[str, Any]] | None


async def resolve_backup_target(instance_id: UUID, uow: UnitOfWork) -> BackupTarget:
    """Resolve an instance's namespace and backup-enabled component configs.

    Walks instance → deployment (for the namespace) and instance → driver
    version → component configs, keeping only the components whose driver
    config declares ``backup.enabled``. Those become the Velero hooks
    ``create_backup`` installs.

    Resolution is best-effort by design: any failure degrades to a hookless
    backup rather than failing the request, because a backup without
    application-aware hooks is still a useful disk-level backup. The failure
    is logged at ``warning``.

    Shared by the ``createBackup`` mutation and the environment-level backup
    fan-out so both produce identical constituent backups (spec FR-014 —
    constituents behave as ordinary backups).
    """
    try:
        async with uow:
            instance = await uow.application_instances.get(instance_id)
            if instance is None:
                return BackupTarget(None, "", None)

            deployment_id = instance.deployment_id
            target_namespace = f"styrmin-{deployment_id}" if deployment_id else ""

            driver_version = await uow.application_driver_versions.get(
                instance.application_driver_version_id
            )
            component_configs: dict[str, dict[str, Any]] | None = None
            if driver_version and driver_version.component_configs:
                resolved: dict[str, dict[str, Any]] = {}
                for component_config in driver_version.component_configs:
                    backup_raw = component_config.config.get("backup")
                    if isinstance(backup_raw, dict) and backup_raw.get("enabled"):
                        resolved[component_config.name] = backup_raw
                if resolved:
                    component_configs = resolved

            return BackupTarget(deployment_id, target_namespace, component_configs)
    except Exception as exc:  # noqa: BLE001 — degrade to a hookless backup
        logger.warning(
            f"Failed to resolve component configs for instance {instance_id}, "
            "backup will be created without hooks",
            exc_info=exc,
        )
        return BackupTarget(None, "", None)


async def create_backup(
    instance_id: UUID,
    uow: UnitOfWork,
    name: str | None = None,
    velero_namespace: str = "styrmin",
    target_namespace: str = "",
    component_configs: dict[str, dict[str, Any]] | None = None,
    timeout: int = DEFAULT_BACKUP_TIMEOUT,
    environment_backup_id: UUID | None = None,
) -> Backup:
    """Create a new on-demand backup for an application instance.

    Args:
        environment_backup_id: Links the backup to an environment backup as
            one of its constituents. ``None`` (the default) for a standalone
            per-instance backup; the constituent's own lifecycle is otherwise
            identical (spec FR-014).
    """
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

        metadata: BackupMetadata = {"timeout": timeout}

        # The id is generated up front so the auto-generated name is final
        # *before* the INSERT: ``Backup.name`` is unique, and writing a shared
        # sentinel and renaming afterwards collides on that index as soon as two
        # rows are created inside one transaction (the environment fan-out).
        backup_id = uuid4()
        backup = Backup(
            id=backup_id,
            name=name or f"styrmin-{backup_id}",
            status=BackupStatus.PENDING,
            instance_id=instance_id,
            component_statuses=component_statuses or None,
            metadata_=metadata,
            environment_backup_id=environment_backup_id,
        )

        backup = await uow.backups.create(backup)

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
    metadata_updates: BackupMetadata | None = None,
) -> Backup:
    """Update backup status after Velero operation completes.

    Args:
        backup_id: The backup record to update.
        status: The status to move the backup to.
        uow: Unit of work supplying the session.
        error_message: Failure detail, when the backup failed.
        size_bytes: Reported backup size, when known.
        component_statuses: Replacement per-component status map.
        metadata_updates: Keys to merge into ``Backup.metadata_`` (e.g. the
            resolved retention ``ttl`` / ``ttl_source``, or ``expires_at``).
            Merged, so pre-existing keys such as ``timeout`` survive. Typed as
            :class:`~styrmin_backend.services.backup.metadata.BackupMetadata`
            rather than a bare ``dict`` so a key the readers do not look up —
            Velero's own ``expiration`` spelling being the live hazard — fails
            type checking here instead of persisting into a blob nothing reads.
    """
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
        if metadata_updates:
            # ``metadata`` is a plain JSON column with no ``MutableDict``
            # wrapper, so SQLAlchemy does not track in-place mutation of the
            # dict. Reassigning the attribute is what marks it dirty — an
            # ``update()``/``[k] = v`` here would be silently dropped on
            # commit. ``metadata_`` is None on pre-existing rows.
            backup.metadata_ = {**(backup.metadata_ or {}), **metadata_updates}

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
    environment_restore_id: UUID | None = None,
) -> tuple[Restore, UUID]:
    """Create a new restore operation from a backup.

    Resolves the target deployment from the backup, blocks restoring an
    internal deployment, blocks a second concurrent restore on the same
    deployment, and flips the deployment to RESTORING in the same
    transaction so the UI reflects the lifecycle immediately.

    Args:
        environment_restore_id: Links the restore to an environment restore
            as one of its constituents. ``None`` (the default) for a
            standalone per-deployment restore; the constituent's own
            lifecycle is otherwise identical (spec FR-014).

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

        # Same reasoning as ``create_backup``: the id is generated up front so
        # the auto-generated name is final before the INSERT rather than being
        # patched after it (``Restore.name`` is unique).
        restore_id = uuid4()
        restore = Restore(
            id=restore_id,
            name=name or f"styrmin-{restore_id}",
            status=RestoreStatus.PENDING,
            target_namespace=target_namespace,
            backup_id=backup_id,
            target_instance_id=target_instance_id,
            metadata_={"timeout": timeout},
            environment_restore_id=environment_restore_id,
        )

        restore = await uow.restores.create(restore)

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
