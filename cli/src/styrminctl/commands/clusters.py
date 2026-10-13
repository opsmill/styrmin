"""Cluster management commands."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated, Protocol

from cyclopts import App, Parameter
from rich.markup import escape
from styrmin_sdk.exceptions import StyrminTransportError
from styrmin_sdk.resources.clusters import cluster_update_input

from styrminctl import client
from styrminctl.output import (
    console,
    parse_json_argument,
    print_success,
    print_table,
    styrmin_error_handler,
)
from styrminctl.types import ClusterName, OptionalClusterId

if TYPE_CHECKING:
    from uuid import UUID

    from styrmin_sdk.models import ClusterUpdateResult

clusters_app = App(name="clusters", help="Manage clusters.")


def _config_cell(config: object) -> str:
    """The config as JSON in a table cell; ``clusters get --json`` prints it whole."""
    return escape(json.dumps(config, sort_keys=True)) if config is not None else ""


@clusters_app.command
async def create(
    name: Annotated[str, Parameter(help="Name of the cluster.")],
    *,
    config: Annotated[str | None, Parameter(help="JSON config (inline or @filepath).")] = None,
) -> None:
    """Create a new cluster."""
    with styrmin_error_handler():
        parsed_config = parse_json_argument(config)
        async with client.get_client() as sdk:
            cluster = await sdk.clusters.create(name=name, config=parsed_config)

    print_success(f"Cluster '{cluster.name}' created (id: {cluster.id})")


@clusters_app.command(name="list")
async def list_clusters() -> None:
    """List all clusters."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            clusters = await sdk.clusters.list()

    if not clusters:
        console.print("No clusters found.")
        return

    rows = [{"id": str(c.id), "name": c.name, "config": _config_cell(c.config)} for c in clusters]
    print_table(rows, columns=["id", "name", "config"], title="Clusters")


@clusters_app.command
async def get(
    name: ClusterName = None,
    *,
    id: OptionalClusterId = None,
    json_output: Annotated[
        bool,
        Parameter(
            name="--json",
            help="Print only the cluster's config as JSON, to edit and pass to clusters update --config @FILE.",
        ),
    ] = False,
) -> None:
    """Get a cluster by name or ID."""
    with styrmin_error_handler():
        if name is not None and id is not None:
            raise ValueError("Provide either a name or --id, not both")
        if name is None and id is None:
            raise ValueError("Either a name or --id is required")

        async with client.get_client() as sdk:
            cluster = await sdk.clusters.get(cluster_id=id, cluster_name=name)

    if json_output:
        print(json.dumps(cluster.config or {}, indent=2, sort_keys=True))
        return
    row = {"id": str(cluster.id), "name": cluster.name, "config": _config_cell(cluster.config)}
    print_table([row], columns=["id", "name", "config"], title="Cluster")


class _DeploymentEntry(Protocol):
    environment_name: str
    deployment_name: str
    task_id: UUID | None


def _deployment_rows(entries: Sequence[_DeploymentEntry], *, with_task: bool = False) -> None:
    rows = [
        {
            "environment": entry.environment_name,
            "deployment": entry.deployment_name,
            "task": str(entry.task_id) if entry.task_id else "",
        }
        for entry in entries
    ]
    print_table(rows, columns=["environment", "deployment", "task"] if with_task else ["environment", "deployment"])


def _print_update_result(result: ClusterUpdateResult) -> None:
    """Print which deployments the update redeploys, leaves waiting, skips or could not start."""
    verb = "would be" if result.dry_run else "are being"
    if result.redeployed:
        console.print(f"{len(result.redeployed)} deployment(s) {verb} redeployed:")
        _deployment_rows(result.redeployed, with_task=not result.dry_run)
    if result.waiting_for_ingress:
        console.print(
            f"{len(result.waiting_for_ingress)} deployment(s) wait for their environment's dedicated ingress "
            "controller, and are redeployed when it runs with the new values:"
        )
        _deployment_rows(result.waiting_for_ingress)
    if result.skipped_restoring:
        console.print(
            f"{len(result.skipped_restoring)} deployment(s) are not redeployed because a restore runs. "
            "Run this command again after the restore:"
        )
        _deployment_rows(result.skipped_restoring)
    if result.ingress_controllers:
        rows = [
            {
                "environment": controller.environment_name,
                "action": controller.action.value.lower(),
                "result": "failed to start" if controller.failed else "",
            }
            for controller in result.ingress_controllers
        ]
        print_table(rows, columns=["environment", "action", "result"], title="Dedicated ingress controllers")
    if result.failed_to_start:
        console.print(f"[red]{len(result.failed_to_start)} deployment(s) could not be redeployed:[/red]")
        _deployment_rows(result.failed_to_start)
    if result.failed_environments:
        names = ", ".join(escape(env.environment_name) for env in result.failed_environments)
        console.print(f"[red]These environments could not be evaluated: {names}[/red]")
    failed = result.failed_to_start or result.failed_environments or any(c.failed for c in result.ingress_controllers)
    if failed and not result.dry_run:
        console.print("Run this command again to retry them. The config is saved.")
    if not (result.redeployed or result.waiting_for_ingress or result.skipped_restoring or failed):
        none = "none would be" if result.dry_run else "none is"
        console.print(f"No deployment takes a changed value, so {none} redeployed.")
    console.print(f"{result.unchanged_count} deployment(s) already run with this config.")
    if result.redeployed and not result.dry_run:
        console.print("Follow a redeploy with: styrminctl tasks get TASK_ID")


@clusters_app.command
async def update(
    name: ClusterName = None,
    *,
    id: OptionalClusterId = None,
    config: Annotated[
        str,
        Parameter(
            help="The whole cluster config (inline JSON or @filepath), as for create; snake_case or camelCase keys "
            "accepted. A value left out is removed."
        ),
    ],
    dry_run: Annotated[
        bool,
        Parameter(help="Check the config and list the deployments that would be redeployed, without saving."),
    ] = False,
) -> None:
    """Replace a cluster's config and redeploy the deployments that take a changed value."""
    with styrmin_error_handler():
        if name is not None and id is not None:
            raise ValueError("Provide either a name or --id, not both")
        if name is None and id is None:
            raise ValueError("Either a name or --id is required")

        parsed_config = parse_json_argument(config)
        if not isinstance(parsed_config, dict):
            raise ValueError("The config must be a JSON object")
        # Refuses misspelled keys before connecting; the SDK checks again.
        cluster_update_input(parsed_config)
        async with client.get_client() as sdk:
            try:
                result = await sdk.clusters.update(parsed_config, cluster_id=id, cluster_name=name, dry_run=dry_run)
            except StyrminTransportError as e:
                raise StyrminTransportError(
                    f"{e} The server may still be saving the config and starting the redeploys; "
                    "check the config with styrminctl clusters get before running this command again."
                ) from e

    cluster = result.cluster
    if dry_run:
        console.print(f"Dry run for cluster '{escape(cluster.name)}': nothing was saved.")
    else:
        print_success(f"Cluster '{cluster.name}' updated (id: {cluster.id})")
    _print_update_result(result)


@clusters_app.command
async def delete(
    name: ClusterName = None,
    *,
    id: OptionalClusterId = None,
) -> None:
    """Delete a cluster by name or ID."""
    with styrmin_error_handler():
        if name is not None and id is not None:
            raise ValueError("Provide either a name or --id, not both")
        if name is None and id is None:
            raise ValueError("Either a name or --id is required")

        async with client.get_client() as sdk:
            await sdk.clusters.delete(cluster_id=id, cluster_name=name)

    print_success("Cluster deleted.")
