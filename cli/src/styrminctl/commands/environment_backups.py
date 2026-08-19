"""Environment-level backup and restore commands.

The counterpart to :mod:`styrminctl.commands.backups`, one level up: a single
``env-backups create`` snapshots the environment config plus one constituent
backup per eligible deployment. The parent ``status`` is *derived* from those
constituents on every read, so ``--wait`` polls for a terminal derived status
(``COMPLETED`` / ``PARTIAL`` / ``FAILED``) rather than for a stored column.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Protocol

from cyclopts import App, Parameter

from styrminctl import client
from styrminctl.output import console, print_error, print_success, print_table, styrmin_error_handler
from styrminctl.resolve import resolve_environment_id
from styrminctl.types import (
    ClusterContextId,
    ClusterContextName,
    EnvironmentBackupId,
    EnvironmentName,
    EnvironmentRestoreId,
    MaxWait,
    OptionalEnvironmentId,
    PollInterval,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from styrmin_sdk import EnvironmentBackupStatus, EnvironmentRestoreStatus

environment_backups_app = App(name="env-backups", help="Manage environment-level backups and restores.")


#: Terminal environment-level statuses that mean "not everything worked".
#: The mutation derives the parent status synchronously, so it can already be
#: one of these when it returns — see :func:`create` and :func:`restore`.
_FAILED_STATUSES = frozenset({"FAILED", "PARTIAL"})

#: ``Backup.status`` is a plain string on the wire carrying the backend enum's
#: lowercase value, unlike the uppercase ``EnvironmentBackupStatus`` enum of the
#: parent. Compared case-insensitively so the counts survive either spelling.
_COMPLETED_BACKUP_STATUS = "completed"


class _BackupLike(Protocol):
    """The constituent-backup fields both the get and list projections carry."""

    @property
    def id(self) -> object: ...

    @property
    def status(self) -> str: ...


class _ConstituentLike(Protocol):
    """The per-constituent outcome shape shared by the get and list projections."""

    @property
    def deployment_name(self) -> str: ...

    @property
    def error(self) -> str | None: ...

    @property
    def backup(self) -> _BackupLike | None: ...


class _DetailedBackupLike(_BackupLike, Protocol):
    """A constituent backup that also carries its own failure reason.

    The get and create projections select ``errorMessage``; the list projection
    does not (it only renders counts), which is why this is a separate protocol
    rather than a field on :class:`_BackupLike`.
    """

    @property
    def error_message(self) -> str | None: ...


class _DetailedConstituentLike(Protocol):
    """A per-constituent outcome whose backup can explain its own failure."""

    @property
    def deployment_name(self) -> str: ...

    @property
    def error(self) -> str | None: ...

    @property
    def backup(self) -> _DetailedBackupLike | None: ...


class _RestoreLike(Protocol):
    """The constituent-restore fields both the restore-get and restore-list projections carry."""

    @property
    def id(self) -> object: ...

    @property
    def name(self) -> str: ...

    @property
    def status(self) -> str: ...

    @property
    def error_message(self) -> str | None: ...


class _SkippedConstituentLike(Protocol):
    """A constituent that was not restored, attributed by deployment name and reason."""

    @property
    def deployment_name(self) -> str: ...

    @property
    def reason(self) -> str: ...


class _EnvironmentBackupLike(Protocol):
    """A snapshot as returned by either the create mutation or the get query.

    Both carry the same derived status and per-constituent projection, and the
    terminal report is reached from both paths (the mutation can already return
    a terminal status), so the reporter is typed structurally rather than
    against one of the two generated shapes.
    """

    @property
    def status(self) -> EnvironmentBackupStatus: ...

    @property
    def constituents(self) -> Sequence[_DetailedConstituentLike]: ...


class _EnvironmentRestoreLike(Protocol):
    """A restore as returned by either the restore mutation or the get query."""

    @property
    def status(self) -> EnvironmentRestoreStatus: ...

    @property
    def restores(self) -> Sequence[_RestoreLike]: ...

    @property
    def skipped_constituents(self) -> Sequence[_SkippedConstituentLike]: ...


def _constituent_counts(constituents: Sequence[_ConstituentLike]) -> tuple[int, int, int]:
    """Return ``(ok, failed, total)`` for a snapshot's constituents.

    ``ok`` counts constituents whose backup actually **completed**, not merely
    those whose row exists: counting a created-but-failed backup as ok made a
    ``PARTIAL`` snapshot print ``constituents: 2/0/2``, contradicting its own
    status on one line. ``failed`` counts constituents that never got a row at
    all (spec FR-005). Entries with neither — the gaps left by individually
    deleted constituents — and rows still in flight show up only in the total.
    """
    ok = sum(1 for c in constituents if c.backup is not None and c.backup.status.lower() == _COMPLETED_BACKUP_STATUS)
    failed = sum(1 for c in constituents if c.error is not None)
    return ok, failed, len(constituents)


def _print_constituents(constituents: Sequence[_DetailedConstituentLike]) -> None:
    if not constituents:
        console.print("  Constituents: none (config-only snapshot)")
        return

    console.print("  Constituents:")
    for constituent in constituents:
        if constituent.backup is not None:
            detail = f"backup {constituent.backup.id} ({constituent.backup.status})"
            if constituent.backup.error_message is not None:
                # A constituent that failed *after* its row was created carries
                # its own reason; without it ``--wait`` printed a bare
                # ``backup <id> (failed)`` and left the operator to go digging.
                detail = f"{detail} — {constituent.backup.error_message}"
        elif constituent.error is not None:
            detail = f"failed: {constituent.error}"
        else:
            # Neither backup nor error: the constituent backup was deleted
            # individually after the snapshot was taken. The gap is deliberately
            # visible rather than silently dropped.
            detail = "deleted"
        console.print(f"    - {constituent.deployment_name}: {detail}")


def _report_terminal_status(environment_backup: _EnvironmentBackupLike) -> None:
    """Print the polled outcome and exit non-zero unless every constituent completed.

    ``PARTIAL`` exits non-zero too: the snapshot is real and restorable, but a
    script that asked for a coordinated backup of an environment did not get
    one for every deployment, and the exit code is the only machine-readable
    place to say so.
    """
    status = environment_backup.status.value
    if status == "COMPLETED":
        print_success("Environment backup completed")
        return

    if status == "PARTIAL":
        console.print("[yellow]Warning:[/yellow] Environment backup PARTIAL — some constituents did not complete")
    else:
        print_error(f"Environment backup {status}")
    _print_constituents(environment_backup.constituents)
    raise SystemExit(1)


def _print_restores(restores: Sequence[_RestoreLike]) -> None:
    if not restores:
        console.print("  Restored constituents: none")
        return

    console.print("  Restored constituents:")
    for restore in restores:
        detail = f"restore {restore.id} ({restore.status})"
        if restore.error_message is not None:
            detail = f"{detail} — {restore.error_message}"
        console.print(f"    - {restore.name}: {detail}")


def _print_skipped_constituents(skipped_constituents: Sequence[_SkippedConstituentLike]) -> None:
    """Print every non-restored constituent with its deployment name and reason.

    Spec FR-007 / SC-004: zero silent skips. ``reason`` is free text from the
    backend, not a closed vocabulary, so it is printed verbatim rather than
    mapped through a lookup table that would drop unknown values.
    """
    if not skipped_constituents:
        console.print("  Skipped constituents: none")
        return

    console.print("  Skipped constituents:")
    for skipped in skipped_constituents:
        console.print(f"    - {skipped.deployment_name}: {skipped.reason}")


def _report_terminal_restore_status(environment_restore: _EnvironmentRestoreLike) -> None:
    """Print the polled outcome and exit non-zero unless every constituent restored.

    Mirrors :func:`_report_terminal_status`: ``PARTIAL`` exits non-zero too,
    because a script that asked to restore an environment did not get every
    deployment back, and the exit code is the only machine-readable place to
    say so.
    """
    status = environment_restore.status.value
    if status == "COMPLETED":
        print_success("Environment restore completed")
        return

    if status == "PARTIAL":
        console.print("[yellow]Warning:[/yellow] Environment restore PARTIAL — some constituents did not restore")
    else:
        print_error(f"Environment restore {status}")
    _print_restores(environment_restore.restores)
    _print_skipped_constituents(environment_restore.skipped_constituents)
    raise SystemExit(1)


@environment_backups_app.command
async def create(
    environment: EnvironmentName = None,
    *,
    id: OptionalEnvironmentId = None,
    cluster: ClusterContextName = "default",
    cluster_id: ClusterContextId = None,
    name: Annotated[str | None, Parameter(help="Optional environment backup name.")] = None,
    wait: Annotated[bool, Parameter(help="Wait for every constituent backup to reach a terminal state.")] = False,
    max_wait: MaxWait = 600,
    interval: PollInterval = 5,
) -> None:
    """Create a coordinated backup of an environment.

    Target the environment by name (optionally with --cluster/--cluster-id) or
    by --id. One constituent backup is created per eligible deployment; an
    environment with none yields a config-only snapshot.
    """
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            environment_id = await resolve_environment_id(
                sdk,
                name=environment,
                environment_id=id,
                cluster=cluster,
                cluster_id=cluster_id,
            )
            environment_backup = await sdk.environment_backups.create(environment_id=environment_id, name=name)

            ok, failed, total = _constituent_counts(environment_backup.constituents)
            summary = (
                f"Environment backup '{environment_backup.name}' created "
                f"(id: {environment_backup.id}, status: {environment_backup.status.value}, "
                f"constituents: {ok}/{failed}/{total} ok/failed/total)"
            )

            if environment_backup.status.value in _FAILED_STATUSES:
                # The parent status is derived synchronously, so a fan-out where
                # every constituent failed at creation comes back terminal from
                # the mutation itself. Printing "Success" and exiting 0 there
                # would report a backup that does not exist as one that does.
                # Nothing is polled: FAILED and PARTIAL are terminal already.
                console.print(summary)
                _report_terminal_status(environment_backup)

            print_success(summary)
            _print_constituents(environment_backup.constituents)

            if wait:
                console.print("Waiting for constituent backups to complete...")
                environment_backup = await sdk.environment_backups.wait_for_backup(
                    environment_backup.id, max_wait=max_wait, interval=interval
                )
                _report_terminal_status(environment_backup)


@environment_backups_app.command
async def get(environment_backup_id: EnvironmentBackupId) -> None:
    """Get environment backup details, including per-constituent outcomes."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            environment_backup = await sdk.environment_backups.get(environment_backup_id)

    console.print(f"  ID: {environment_backup.id}")
    console.print(f"  Name: {environment_backup.name}")
    console.print(f"  Status: {environment_backup.status.value}")
    console.print(f"  Environment ID: {environment_backup.environment_id}")
    console.print(f"  Created on: {environment_backup.created_on}")
    console.print(f"  Environment config: {environment_backup.environment_config}")
    console.print(f"  Deployment snapshots: {len(environment_backup.deployment_snapshots)}")
    _print_constituents(environment_backup.constituents)


@environment_backups_app.command(name="list")
async def list_environment_backups(
    environment: EnvironmentName = None,
    *,
    id: OptionalEnvironmentId = None,
    cluster: ClusterContextName = "default",
    cluster_id: ClusterContextId = None,
) -> None:
    """List an environment's environment backups, newest first."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            environment_id = await resolve_environment_id(
                sdk,
                name=environment,
                environment_id=id,
                cluster=cluster,
                cluster_id=cluster_id,
            )
            environment_backups = await sdk.environment_backups.list(environment_id=environment_id)

    if not environment_backups:
        console.print("No environment backups found.")
        return

    rows = []
    for environment_backup in environment_backups:
        ok, failed, total = _constituent_counts(environment_backup.constituents)
        rows.append(
            {
                "id": str(environment_backup.id),
                "name": environment_backup.name,
                "status": environment_backup.status.value,
                "constituents": f"{ok}/{failed}/{total}",
                "created_on": str(environment_backup.created_on),
            }
        )
    print_table(
        rows,
        columns=["id", "name", "status", "constituents", "created_on"],
        title="Environment backups (constituents: ok/failed/total)",
    )


@environment_backups_app.command
async def delete(environment_backup_id: EnvironmentBackupId) -> None:
    """Delete an environment backup, its constituent backups, and their restores.

    Works regardless of the snapshot's status: deleting one whose constituents
    are still in flight is the escape hatch for an environment pinned in
    progress by a constituent backup that never got picked up.
    """
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            await sdk.environment_backups.delete(environment_backup_id)

    print_success(f"Environment backup '{environment_backup_id}' deleted")


@environment_backups_app.command
async def restore(
    environment_backup_id: EnvironmentBackupId,
    *,
    wait: Annotated[bool, Parameter(help="Wait for every constituent restore to reach a terminal state.")] = False,
    max_wait: MaxWait = 900,
    interval: PollInterval = 5,
) -> None:
    """Restore an environment backup in place.

    Reverts the environment's captured config and restores every usable
    constituent into its existing deployment. Requires the ADMIN role. Every
    constituent that is not restored is printed with its deployment name and
    reason.
    """
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            environment_restore = await sdk.environment_backups.restore(environment_backup_id)

            summary = (
                f"Environment restore started (id: {environment_restore.id}, "
                f"status: {environment_restore.status.value}, "
                f"restored: {len(environment_restore.restores)}, "
                f"skipped: {len(environment_restore.skipped_constituents)})"
            )

            if environment_restore.status.value in _FAILED_STATUSES:
                # Same as ``create``: the derived status can already be terminal
                # when the mutation returns — every constituent skipped is a
                # FAILED restore — and "Success" plus exit 0 would hide it.
                console.print(summary)
                _report_terminal_restore_status(environment_restore)

            print_success(summary)
            _print_restores(environment_restore.restores)
            _print_skipped_constituents(environment_restore.skipped_constituents)

            if wait:
                console.print("Waiting for constituent restores to complete...")
                environment_restore = await sdk.environment_backups.wait_for_restore(
                    environment_restore.id, max_wait=max_wait, interval=interval
                )
                _report_terminal_restore_status(environment_restore)


@environment_backups_app.command(name="restore-get")
async def restore_get(environment_restore_id: EnvironmentRestoreId) -> None:
    """Get environment restore details, including skipped constituents and their reasons."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            environment_restore = await sdk.environment_backups.get_restore(environment_restore_id)

    console.print(f"  ID: {environment_restore.id}")
    console.print(f"  Status: {environment_restore.status.value}")
    console.print(f"  Environment backup ID: {environment_restore.environment_backup_id}")
    console.print(f"  Created on: {environment_restore.created_on}")
    _print_restores(environment_restore.restores)
    _print_skipped_constituents(environment_restore.skipped_constituents)


@environment_backups_app.command(name="restore-list")
async def restore_list(environment_backup_id: EnvironmentBackupId) -> None:
    """List the coordinated restores performed from an environment backup, newest first."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            environment_restores = await sdk.environment_backups.list_restores(environment_backup_id)

    if not environment_restores:
        console.print("No environment restores found.")
        return

    rows = [
        {
            "id": str(environment_restore.id),
            "status": environment_restore.status.value,
            "restored": str(len(environment_restore.restores)),
            "skipped": str(len(environment_restore.skipped_constituents)),
            "created_on": str(environment_restore.created_on),
        }
        for environment_restore in environment_restores
    ]
    print_table(
        rows,
        columns=["id", "status", "restored", "skipped", "created_on"],
        title="Environment restores",
    )
