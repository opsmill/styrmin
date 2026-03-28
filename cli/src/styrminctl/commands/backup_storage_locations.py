"""Backup storage location management commands."""

from __future__ import annotations

from typing import Annotated

from cyclopts import App, Parameter

from styrminctl import client
from styrminctl.output import console, print_success, print_table, styrmin_error_handler
from styrminctl.types import BslId, EnvironmentId

backup_storage_locations_app = App(name="backup-locations", help="Manage backup storage locations.")


@backup_storage_locations_app.command
async def create(
    name: Annotated[str, Parameter(help="Name of the backup storage location.")],
    *,
    endpoint: Annotated[str, Parameter(help="S3-compatible endpoint URL.")],
    bucket: Annotated[str, Parameter(help="S3 bucket name.")],
    region: Annotated[str, Parameter(help="S3 region.")],
    access_key_id: Annotated[str, Parameter(help="S3 access key ID.")],
    secret_access_key: Annotated[str, Parameter(help="S3 secret access key.")],
) -> None:
    """Create a new backup storage location."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            bsl = await sdk.backup_storage_locations.create(
                name=name,
                endpoint=endpoint,
                bucket=bucket,
                region=region,
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
            )

    print_success(f"Backup storage location '{bsl.name}' created (id: {bsl.id})")


@backup_storage_locations_app.command(name="list")
async def list_bsls() -> None:
    """List all backup storage locations."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            bsls = await sdk.backup_storage_locations.list()

    if not bsls:
        console.print("No backup storage locations found.")
        return

    rows = [
        {
            "id": str(b.id),
            "name": b.name,
            "endpoint": b.endpoint,
            "bucket": b.bucket,
            "region": b.region,
            "environments": str(b.environment_count),
        }
        for b in bsls
    ]
    print_table(
        rows, columns=["id", "name", "endpoint", "bucket", "region", "environments"], title="Backup Storage Locations"
    )


@backup_storage_locations_app.command
async def get(bsl_id: BslId) -> None:
    """Get a backup storage location by ID."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            bsl = await sdk.backup_storage_locations.get(bsl_id)

    row = {
        "id": str(bsl.id),
        "name": bsl.name,
        "endpoint": bsl.endpoint,
        "bucket": bsl.bucket,
        "region": bsl.region,
        "environments": str(bsl.environment_count),
    }
    print_table(
        [row], columns=["id", "name", "endpoint", "bucket", "region", "environments"], title="Backup Storage Location"
    )


@backup_storage_locations_app.command
async def delete(bsl_id: BslId) -> None:
    """Delete a backup storage location."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            await sdk.backup_storage_locations.delete(bsl_id)

    print_success("Backup storage location deleted.")


@backup_storage_locations_app.command
async def assign(environment_id: EnvironmentId, bsl_id: BslId) -> None:
    """Assign a backup storage location to an environment."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            await sdk.backup_storage_locations.assign(environment_id, bsl_id)

    print_success("Backup storage location assigned to environment.")


@backup_storage_locations_app.command
async def unassign(environment_id: EnvironmentId) -> None:
    """Remove the backup storage location assignment from an environment."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            await sdk.backup_storage_locations.unassign(environment_id)

    print_success("Backup storage location unassigned from environment.")
