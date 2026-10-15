"""Provides the backup storage location services."""

from __future__ import annotations

from typing import Sequence
from uuid import UUID

from fast_depends import Depends, inject

from styrmin_backend.db.models import BackupStorageLocation
from styrmin_backend.services.capabilities import compute_environment_capabilities
from styrmin_backend.services.exceptions import (
    BackupStorageLocationAlreadyExistsError,
    BackupStorageLocationCleanupError,
    BackupStorageLocationInUseError,
    BackupStorageLocationNotFoundError,
    EnvironmentNotFoundError,
)
from styrmin_backend.services.unit_of_work import UnitOfWork
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.manager import PrefectManager
from styrmin_backend.workflows.models import PrefectAction

# Namespace of the Velero object and credentials Secret that Styrmin creates
# for a backup storage location.
BSL_CLUSTER_NAMESPACE = "styrmin"


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

        bsl = await uow.backup_storage_locations.create(
            BackupStorageLocation(
                name=name,
                endpoint=endpoint,
                bucket=bucket,
                region=region,
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
            )
        )
        # Read back by id: the name can change once the location is committed (#510).
        backup_storage_location_id = bsl.id
        await uow.commit()
        created = await uow.backup_storage_locations.get(backup_storage_location_id)
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

        name_changed = name is not None and name != bsl.name

        if name_changed:
            existing = await uow.backup_storage_locations.get_by_name(name)
            if existing is not None:
                raise BackupStorageLocationAlreadyExistsError(
                    f"A backup storage location with name '{name}' already exists."
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


@inject(cast_result=False)  # type: ignore[arg-type]
async def request_bsl_cluster_cleanup(
    bsl_id: UUID,
    prefect_manager: PrefectManager = Depends(get_manager),
) -> None:
    """Submit the workflow that removes a location's objects from the cluster.

    The workflow deletes the Velero ``BackupStorageLocation``
    (``styrmin-bsl-<name>``) and its credentials Secret. It is submitted and
    not awaited to completion: a run that fails inside the cluster is visible
    in the workflow service, not here.

    Raises:
        Exception: Whatever the workflow manager raises when the submission
            fails. Callers decide whether that blocks their operation.
    """
    await prefect_manager.run_action(
        action=PrefectAction.SYNC_BSL_DELETE,
        parameters={"bsl_id": str(bsl_id), "namespace": BSL_CLUSTER_NAMESPACE},
    )


async def get_bsl_id_to_remove_from_cluster(
    environment_id: UUID, uow: UnitOfWork
) -> UUID | None:
    """Id of the location to remove from the cluster once an environment stops using it.

    Returns ``None`` when the environment has no location, or when another
    environment of the same cluster still uses it. Call it *before* the
    environment's assignment or row changes, because it reads the current
    assignment.
    """
    async with uow:
        environment = await uow.environments.get(environment_id)
        if environment is None or environment.backup_storage_location_id is None:
            return None
        bsl = await uow.backup_storage_locations.get(
            environment.backup_storage_location_id
        )
        if bsl is None:
            return None
        other_environments_on_cluster = [
            other
            for other in bsl.environments
            if other.cluster_id == environment.cluster_id and other.id != environment_id
        ]
        if other_environments_on_cluster:
            return None
        return bsl.id


async def delete_backup_storage_location(
    backup_storage_location_id: UUID, uow: UnitOfWork
) -> None:
    """Delete a backup storage location and remove it from the cluster.

    Raises:
        BackupStorageLocationNotFoundError: The location does not exist.
        BackupStorageLocationInUseError: Environments still use the location.
        BackupStorageLocationCleanupError: The cluster cleanup could not be
            submitted. The location is kept, because once its row is gone
            nothing records that the cluster objects exist.
    """
    async with uow:
        bsl = await uow.backup_storage_locations.get(backup_storage_location_id)
        if bsl is None:
            raise BackupStorageLocationNotFoundError(
                f"Backup storage location with id {backup_storage_location_id} not found."
            )

        if bsl.environments:
            env_names = [env.name for env in bsl.environments]
            raise BackupStorageLocationInUseError(environment_names=env_names)

        try:
            await request_bsl_cluster_cleanup(bsl.id)
        except Exception as exc:
            raise BackupStorageLocationCleanupError(bsl.name) from exc

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

        environment = await uow.environments.get(environment_id)
        if environment is None:
            raise EnvironmentNotFoundError(
                f"Environment with id {environment_id} not found."
            )

        environment.backup_storage_location_id = backup_storage_location_id
        environment.backup_storage_location = bsl
        environment.capabilities = compute_environment_capabilities(environment)
        await uow.commit()


async def unassign_backup_storage_location(
    environment_id: UUID, uow: UnitOfWork
) -> None:
    """Remove the backup storage location assignment from an environment."""
    async with uow:
        environment = await uow.environments.get(environment_id)
        if environment is None:
            raise EnvironmentNotFoundError(
                f"Environment with id {environment_id} not found."
            )

        environment.backup_storage_location_id = None
        environment.backup_storage_location = None
        environment.capabilities = compute_environment_capabilities(environment)
        await uow.commit()
