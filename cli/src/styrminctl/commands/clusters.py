"""Cluster management commands."""

from __future__ import annotations

from typing import Annotated

from cyclopts import App, Parameter

from styrminctl import client
from styrminctl.output import console, parse_json_argument, print_success, print_table, styrmin_error_handler
from styrminctl.types import ClusterId

clusters_app = App(name="clusters", help="Manage clusters.")


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

    rows = [{"id": str(c.id), "name": c.name, "config": str(c.config) if c.config else ""} for c in clusters]
    print_table(rows, columns=["id", "name", "config"], title="Clusters")


@clusters_app.command
async def get(cluster_id: ClusterId) -> None:
    """Get a cluster by ID."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            cluster = await sdk.clusters.get(cluster_id)

    row = {"id": str(cluster.id), "name": cluster.name, "config": str(cluster.config) if cluster.config else ""}
    print_table([row], columns=["id", "name", "config"], title="Cluster")


@clusters_app.command
async def delete(cluster_id: ClusterId) -> None:
    """Delete a cluster."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            await sdk.clusters.delete(cluster_id)

    print_success("Cluster deleted.")
