"""Backup and restore management commands."""

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
async def create(
    instance_id: str = typer.Argument(..., help="UUID of the application instance to back up"),
    name: str | None = typer.Option(None, "--name", "-n", help="Optional backup name"),
    wait: bool = typer.Option(False, "--wait", "-w", help="Wait for backup to complete"),
    max_wait: float = typer.Option(300, "--timeout", help="Max seconds to wait (with --wait)"),
    interval: float = typer.Option(5, "--interval", help="Poll interval in seconds (with --wait)"),
) -> None:
    """Create a backup of an application instance."""
    async with _get_client() as client:
        try:
            backup = await client.backups.create_backup(instance_id=instance_id, name=name)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

        print_success(f"Backup '{backup.name}' created (id: {backup.id}, status: {backup.status})")

        if wait:
            console.print("Waiting for backup to complete...")
            try:
                backup = await client.backups.wait_for_backup(backup.id, max_wait=max_wait, interval=interval)
            except StyrminError as e:
                print_error(str(e))
                raise typer.Exit(code=1) from e

            if backup.status == "completed":
                print_success(f"Backup completed (size: {backup.size_bytes or 'unknown'} bytes)")
            else:
                print_error(f"Backup {backup.status}: {backup.error_message or 'unknown error'}")
                raise typer.Exit(code=1)


@app.command()
async def get(
    backup_id: str = typer.Argument(..., help="UUID of the backup"),
) -> None:
    """Get backup details."""
    async with _get_client() as client:
        try:
            backup = await client.backups.get_backup(backup_id)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    console.print(f"  ID: {backup.id}")
    console.print(f"  Name: {backup.name}")
    console.print(f"  Status: {backup.status}")
    console.print(f"  Instance ID: {backup.instance_id}")
    console.print(f"  Started at: {backup.started_at or ''}")
    console.print(f"  Completed at: {backup.completed_at or ''}")
    console.print(f"  Size (bytes): {backup.size_bytes or ''}")
    if backup.error_message:
        console.print(f"  Error: {backup.error_message}")


@app.command(name="list")
async def list_backups(
    instance_id: str = typer.Argument(..., help="UUID of the application instance"),
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
) -> None:
    """List backups for an application instance."""
    async with _get_client() as client:
        try:
            backups = await client.backups.list_backups(instance_id=instance_id, status=status)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    if not backups:
        console.print("No backups found.")
        return

    rows = [
        {
            "id": str(b.id),
            "name": b.name,
            "status": b.status,
            "started_at": str(b.started_at or ""),
            "completed_at": str(b.completed_at or ""),
            "size_bytes": str(b.size_bytes or ""),
        }
        for b in backups
    ]
    print_table(rows, columns=["id", "name", "status", "started_at", "completed_at", "size_bytes"], title="Backups")


@app.command()
async def delete(
    backup_id: str = typer.Argument(..., help="UUID of the backup to delete"),
) -> None:
    """Delete a backup and all associated restores."""
    async with _get_client() as client:
        try:
            await client.backups.delete_backup(backup_id)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    print_success(f"Backup '{backup_id}' deleted")


@app.command()
async def restore(
    backup_id: str = typer.Argument(..., help="UUID of the backup to restore from"),
    *,
    target_namespace: str = typer.Option(..., "--target-namespace", "-t", help="Target Kubernetes namespace"),
    target_instance_id: str | None = typer.Option(
        None, "--target-instance-id", help="UUID of the target application instance"
    ),
    wait: bool = typer.Option(False, "--wait", "-w", help="Wait for restore to complete"),
    max_wait: float = typer.Option(300, "--timeout", help="Max seconds to wait (with --wait)"),
    interval: float = typer.Option(5, "--interval", help="Poll interval in seconds (with --wait)"),
) -> None:
    """Restore from a backup."""
    async with _get_client() as client:
        try:
            rst = await client.backups.create_restore(
                backup_id=backup_id,
                target_namespace=target_namespace,
                target_instance_id=target_instance_id,
            )
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

        print_success(f"Restore '{rst.name}' created (id: {rst.id}, status: {rst.status})")

        if wait:
            console.print("Waiting for restore to complete...")
            try:
                rst = await client.backups.wait_for_restore(rst.id, max_wait=max_wait, interval=interval)
            except StyrminError as e:
                print_error(str(e))
                raise typer.Exit(code=1) from e

            if rst.status == "completed":
                print_success("Restore completed")
            else:
                print_error(f"Restore {rst.status}: {rst.error_message or 'unknown error'}")
                raise typer.Exit(code=1)


@app.command(name="restore-get")
async def restore_get(
    restore_id: str = typer.Argument(..., help="UUID of the restore operation"),
) -> None:
    """Get restore operation details."""
    async with _get_client() as client:
        try:
            rst = await client.backups.get_restore(restore_id)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    console.print(f"  ID: {rst.id}")
    console.print(f"  Name: {rst.name}")
    console.print(f"  Status: {rst.status}")
    console.print(f"  Backup ID: {rst.backup_id}")
    console.print(f"  Target namespace: {rst.target_namespace}")
    console.print(f"  Target instance ID: {rst.target_instance_id or ''}")
    console.print(f"  Started at: {rst.started_at or ''}")
    console.print(f"  Completed at: {rst.completed_at or ''}")
    if rst.error_message:
        console.print(f"  Error: {rst.error_message}")


@app.command(name="restore-list")
async def restore_list(
    backup_id: str = typer.Argument(..., help="UUID of the backup"),
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
) -> None:
    """List restore operations for a backup."""
    async with _get_client() as client:
        try:
            restores = await client.backups.list_restores(backup_id=backup_id, status=status)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    if not restores:
        console.print("No restores found.")
        return

    rows = [
        {
            "id": str(r.id),
            "name": r.name,
            "status": r.status,
            "target_namespace": r.target_namespace,
            "started_at": str(r.started_at or ""),
            "completed_at": str(r.completed_at or ""),
        }
        for r in restores
    ]
    print_table(
        rows,
        columns=["id", "name", "status", "target_namespace", "started_at", "completed_at"],
        title="Restores",
    )
