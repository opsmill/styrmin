"""Environment backup and restore management commands."""

from __future__ import annotations

from typing import Annotated

from cyclopts import App, Parameter

from styrminctl import client
from styrminctl.output import console, print_error, print_success, print_table, styrmin_error_handler
from styrminctl.types import EnvironmentId, MaxWait, PollInterval

env_backups_app = App(name="env-backups", help="Manage environment-level backups and restores.")

EnvironmentBackupId = Annotated[str, Parameter(help="UUID of the environment backup.")]


@env_backups_app.command
async def create(
    environment_id: EnvironmentId,
    *,
    name: Annotated[str | None, Parameter(help="Optional backup name.")] = None,
    max_concurrency: Annotated[int | None, Parameter(help="Max concurrent constituent backups.")] = None,
    backup_timeout: Annotated[int | None, Parameter(name="--timeout", help="Overall timeout in seconds.")] = None,
    wait: Annotated[bool, Parameter(help="Wait for backup to complete.")] = False,
    max_wait: MaxWait = 600,
    interval: PollInterval = 10,
) -> None:
    """Create a coordinated backup of all active instances in an environment."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            env_backup = await sdk.environment_backups.create(
                environment_id=environment_id,
                name=name,
                max_concurrency=max_concurrency,
                backup_timeout=backup_timeout,
            )

            print_success(
                f"Environment backup '{env_backup.name}' created (id: {env_backup.id}, status: {env_backup.status})"
            )

            if wait:
                console.print("Waiting for environment backup to complete...")
                env_backup = await sdk.environment_backups.wait_for_completion(
                    env_backup.id, max_wait=max_wait, interval=interval
                )

                if env_backup.status == "completed":
                    print_success("Environment backup completed")
                elif env_backup.status == "partially_failed":
                    print_error(
                        f"Environment backup partially failed: {env_backup.error_message or 'some constituents failed'}"
                    )
                    raise SystemExit(1)
                else:
                    print_error(
                        f"Environment backup {env_backup.status}: {env_backup.error_message or 'unknown error'}"
                    )
                    raise SystemExit(1)


@env_backups_app.command
async def get(environment_backup_id: EnvironmentBackupId) -> None:
    """Get environment backup details."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            eb = await sdk.environment_backups.get(environment_backup_id)

        console.print(f"  ID: {eb.id}")
        console.print(f"  Name: {eb.name}")
        console.print(f"  Status: {eb.status}")
        console.print(f"  Backup Count: {eb.backup_count or ''}")
        console.print(f"  Completed: {eb.completed_count or ''}")
        console.print(f"  Failed: {eb.failed_count or ''}")
        console.print(f"  Started at: {eb.started_at or ''}")
        console.print(f"  Completed at: {eb.completed_at or ''}")
        if eb.error_message:
            console.print(f"  Error: {eb.error_message}")


@env_backups_app.command(name="list")
async def list_env_backups(
    environment_id: EnvironmentId,
    *,
    status: Annotated[str | None, Parameter(help="Filter by status.")] = None,
) -> None:
    """List environment backups for an environment."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            backups = await sdk.environment_backups.list(environment_id=environment_id, status=status)

    if not backups:
        console.print("No environment backups found.")
        return

    rows = [
        {
            "id": str(b.id),
            "name": b.name,
            "status": b.status,
            "backups": str(b.backup_count or ""),
            "completed": str(b.completed_count or ""),
            "failed": str(b.failed_count or ""),
            "created": str(b.created_on or ""),
        }
        for b in backups
    ]
    print_table(
        rows,
        columns=["id", "name", "status", "backups", "completed", "failed", "created"],
        title="Environment Backups",
    )


@env_backups_app.command
async def delete(environment_backup_id: EnvironmentBackupId) -> None:
    """Delete an environment backup and all associated data."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            await sdk.environment_backups.delete(environment_backup_id)

    print_success(f"Environment backup '{environment_backup_id}' deleted")


@env_backups_app.command
async def restore(
    environment_backup_id: EnvironmentBackupId,
    *,
    wait: Annotated[bool, Parameter(help="Wait for restore to complete.")] = False,
    max_wait: MaxWait = 600,
    interval: PollInterval = 10,
) -> None:
    """Restore an environment from an environment backup."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            env_restore = await sdk.environment_restores.create(
                environment_backup_id=environment_backup_id,
            )

            print_success(
                f"Environment restore '{env_restore.name}' created (id: {env_restore.id}, status: {env_restore.status})"
            )

            if wait:
                console.print("Waiting for environment restore to complete...")
                env_restore = await sdk.environment_restores.wait_for_completion(
                    env_restore.id, max_wait=max_wait, interval=interval
                )

                if env_restore.status == "completed":
                    print_success("Environment restore completed")
                elif env_restore.status == "partially_failed":
                    print_error(
                        f"Environment restore partially failed: "
                        f"{env_restore.error_message or 'some constituents failed'}"
                    )
                    raise SystemExit(1)
                else:
                    print_error(
                        f"Environment restore {env_restore.status}: {env_restore.error_message or 'unknown error'}"
                    )
                    raise SystemExit(1)


@env_backups_app.command(name="restore-get")
async def restore_get(
    environment_restore_id: Annotated[str, Parameter(help="UUID of the environment restore.")],
) -> None:
    """Get environment restore operation details."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            er = await sdk.environment_restores.get(environment_restore_id)

        console.print(f"  ID: {er.id}")
        console.print(f"  Name: {er.name}")
        console.print(f"  Status: {er.status}")
        console.print(f"  Restore Count: {er.restore_count or ''}")
        console.print(f"  Completed: {er.completed_count or ''}")
        console.print(f"  Failed: {er.failed_count or ''}")
        console.print(f"  Started at: {er.started_at or ''}")
        console.print(f"  Completed at: {er.completed_at or ''}")
        if er.error_message:
            console.print(f"  Error: {er.error_message}")


@env_backups_app.command(name="restore-list")
async def restore_list(
    environment_backup_id: EnvironmentBackupId,
    *,
    status: Annotated[str | None, Parameter(help="Filter by status.")] = None,
) -> None:
    """List environment restore operations for an environment backup."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            restores = await sdk.environment_restores.list(environment_backup_id=environment_backup_id, status=status)

    if not restores:
        console.print("No environment restores found.")
        return

    rows = [
        {
            "id": str(r.id),
            "name": r.name,
            "status": r.status,
            "restores": str(r.restore_count or ""),
            "completed": str(r.completed_count or ""),
            "failed": str(r.failed_count or ""),
            "created": str(r.created_on or ""),
        }
        for r in restores
    ]
    print_table(
        rows,
        columns=["id", "name", "status", "restores", "completed", "failed", "created"],
        title="Environment Restores",
    )
