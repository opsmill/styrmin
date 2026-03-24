from __future__ import annotations

from typing import TYPE_CHECKING, Sequence
from uuid import UUID

from loguru import logger

from styrmin_backend.db.models import BackupSchedule
from styrmin_backend.services.exceptions import (
    BackupScheduleAlreadyExistsError,
    BackupScheduleNotFoundError,
)

if TYPE_CHECKING:
    from styrmin_backend.services.unit_of_work import UnitOfWork


async def create_backup_schedule(
    deployment_id: UUID,
    name: str,
    cron_expression: str,
    uow: UnitOfWork,
    retention_count: int = 10,
    enabled: bool = True,
) -> BackupSchedule:
    """Create a new backup schedule for a deployment.

    Raises BackupScheduleAlreadyExistsError if a schedule already exists
    for the given deployment.
    """
    async with uow:
        existing = await uow.backup_schedules.get_by_deployment_id(deployment_id)
        if existing:
            raise BackupScheduleAlreadyExistsError(
                existing_schedule_id=str(existing[0].id),
            )

        schedule = BackupSchedule(
            name=name,
            cron_expression=cron_expression,
            retention_count=retention_count,
            enabled=enabled,
            deployment_id=deployment_id,
        )

        schedule = await uow.backup_schedules.create(schedule)
        await uow.commit()
        await uow.session.refresh(schedule)  # Load server-generated fields

        logger.info(
            f"Created backup schedule {schedule.id} ({schedule.name}) "
            f"for deployment {deployment_id}"
        )
        return schedule


async def get_backup_schedule(
    schedule_id: UUID,
    uow: UnitOfWork,
) -> BackupSchedule:
    """Get a backup schedule by ID."""
    async with uow:
        schedule = await uow.backup_schedules.get(schedule_id)
        if schedule is None:
            raise BackupScheduleNotFoundError(
                f"Backup schedule {schedule_id} not found"
            )
        return schedule


async def get_backup_schedules(
    deployment_id: UUID,
    uow: UnitOfWork,
) -> Sequence[BackupSchedule]:
    """Get all backup schedules for a deployment."""
    async with uow:
        return await uow.backup_schedules.get_by_deployment_id(deployment_id)


async def update_backup_schedule(
    schedule_id: UUID,
    uow: UnitOfWork,
    name: str | None = None,
    cron_expression: str | None = None,
    retention_count: int | None = None,
    enabled: bool | None = None,
) -> BackupSchedule:
    """Update a backup schedule's fields.

    Only provided (non-None) fields are updated.
    """
    async with uow:
        schedule = await uow.backup_schedules.get(schedule_id)
        if schedule is None:
            raise BackupScheduleNotFoundError(
                f"Backup schedule {schedule_id} not found"
            )

        if name is not None:
            schedule.name = name
        if cron_expression is not None:
            schedule.cron_expression = cron_expression
        if retention_count is not None:
            schedule.retention_count = retention_count
        if enabled is not None:
            schedule.enabled = enabled

        await uow.commit()
        await uow.session.refresh(schedule)  # Load server-generated fields

        logger.info(f"Updated backup schedule {schedule_id} ({schedule.name})")
        return schedule


async def delete_backup_schedule(
    schedule_id: UUID,
    uow: UnitOfWork,
) -> None:
    """Delete a backup schedule."""
    async with uow:
        schedule = await uow.backup_schedules.get(schedule_id)
        if schedule is None:
            raise BackupScheduleNotFoundError(
                f"Backup schedule {schedule_id} not found"
            )

        await uow.backup_schedules.delete(schedule)
        await uow.commit()

        logger.info(f"Deleted backup schedule {schedule_id} ({schedule.name})")
