"""Cluster management commands."""

from __future__ import annotations

import typer
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import StyrminError

from styrminctl.async_typer import AsyncTyper as Typer
from styrminctl.config import SETTINGS
from styrminctl.output import console, parse_json_argument, print_error, print_success, print_table

app = Typer()


def _get_client() -> StyrminClient:
    return StyrminClient(
        server_address=SETTINGS.server_address,
        timeout=SETTINGS.timeout,
        headers=SETTINGS.additional_headers,
    )


@app.command()
async def create(
    name: str = typer.Argument(..., help="Name of the cluster"),
    config: str | None = typer.Option(None, "--config", "-c", help="JSON config (inline string or @filepath)"),
) -> None:
    """Create a new cluster."""
    parsed_config = parse_json_argument(config)

    async with _get_client() as client:
        try:
            cluster = await client.clusters.create(name=name, config=parsed_config)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    print_success(f"Cluster '{cluster.name}' created (id: {cluster.id})")


@app.command(name="list")
async def list_clusters() -> None:
    """List all clusters."""
    async with _get_client() as client:
        try:
            clusters = await client.clusters.list()
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    if not clusters:
        console.print("No clusters found.")
        return

    rows = [{"id": str(c.id), "name": c.name, "config": str(c.config) if c.config else ""} for c in clusters]
    print_table(rows, columns=["id", "name", "config"], title="Clusters")


@app.command()
async def get(
    cluster_id: str = typer.Argument(..., help="UUID of the cluster"),
) -> None:
    """Get a cluster by ID."""
    async with _get_client() as client:
        try:
            cluster = await client.clusters.get(cluster_id)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    row = {"id": str(cluster.id), "name": cluster.name, "config": str(cluster.config) if cluster.config else ""}
    print_table([row], columns=["id", "name", "config"], title="Cluster")


@app.command()
async def delete(
    cluster_id: str = typer.Argument(..., help="UUID of the cluster to delete"),
) -> None:
    """Delete a cluster."""
    async with _get_client() as client:
        try:
            await client.clusters.delete(cluster_id)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    print_success("Cluster deleted.")
