"""Prefect workflow templates for environment-level backup and restore operations.

INTERNAL flows (styrmin-work-pool): Orchestrate constituent backup/restore
operations with configurable concurrency limiting.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from prefect import flow
from prefect.logging import get_run_logger

from styrmin_backend import config
from styrmin_backend.db.models import (
    BackupStatus,
    EnvironmentBackupStatus,
    EnvironmentRestoreStatus,
    RestoreStatus,
)
from styrmin_backend.services.backup.environment import (
    update_environment_backup_status,
    update_environment_restore_status,
)
from styrmin_backend.services.backup.service import (
    update_backup_status,
    update_restore_status,
)
from styrmin_backend.services.unit_of_work import get_unit_of_work
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.models import PrefectAction


@flow(name="execute_env_backup")
async def execute_environment_backup_workflow(
    environment_backup_id: str,
) -> None:
    """Orchestrate concurrent constituent backups for an environment backup.

    Runs on styrmin-work-pool. Dispatches individual EXECUTE_BACKUP flows
    for each constituent backup with concurrency limiting via asyncio.Semaphore.
    """
    env_backup_uuid = UUID(environment_backup_id)

    config.SETTINGS.initialize_and_exit()
    logger = get_run_logger()

    try:
        # Mark environment backup as IN_PROGRESS
        uow = await get_unit_of_work()
        await update_environment_backup_status(
            environment_backup_id=env_backup_uuid,
            uow=uow,
            status=EnvironmentBackupStatus.IN_PROGRESS,
        )

        # Load environment backup and constituents
        uow = await get_unit_of_work()
        async with uow:
            env_backup = await uow.environment_backups.get(env_backup_uuid)
            if env_backup is None:
                raise RuntimeError(f"EnvironmentBackup {env_backup_uuid} not found")

            max_concurrency = env_backup.max_concurrency
            timeout = env_backup.timeout

            # Load constituent backups with their instances
            from sqlmodel import select
            from styrmin_backend.db.models import Backup

            result = await uow.session.exec(
                select(Backup).where(Backup.environment_backup_id == env_backup_uuid)
            )
            constituent_backups = list(result.all())

            # Resolve deployment IDs for each constituent
            backup_dispatch_info = []
            for backup in constituent_backups:
                instance = await uow.application_instances.get(backup.instance_id)
                deployment_id = instance.deployment_id if instance else None
                backup_dispatch_info.append(
                    (str(backup.id), str(deployment_id) if deployment_id else None)
                )

        if not backup_dispatch_info:
            raise RuntimeError("No constituent backups to execute")

        logger.info(
            f"Dispatching {len(backup_dispatch_info)} constituent backups "
            f"(max_concurrency={max_concurrency}, timeout={timeout}s)"
        )

        # Dispatch constituent backups with concurrency limiting
        semaphore = asyncio.Semaphore(max_concurrency)
        prefect_manager = get_manager()

        async def dispatch_backup(backup_id: str, deployment_id: str | None) -> None:
            if deployment_id is None:
                logger.warning(f"Skipping backup {backup_id}: no deployment ID")
                uow = await get_unit_of_work()
                await update_backup_status(
                    backup_id=UUID(backup_id),
                    status=BackupStatus.FAILED,
                    uow=uow,
                    error_message="No deployment ID available",
                )
                return

            async with semaphore:
                try:
                    await prefect_manager.run_action(
                        action=PrefectAction.EXECUTE_BACKUP,
                        parameters={
                            "backup_id": backup_id,
                            "deployment_id": deployment_id,
                        },
                        timeout=0,
                    )
                except Exception as exc:
                    logger.error(f"Failed to dispatch backup {backup_id}: {exc}")
                    uow = await get_unit_of_work()
                    await update_backup_status(
                        backup_id=UUID(backup_id),
                        status=BackupStatus.FAILED,
                        uow=uow,
                        error_message=f"Failed to dispatch: {exc}",
                    )

        # Dispatch all backups concurrently (bounded by semaphore)
        await asyncio.gather(
            *(dispatch_backup(bid, did) for bid, did in backup_dispatch_info)
        )

        # Poll until all constituents reach terminal status or timeout
        poll_interval = 10
        elapsed = 0
        while elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            uow = await get_unit_of_work()
            async with uow:
                from sqlmodel import select
                from styrmin_backend.db.models import Backup

                result = await uow.session.exec(
                    select(Backup).where(
                        Backup.environment_backup_id == env_backup_uuid
                    )
                )
                current_backups = list(result.all())
                statuses = [b.status for b in current_backups]

                all_terminal = all(
                    s in (BackupStatus.COMPLETED, BackupStatus.FAILED) for s in statuses
                )

                if all_terminal:
                    logger.info("All constituent backups reached terminal status")
                    break
        else:
            # Timeout reached — mark remaining as FAILED
            logger.warning(f"Environment backup timeout ({timeout}s) reached")
            uow = await get_unit_of_work()
            async with uow:
                from sqlmodel import select
                from styrmin_backend.db.models import Backup

                result = await uow.session.exec(
                    select(Backup).where(
                        Backup.environment_backup_id == env_backup_uuid,
                        Backup.status.in_(
                            [BackupStatus.PENDING, BackupStatus.IN_PROGRESS]
                        ),  # type: ignore[attr-defined]
                    )
                )
                for backup in result.all():
                    uow2 = await get_unit_of_work()
                    await update_backup_status(
                        backup_id=backup.id,
                        status=BackupStatus.FAILED,
                        uow=uow2,
                        error_message="Environment backup timeout exceeded",
                    )

        # Recompute and update parent status from constituent statuses
        uow = await get_unit_of_work()
        await update_environment_backup_status(
            environment_backup_id=env_backup_uuid,
            uow=uow,
        )

        logger.info(f"Environment backup {env_backup_uuid} orchestration complete")

    except Exception as exc:
        logger.error(f"Environment backup {env_backup_uuid} failed: {exc}")
        uow = await get_unit_of_work()
        await update_environment_backup_status(
            environment_backup_id=env_backup_uuid,
            uow=uow,
            status=EnvironmentBackupStatus.FAILED,
            error_message=str(exc),
        )
        raise


@flow(name="execute_env_restore")
async def execute_environment_restore_workflow(
    environment_restore_id: str,
) -> None:
    """Orchestrate concurrent constituent restores for an environment restore.

    Runs on styrmin-work-pool. Dispatches individual EXECUTE_RESTORE flows
    for each constituent restore with concurrency limiting.
    """
    env_restore_uuid = UUID(environment_restore_id)

    config.SETTINGS.initialize_and_exit()
    logger = get_run_logger()

    try:
        # Mark environment restore as IN_PROGRESS
        uow = await get_unit_of_work()
        await update_environment_restore_status(
            environment_restore_id=env_restore_uuid,
            uow=uow,
            status=EnvironmentRestoreStatus.IN_PROGRESS,
        )

        # Load environment restore and constituents
        uow = await get_unit_of_work()
        async with uow:
            env_restore = await uow.environment_restores.get(env_restore_uuid)
            if env_restore is None:
                raise RuntimeError(f"EnvironmentRestore {env_restore_uuid} not found")

            env_backup = await uow.environment_backups.get(
                env_restore.environment_backup_id
            )
            max_concurrency = env_backup.max_concurrency if env_backup else 5

            from sqlmodel import select
            from styrmin_backend.db.models import Restore

            result = await uow.session.exec(
                select(Restore).where(
                    Restore.environment_restore_id == env_restore_uuid
                )
            )
            constituent_restores = list(result.all())

            # Resolve dispatch info for each constituent restore
            restore_dispatch_info = []
            for restore in constituent_restores:
                backup = await uow.backups.get(restore.backup_id)
                if backup is None:
                    continue
                instance = await uow.application_instances.get(backup.instance_id)
                deployment_id = instance.deployment_id if instance else None
                restore_dispatch_info.append(
                    (
                        str(restore.id),
                        str(restore.backup_id),
                        str(deployment_id) if deployment_id else None,
                        restore.target_namespace,
                    )
                )

        if not restore_dispatch_info:
            raise RuntimeError("No constituent restores to execute")

        logger.info(
            f"Dispatching {len(restore_dispatch_info)} constituent restores "
            f"(max_concurrency={max_concurrency})"
        )

        # Dispatch constituent restores with concurrency limiting
        semaphore = asyncio.Semaphore(max_concurrency)
        prefect_manager = get_manager()

        async def dispatch_restore(
            restore_id: str,
            backup_id: str,
            deployment_id: str | None,
            target_namespace: str,
        ) -> None:
            if deployment_id is None:
                logger.warning(f"Skipping restore {restore_id}: no deployment ID")
                uow = await get_unit_of_work()
                await update_restore_status(
                    restore_id=UUID(restore_id),
                    status=RestoreStatus.FAILED,
                    uow=uow,
                    error_message="No deployment ID available",
                )
                return

            async with semaphore:
                try:
                    await prefect_manager.run_action(
                        action=PrefectAction.EXECUTE_RESTORE,
                        parameters={
                            "restore_id": restore_id,
                            "backup_id": backup_id,
                            "deployment_id": deployment_id,
                            "target_namespace": target_namespace,
                        },
                        timeout=0,
                    )
                except Exception as exc:
                    logger.error(f"Failed to dispatch restore {restore_id}: {exc}")
                    uow = await get_unit_of_work()
                    await update_restore_status(
                        restore_id=UUID(restore_id),
                        status=RestoreStatus.FAILED,
                        uow=uow,
                        error_message=f"Failed to dispatch: {exc}",
                    )

        # Dispatch all restores concurrently (bounded by semaphore)
        await asyncio.gather(
            *(
                dispatch_restore(rid, bid, did, tns)
                for rid, bid, did, tns in restore_dispatch_info
            )
        )

        # Poll until all constituents reach terminal status
        timeout = 7200
        poll_interval = 10
        elapsed = 0
        while elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            uow = await get_unit_of_work()
            async with uow:
                from sqlmodel import select
                from styrmin_backend.db.models import Restore

                result = await uow.session.exec(
                    select(Restore).where(
                        Restore.environment_restore_id == env_restore_uuid
                    )
                )
                current_restores = list(result.all())
                statuses = [r.status for r in current_restores]

                all_terminal = all(
                    s in (RestoreStatus.COMPLETED, RestoreStatus.FAILED)
                    for s in statuses
                )

                if all_terminal:
                    logger.info("All constituent restores reached terminal status")
                    break
        else:
            logger.warning(f"Environment restore timeout ({timeout}s) reached")
            uow = await get_unit_of_work()
            async with uow:
                from sqlmodel import select
                from styrmin_backend.db.models import Restore

                result = await uow.session.exec(
                    select(Restore).where(
                        Restore.environment_restore_id == env_restore_uuid,
                        Restore.status.in_(
                            [RestoreStatus.PENDING, RestoreStatus.IN_PROGRESS]
                        ),  # type: ignore[attr-defined]
                    )
                )
                for restore in result.all():
                    uow2 = await get_unit_of_work()
                    await update_restore_status(
                        restore_id=restore.id,
                        status=RestoreStatus.FAILED,
                        uow=uow2,
                        error_message="Environment restore timeout exceeded",
                    )

        # Recompute and update parent status
        uow = await get_unit_of_work()
        await update_environment_restore_status(
            environment_restore_id=env_restore_uuid,
            uow=uow,
        )

        logger.info(f"Environment restore {env_restore_uuid} orchestration complete")

    except Exception as exc:
        logger.error(f"Environment restore {env_restore_uuid} failed: {exc}")
        uow = await get_unit_of_work()
        await update_environment_restore_status(
            environment_restore_id=env_restore_uuid,
            uow=uow,
            status=EnvironmentRestoreStatus.FAILED,
            error_message=str(exc),
        )
        raise
