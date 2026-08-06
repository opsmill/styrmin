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
from styrminctl.types import (
    ClusterContextId,
    ClusterContextName,
    EnvironmentBackupId,
    EnvironmentName,
    MaxWait,
    OptionalEnvironmentId,
    PollInterval,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from styrmin_sdk import EnvironmentBackup, StyrminClient

environment_backups_app = App(name="env-backups", help="Manage environment-level backups and restores.")


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


async def _resolve_environment_id(
    sdk: StyrminClient,
    *,
    name: str | None,
    environment_id: str | None,
    cluster: str,
    cluster_id: str | None,
) -> str:
    """Resolve an environment to its UUID from a name (cluster-scoped) or ``--id``.

    ``createEnvironmentBackup`` and ``environmentBackups`` take a UUID only, so
    the name lookup goes through the ``environment`` query — which is where the
    ADR-0031 dual-identifier resolution actually lives (server-side, with the
    cluster scoping rules). The CLI never reimplements the name matching.

    Raises ``ValueError`` on any invalid identifier combination.
    """
    if name is not None and environment_id is not None:
        raise ValueError("Provide either an environment name or --id, not both")
    if name is None and environment_id is None:
        raise ValueError("Either an environment name or --id is required")
    if cluster_id is not None and cluster != "default":
        raise ValueError("Provide either --cluster or --cluster-id, not both")

    if environment_id is not None:
        return environment_id

    environment = await sdk.environments.get(
        environment_name=name,
        cluster_id=cluster_id,
        cluster_name=cluster if cluster_id is None else None,
    )
    return str(environment.id)


def _constituent_counts(constituents: Sequence[_ConstituentLike]) -> tuple[int, int, int]:
    """Return ``(ok, failed, total)`` for a snapshot's constituents.

    ``ok`` counts constituents whose backup row was created — the aggregate
    outcome of those backups is what the parent's derived ``status`` reports.
    ``failed`` counts constituents that could not be created at all (spec
    FR-005). Entries with neither are gaps left by individually deleted
    constituents and show up only in the total.
    """
    ok = sum(1 for c in constituents if c.backup is not None)
    failed = sum(1 for c in constituents if c.error is not None)
    return ok, failed, len(constituents)


def _print_constituents(constituents: Sequence[_ConstituentLike]) -> None:
    if not constituents:
        console.print("  Constituents: none (config-only snapshot)")
        return

    console.print("  Constituents:")
    for constituent in constituents:
        if constituent.backup is not None:
            detail = f"backup {constituent.backup.id} ({constituent.backup.status})"
        elif constituent.error is not None:
            detail = f"failed: {constituent.error}"
        else:
            # Neither backup nor error: the constituent backup was deleted
            # individually after the snapshot was taken. The gap is deliberately
            # visible rather than silently dropped.
            detail = "deleted"
        console.print(f"    - {constituent.deployment_name}: {detail}")


def _report_terminal_status(environment_backup: EnvironmentBackup) -> None:
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
            environment_id = await _resolve_environment_id(
                sdk,
                name=environment,
                environment_id=id,
                cluster=cluster,
                cluster_id=cluster_id,
            )
            environment_backup = await sdk.environment_backups.create(environment_id=environment_id, name=name)

            ok, failed, total = _constituent_counts(environment_backup.constituents)
            print_success(
                f"Environment backup '{environment_backup.name}' created "
                f"(id: {environment_backup.id}, status: {environment_backup.status.value}, "
                f"constituents: {ok}/{failed}/{total} ok/failed/total)"
            )
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
            environment_id = await _resolve_environment_id(
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
