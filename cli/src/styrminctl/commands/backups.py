"""Backup and restore management commands."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated

from cyclopts import App, Parameter
from rich.prompt import Confirm

from styrminctl import client
from styrminctl.output import console, print_error, print_success, print_table, styrmin_error_handler
from styrminctl.resolve import resolve_active_instance, resolve_deployment_id

if TYPE_CHECKING:
    from styrmin_sdk import StyrminClient
    from styrmin_sdk.graphql._generated.list_backups import ListBackupsBackups

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

#: Placeholder for retention values that were never recorded — backups taken
#: before retention tracking, and backups Velero stored nothing for, which get
#: no expiration. A failed backup can still show an expiry: Velero's
#: PartiallyFailed phase is stored, does expire, and is reported as FAILED.
#: An em-dash reads as "nothing here" rather than "zero"/"now".
NOT_RECORDED = "—"


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
    console.print(f"  Application version: {backup.instance.application_version}")
    console.print(f"  Started at: {backup.started_at or ''}")
    console.print(f"  Completed at: {backup.completed_at or ''}")
    console.print(f"  Size (bytes): {backup.size_bytes or ''}")
    console.print(f"  TTL: {backup.ttl or NOT_RECORDED}")
    console.print(f"  Expires at: {backup.expires_at or NOT_RECORDED}")
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
    """List a deployment's backup history: the backups of every instance it has had,
    newest first, with the application version each one was taken at.

    Target the deployment by name (optionally with --environment) or by --id.
    --instance-id lists the backups of one instance only.
    """
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            if instance_id is not None:
                target = await resolve_active_instance(
                    sdk,
                    deployment_name=deployment,
                    deployment_id=id,
                    instance_id=instance_id,
                    environment=environment,
                )
                backups = await sdk.backups.list_backups(instance_id=target.instance_id, status=status)
            else:
                deployment_id = await resolve_deployment_id(
                    sdk,
                    deployment_name=deployment,
                    deployment_id=id,
                    environment=environment,
                )
                backups = await sdk.backups.list_backups(deployment_id=deployment_id, status=status)

    if not backups:
        if deployment is not None and instance_id is None:
            # A deleted deployment's name can be reused, and its history stays with its id.
            console.print(
                f"No backups found for deployment '{deployment}'. If an earlier deployment named "
                f"'{deployment}' was deleted, list its backup history with --id <deployment-id>."
            )
        else:
            console.print("No backups found.")
        return

    rows = [
        {
            "id": str(b.id),
            "name": b.name,
            "status": b.status,
            "application_version": b.instance.application_version,
            "started_at": str(b.started_at or ""),
            "completed_at": str(b.completed_at or ""),
            "size_bytes": str(b.size_bytes or ""),
            "expires_at": str(b.expires_at) if b.expires_at else NOT_RECORDED,
        }
        for b in backups
    ]
    print_table(
        rows,
        columns=[
            "id",
            "name",
            "status",
            "application_version",
            "started_at",
            "completed_at",
            "size_bytes",
            "expires_at",
        ],
        title="Backups",
    )


@backups_app.command
async def delete(backup_id: BackupId) -> None:
    """Delete a backup and all associated restores."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            await sdk.backups.delete_backup(backup_id)

    print_success(f"Backup '{backup_id}' deleted")


def _has_expired(backup: ListBackupsBackups, now: datetime) -> bool:
    """Whether Velero's expiry for the backup has passed, so Velero may have deleted it."""
    return backup.expires_at is not None and backup.expires_at <= now


async def _latest_completed_backup(
    sdk: StyrminClient,
    *,
    deployment_id: str | None,
    instance_id: str | None,
    deployment_label: str | None,
) -> ListBackupsBackups:
    """Return the newest completed backup that has not expired.

    It comes from the backup history of ``deployment_id``, or from the backups
    of ``instance_id`` when no deployment is given. The server lists backups
    newest first. ``deployment_label`` names the deployment in the error
    message; the deployment id is used when it is ``None``.
    """
    if deployment_id is not None:
        backups_list = await sdk.backups.list_backups(deployment_id=deployment_id, status="completed")
        scope = f"deployment '{deployment_label or deployment_id}'"
    else:
        backups_list = await sdk.backups.list_backups(instance_id=instance_id, status="completed")
        scope = f"instance {instance_id}"

    now = datetime.now(UTC)
    for skipped, backup in enumerate(backups_list):
        if not _has_expired(backup, now):
            if skipped:
                console.print(f"Skipped {skipped} newer completed backup(s) whose expiry date has passed.")
            return backup
    if backups_list:
        raise ValueError(
            f"No completed backups found for {scope} that have not expired "
            f"({len(backups_list)} completed backup(s) have passed their expiry date)"
        )
    raise ValueError(f"No completed backups found for {scope}")


def _stdin_is_terminal() -> bool:
    return sys.stdin.isatty()


async def _confirm_backup_of_earlier_instance(
    sdk: StyrminClient,
    deployment_id: str,
    backup: ListBackupsBackups,
    *,
    yes: bool,
) -> None:
    """Ask before ``--last`` restores a backup of an earlier instance, or of another version.

    ``deployment_id`` is the deployment the backup was taken of, which the
    server restores it into. Refuses a deleted deployment, which the server
    also refuses. A deployment without an active instance has no instance the
    backup could be earlier than, so only the versions are compared.
    """
    deployment = await sdk.deployments.get(deployment_id)
    if deployment.deleted_at is not None:
        raise ValueError(
            f"Deployment '{deployment.name}' was deleted. List its backups with "
            f"'styrminctl backups list --id {deployment.id}'; a restore into it is refused."
        )
    backup_version = backup.instance.application_version
    current_version = deployment.application_version
    active_instance = deployment.application_instance
    is_earlier_instance = active_instance is not None and str(backup.instance_id) != str(active_instance.id)
    if not is_earlier_instance and backup_version == current_version:
        return

    taken_of = "an earlier instance of deployment" if is_earlier_instance else "deployment"
    console.print(
        f"[yellow]Warning:[/yellow] backup {backup.id} was taken of {taken_of} '{deployment.name}', "
        f"at application version {backup_version}. The deployment runs application version "
        f"{current_version} now."
    )
    instance_outcome = (
        "Styrmin keeps the current instance as the deployment's active instance."
        if active_instance is not None
        else "The deployment has no active instance, and the restore does not give it one."
    )
    console.print(
        "The restore puts back the StyrminDeployment and HelmRelease that the backup holds, with "
        f"that application version and config. {instance_outcome}"
    )
    if yes:
        return
    if not _stdin_is_terminal():
        raise ValueError("Not restoring this backup without confirmation. Pass --yes to restore it.")
    if not Confirm.ask("Restore this backup?", console=console, default=False):
        raise ValueError("Restore cancelled.")


#: The options that choose, with ``--last``, which backups the newest backup is picked from.
_TARGET_OPTIONS = "--target-deployment, --target-deployment-id, --target-instance-id and --environment"


def _refuse_target_options_with_backup_id(
    *,
    target_deployment: str | None,
    target_deployment_id: str | None,
    target_instance_id: str | None,
    environment: str | None,
) -> None:
    """Refuse a backup id combined with a target option, before anything is sent to the server.

    A backup is always restored into the deployment it was taken of, so a
    target option next to a backup id would only mislead the user.
    ``--environment`` narrows ``--target-deployment``, so it is refused too.
    """
    given = [
        option
        for option, value in (
            ("--target-deployment", target_deployment),
            ("--target-deployment-id", target_deployment_id),
            ("--target-instance-id", target_instance_id),
            ("--environment", environment),
        )
        if value is not None
    ]
    if given:
        raise ValueError(
            f"{_TARGET_OPTIONS} work only with --last. A backup is restored into the deployment it "
            f"was taken of. Run the command again without {' and '.join(given)}."
        )


async def _prepare_restore(
    sdk: StyrminClient,
    *,
    backup_id: str | None,
    target_deployment: str | None,
    target_deployment_id: str | None,
    target_instance_id: str | None,
    environment: str | None,
    last: bool,
    yes: bool = False,
) -> str:
    """Return the id of the backup to restore.

    With ``--last``, resolve the target deployment or instance and pick the
    newest completed backup from its backup history. Raises ``ValueError`` on
    any invalid combination.
    """
    target_selectors = [s for s in (target_deployment, target_deployment_id, target_instance_id) if s is not None]
    if len(target_selectors) > 1:
        raise ValueError("Provide only one of --target-deployment, --target-deployment-id, or --target-instance-id")

    if last:
        if not target_selectors:
            raise ValueError(
                "--last requires a target deployment (--target-deployment/--target-deployment-id) "
                "or --target-instance-id"
            )
        # Only the backup history is read here, so the deployment does not need an active
        # instance: the server restores into a deployment without one.
        deployment_id = None
        if target_instance_id is None:
            deployment_id = await resolve_deployment_id(
                sdk,
                deployment_name=target_deployment,
                deployment_id=target_deployment_id,
                environment=environment,
                not_found_hint="",
            )
        elif environment is not None:
            raise ValueError("--environment only applies when looking up a deployment by name.")
        backup = await _latest_completed_backup(
            sdk, deployment_id=deployment_id, instance_id=target_instance_id, deployment_label=target_deployment
        )
        backup_id = str(backup.id)
        console.print(
            f"Selected the newest completed backup: {backup_id} "
            f"(application version {backup.instance.application_version})"
        )
        # A raw --target-instance-id names no deployment, and the instance given can be an earlier
        # one. The server restores the backup into the deployment its instance belongs to, so
        # compare against that deployment.
        await _confirm_backup_of_earlier_instance(
            sdk, deployment_id or str(backup.instance.deployment_id), backup, yes=yes
        )

    if backup_id is None:
        raise ValueError("backup_id is required (or use --last with a target deployment/instance)")

    return backup_id


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
    last: Annotated[
        bool,
        Parameter(
            help=(
                "Restore the newest completed backup that has not expired, into the deployment it was "
                "taken of. --target-deployment or --target-deployment-id chooses the deployment whose "
                "backup history it comes from; that history holds the backups of the deployment's current "
                "and earlier instances. --target-instance-id chooses the instance whose backups it comes "
                "from. Restoring a backup of an earlier instance, or one taken at another application "
                "version, needs confirmation, or --yes."
            )
        ),
    ] = False,
    yes: Annotated[
        bool,
        Parameter(
            name=["--yes", "-y"],
            negative="",
            help=(
                "With --last, restore a backup of an earlier instance, or one taken at another "
                "application version, without asking for confirmation."
            ),
        ),
    ] = False,
    wait: Annotated[bool, Parameter(help="Wait for restore to complete.")] = False,
    max_wait: MaxWait = 300,
    interval: PollInterval = 5,
) -> None:
    """Restore a backup into the deployment it was taken of.

    Pass a backup id to restore that backup. Or pass --last with
    --target-deployment (and --environment), --target-deployment-id or
    --target-instance-id to restore the newest completed backup from that
    deployment's backup history, or from that instance's backups. These
    options choose which backups --last picks from, not where the backup is
    restored, and work only with --last.
    """
    with styrmin_error_handler():
        if last and backup_id is not None:
            raise ValueError("Provide either a backup_id or --last, not both")
        if backup_id is not None:
            _refuse_target_options_with_backup_id(
                target_deployment=target_deployment,
                target_deployment_id=target_deployment_id,
                target_instance_id=target_instance_id,
                environment=environment,
            )

        async with client.get_client() as sdk:
            backup_id = await _prepare_restore(
                sdk,
                backup_id=backup_id,
                target_deployment=target_deployment,
                target_deployment_id=target_deployment_id,
                target_instance_id=target_instance_id,
                environment=environment,
                last=last,
                yes=yes,
            )

            rst = await sdk.backups.create_restore(backup_id=backup_id)

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
