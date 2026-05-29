"""Backup and restore management commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from cyclopts import App, Parameter

from styrminctl import client
from styrminctl.output import console, print_error, print_success, print_table, styrmin_error_handler
from styrminctl.resolve import resolve_active_instance

if TYPE_CHECKING:
    from styrmin_sdk import StyrminClient
from styrminctl.types import (
    BackupId,
    DeploymentName,
    EnvironmentContextName,
    InstanceIdOption,
    MaxWait,
    OptionalDeploymentId,
    OptionalInstanceId,
    PollInterval,
    RestoreId,
    TargetDeploymentId,
    TargetDeploymentName,
    validate_uuid,
)

backups_app = App(name="backups", help="Manage backups and restores.")


@backups_app.command
async def create(
    deployment: DeploymentName = None,
    *,
    id: OptionalDeploymentId = None,
    environment: EnvironmentContextName = None,
    instance_id: InstanceIdOption = None,
    name: Annotated[str | None, Parameter(help="Optional backup name.")] = None,
    wait: Annotated[bool, Parameter(help="Wait for backup to complete.")] = False,
    max_wait: MaxWait = 300,
    interval: PollInterval = 5,
) -> None:
    """Create a backup of a deployment's active application instance.

    Target the deployment by name (optionally with --environment), by --id, or
    a specific instance with --instance-id.
    """
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            target = await resolve_active_instance(
                sdk,
                deployment_name=deployment,
                deployment_id=id,
                instance_id=instance_id,
                environment=environment,
            )
            backup = await sdk.backups.create_backup(instance_id=target.instance_id, name=name)

            print_success(f"Backup '{backup.name}' created (id: {backup.id}, status: {backup.status})")

            if wait:
                console.print("Waiting for backup to complete...")
                backup = await sdk.backups.wait_for_backup(backup.id, max_wait=max_wait, interval=interval)

                if backup.status == "completed":
                    print_success(f"Backup completed (size: {backup.size_bytes or 'unknown'} bytes)")
                else:
                    print_error(f"Backup {backup.status}: {backup.error_message or 'unknown error'}")
                    raise SystemExit(1)


@backups_app.command
async def get(backup_id: BackupId) -> None:
    """Get backup details."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            backup = await sdk.backups.get_backup(backup_id)

    console.print(f"  ID: {backup.id}")
    console.print(f"  Name: {backup.name}")
    console.print(f"  Status: {backup.status}")
    console.print(f"  Instance ID: {backup.instance_id}")
    console.print(f"  Started at: {backup.started_at or ''}")
    console.print(f"  Completed at: {backup.completed_at or ''}")
    console.print(f"  Size (bytes): {backup.size_bytes or ''}")
    if backup.error_message:
        console.print(f"  Error: {backup.error_message}")


@backups_app.command(name="list")
async def list_backups(
    deployment: DeploymentName = None,
    *,
    id: OptionalDeploymentId = None,
    environment: EnvironmentContextName = None,
    instance_id: InstanceIdOption = None,
    status: Annotated[str | None, Parameter(help="Filter by status.")] = None,
) -> None:
    """List backups for a deployment's active application instance.

    Target the deployment by name (optionally with --environment), by --id, or
    a specific instance with --instance-id.
    """
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            target = await resolve_active_instance(
                sdk,
                deployment_name=deployment,
                deployment_id=id,
                instance_id=instance_id,
                environment=environment,
            )
            backups = await sdk.backups.list_backups(instance_id=target.instance_id, status=status)

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


@backups_app.command
async def delete(backup_id: BackupId) -> None:
    """Delete a backup and all associated restores."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            await sdk.backups.delete_backup(backup_id)

    print_success(f"Backup '{backup_id}' deleted")


async def _prepare_restore(
    sdk: StyrminClient,
    *,
    backup_id: str | None,
    target_deployment: str | None,
    target_deployment_id: str | None,
    target_instance_id: str | None,
    environment: str | None,
    target_namespace: str | None,
    last: bool,
) -> tuple[str, str, str | None]:
    """Resolve the restore target, pick the backup for ``--last``, and derive the namespace.

    Returns ``(backup_id, target_namespace, target_instance_id)`` ready for
    ``create_restore``. Raises ``ValueError`` on any invalid combination.
    """
    target_selectors = [s for s in (target_deployment, target_deployment_id, target_instance_id) if s is not None]
    if len(target_selectors) > 1:
        raise ValueError("Provide only one of --target-deployment, --target-deployment-id, or --target-instance-id")

    target = None
    if target_selectors:
        target = await resolve_active_instance(
            sdk,
            deployment_name=target_deployment,
            deployment_id=target_deployment_id,
            instance_id=target_instance_id,
            environment=environment,
        )
    resolved_instance_id = target.instance_id if target else None

    if last:
        if resolved_instance_id is None:
            raise ValueError(
                "--last requires a target deployment (--target-deployment/--target-deployment-id) "
                "or --target-instance-id"
            )
        backups_list = await sdk.backups.list_backups(instance_id=resolved_instance_id, status="completed")
        if not backups_list:
            raise ValueError(f"No completed backups found for instance {resolved_instance_id}")
        backup_id = str(backups_list[0].id)
        console.print(f"Selected latest completed backup: {backup_id}")

    if backup_id is None:
        raise ValueError("backup_id is required (or use --last with a target deployment/instance)")

    if target_namespace is None:
        if target is not None and target.deployment_id is not None:
            target_namespace = f"styrmin-{target.deployment_id}"
        else:
            raise ValueError("--target-namespace is required when restoring to a raw --target-instance-id")

    return backup_id, target_namespace, resolved_instance_id


@backups_app.command
async def restore(
    backup_id: Annotated[
        str | None,
        Parameter(help="UUID of the backup to restore (omit when using --last).", validator=validate_uuid),
    ] = None,
    *,
    target_deployment: TargetDeploymentName = None,
    target_deployment_id: TargetDeploymentId = None,
    target_instance_id: OptionalInstanceId = None,
    environment: EnvironmentContextName = None,
    target_namespace: Annotated[
        str | None,
        Parameter(help="Target Kubernetes namespace (defaults to the target deployment's namespace)."),
    ] = None,
    last: Annotated[
        bool,
        Parameter(help="Restore the most recent completed backup of the target deployment/instance (in-place)."),
    ] = False,
    wait: Annotated[bool, Parameter(help="Wait for restore to complete.")] = False,
    max_wait: MaxWait = 300,
    interval: PollInterval = 5,
) -> None:
    """Restore from a backup.

    Target an in-place restore by deployment name (with --environment), by
    --target-deployment-id, or a specific instance with --target-instance-id.
    """
    with styrmin_error_handler():
        if last and backup_id is not None:
            raise ValueError("Provide either a backup_id or --last, not both")

        async with client.get_client() as sdk:
            backup_id, target_namespace, resolved_instance_id = await _prepare_restore(
                sdk,
                backup_id=backup_id,
                target_deployment=target_deployment,
                target_deployment_id=target_deployment_id,
                target_instance_id=target_instance_id,
                environment=environment,
                target_namespace=target_namespace,
                last=last,
            )

            rst = await sdk.backups.create_restore(
                backup_id=backup_id,
                target_namespace=target_namespace,
                target_instance_id=resolved_instance_id,
            )

            print_success(f"Restore '{rst.name}' created (id: {rst.id}, status: {rst.status})")

            if wait:
                console.print("Waiting for restore to complete...")
                rst = await sdk.backups.wait_for_restore(rst.id, max_wait=max_wait, interval=interval)

                if rst.status == "completed":
                    print_success("Restore completed")
                else:
                    print_error(f"Restore {rst.status}: {rst.error_message or 'unknown error'}")
                    raise SystemExit(1)


@backups_app.command(name="restore-get")
async def restore_get(restore_id: RestoreId) -> None:
    """Get restore operation details."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            rst = await sdk.backups.get_restore(restore_id)

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


@backups_app.command(name="restore-list")
async def restore_list(
    backup_id: BackupId,
    *,
    status: Annotated[str | None, Parameter(help="Filter by status.")] = None,
) -> None:
    """List restore operations for a backup."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            restores = await sdk.backups.list_restores(backup_id=backup_id, status=status)

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
