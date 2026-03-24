"""Provides the backup storage location services."""

from __future__ import annotations

from typing import Sequence
from uuid import UUID

from styrmin_backend.db.models import BackupStorageLocation
from styrmin_backend.services.exceptions import (
    BackupStorageLocationAlreadyExistsError,
    BackupStorageLocationInUseError,
    BackupStorageLocationNotFoundError,
)
from styrmin_backend.services.unit_of_work import UnitOfWork


async def create_backup_storage_location(
    name: str,
    endpoint: str,
    bucket: str,
    region: str,
    access_key_id: str,
    secret_access_key: str,
    uow: UnitOfWork,
) -> BackupStorageLocation:
    """Create a backup storage location with the given parameters."""
    async with uow:
        existing = await uow.backup_storage_locations.get_by_name(name)
        if existing:
            raise BackupStorageLocationAlreadyExistsError(
                f"A backup storage location with name '{name}' already exists."
            )

        await uow.backup_storage_locations.create(
            BackupStorageLocation(
                name=name,
                endpoint=endpoint,
                bucket=bucket,
                region=region,
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
            )
        )
        await uow.commit()
        created = await uow.backup_storage_locations.get_by_name(name)
        assert created is not None, "BSL should be created successfully"
        return created


async def get_backup_storage_locations(
    uow: UnitOfWork,
) -> Sequence[BackupStorageLocation]:
    """Get all backup storage locations."""
    async with uow:
        return await uow.backup_storage_locations.get_all()


async def get_backup_storage_location(
    backup_storage_location_id: UUID, uow: UnitOfWork
) -> BackupStorageLocation:
    """Get a backup storage location by its id."""
    async with uow:
        bsl = await uow.backup_storage_locations.get(backup_storage_location_id)
        if bsl is None:
            raise BackupStorageLocationNotFoundError(
                f"Backup storage location with id {backup_storage_location_id} not found."
            )
        return bsl


async def update_backup_storage_location(
    backup_storage_location_id: UUID,
    uow: UnitOfWork,
    name: str | None = None,
    endpoint: str | None = None,
    bucket: str | None = None,
    region: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
) -> BackupStorageLocation:
    """Update a backup storage location. Only provided fields are updated."""
    async with uow:
        bsl = await uow.backup_storage_locations.get(backup_storage_location_id)
        if bsl is None:
            raise BackupStorageLocationNotFoundError(
                f"Backup storage location with id {backup_storage_location_id} not found."
            )

        if name is not None:
            bsl.name = name
        if endpoint is not None:
            bsl.endpoint = endpoint
        if bucket is not None:
            bsl.bucket = bucket
        if region is not None:
            bsl.region = region
        if access_key_id is not None:
            bsl.access_key_id = access_key_id
        if secret_access_key is not None:
            bsl.secret_access_key = secret_access_key

        await uow.commit()
        updated = await uow.backup_storage_locations.get(backup_storage_location_id)
        assert updated is not None
        return updated


async def delete_backup_storage_location(
    backup_storage_location_id: UUID, uow: UnitOfWork
) -> None:
    """Delete a backup storage location. Raises if in use by environments."""
    async with uow:
        bsl = await uow.backup_storage_locations.get(backup_storage_location_id)
        if bsl is None:
            raise BackupStorageLocationNotFoundError(
                f"Backup storage location with id {backup_storage_location_id} not found."
            )

        if bsl.environments:
            env_names = [env.name for env in bsl.environments]
            raise BackupStorageLocationInUseError(environment_names=env_names)

        await uow.backup_storage_locations.delete(bsl)
        await uow.commit()


async def assign_backup_storage_location(
    environment_id: UUID,
    backup_storage_location_id: UUID,
    uow: UnitOfWork,
) -> None:
    """Assign a backup storage location to an environment."""
    async with uow:
        bsl = await uow.backup_storage_locations.get(backup_storage_location_id)
        if bsl is None:
            raise BackupStorageLocationNotFoundError(
                f"Backup storage location with id {backup_storage_location_id} not found."
            )

        from styrmin_backend.services.exceptions import EnvironmentNotFoundError

        environment = await uow.environments.get(environment_id)
        if environment is None:
            raise EnvironmentNotFoundError(
                f"Environment with id {environment_id} not found."
            )

        environment.backup_storage_location_id = backup_storage_location_id
        await uow.commit()


async def unassign_backup_storage_location(
    environment_id: UUID, uow: UnitOfWork
) -> None:
    """Remove the backup storage location assignment from an environment."""
    async with uow:
        from styrmin_backend.services.exceptions import EnvironmentNotFoundError

        environment = await uow.environments.get(environment_id)
        if environment is None:
            raise EnvironmentNotFoundError(
                f"Environment with id {environment_id} not found."
            )

        environment.backup_storage_location_id = None
        await uow.commit()
