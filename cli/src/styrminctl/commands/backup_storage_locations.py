"""Backup storage location management commands."""

from __future__ import annotations

import typer
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import StyrminError

from styrminctl.async_typer import AsyncTyper as Typer
from styrminctl.config import SETTINGS
from styrminctl.output import console, print_error, print_success, print_table

app = Typer()


def _get_client() -> StyrminClient:
    return StyrminClient(
        server_address=SETTINGS.server_address,
        timeout=SETTINGS.timeout,
        headers=SETTINGS.additional_headers,
    )


@app.command()
async def create(  # noqa: PLR0917
    name: str = typer.Argument(..., help="Name of the backup storage location"),
    endpoint: str = typer.Option(..., "--endpoint", "-e", help="S3-compatible endpoint URL"),
    bucket: str = typer.Option(..., "--bucket", "-b", help="S3 bucket name"),
    region: str = typer.Option(..., "--region", "-r", help="S3 region"),
    access_key_id: str = typer.Option(..., "--access-key-id", help="S3 access key ID"),
    secret_access_key: str = typer.Option(..., "--secret-access-key", help="S3 secret access key"),
) -> None:
    """Create a new backup storage location."""
    async with _get_client() as client:
        try:
            bsl = await client.backup_storage_locations.create(
                name=name,
                endpoint=endpoint,
                bucket=bucket,
                region=region,
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
            )
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    print_success(f"Backup storage location '{bsl.name}' created (id: {bsl.id})")


@app.command(name="list")
async def list_bsls() -> None:
    """List all backup storage locations."""
    async with _get_client() as client:
        try:
            bsls = await client.backup_storage_locations.list()
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

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


@app.command()
async def get(
    bsl_id: str = typer.Argument(..., help="UUID of the backup storage location"),
) -> None:
    """Get a backup storage location by ID."""
    async with _get_client() as client:
        try:
            bsl = await client.backup_storage_locations.get(bsl_id)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

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


@app.command()
async def delete(
    bsl_id: str = typer.Argument(..., help="UUID of the backup storage location to delete"),
) -> None:
    """Delete a backup storage location."""
    async with _get_client() as client:
        try:
            await client.backup_storage_locations.delete(bsl_id)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    print_success("Backup storage location deleted.")


@app.command()
async def assign(
    environment_id: str = typer.Argument(..., help="UUID of the environment"),
    bsl_id: str = typer.Argument(..., help="UUID of the backup storage location"),
) -> None:
    """Assign a backup storage location to an environment."""
    async with _get_client() as client:
        try:
            await client.backup_storage_locations.assign(environment_id, bsl_id)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    print_success("Backup storage location assigned to environment.")


@app.command()
async def unassign(
    environment_id: str = typer.Argument(..., help="UUID of the environment"),
) -> None:
    """Remove the backup storage location assignment from an environment."""
    async with _get_client() as client:
        try:
            await client.backup_storage_locations.unassign(environment_id)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    print_success("Backup storage location unassigned from environment.")
