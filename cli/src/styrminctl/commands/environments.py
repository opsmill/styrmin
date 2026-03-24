"""Environment management commands."""

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
    name: str = typer.Argument(..., help="Name of the environment"),
    cluster_id: str = typer.Argument(..., help="UUID of the parent cluster"),
    config: str | None = typer.Option(None, "--config", "-c", help="JSON config (inline string or @filepath)"),
) -> None:
    """Create a new environment in a cluster."""
    parsed_config = parse_json_argument(config)

    async with _get_client() as client:
        try:
            env = await client.environments.create(name=name, cluster_id=cluster_id, config=parsed_config)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    print_success(f"Environment '{env.name}' created in cluster '{env.cluster.name}' (id: {env.id})")


@app.command(name="list")
async def list_environments() -> None:
    """List all environments."""
    async with _get_client() as client:
        try:
            environments = await client.environments.list()
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    if not environments:
        console.print("No environments found.")
        return

    rows = [
        {
            "id": str(e.id),
            "name": e.name,
            "cluster": e.cluster.name,
            "config": str(e.config) if e.config else "",
        }
        for e in environments
    ]
    print_table(rows, columns=["id", "name", "cluster", "config"], title="Environments")


@app.command()
async def get(
    environment_id: str = typer.Argument(..., help="UUID of the environment"),
) -> None:
    """Get an environment by ID."""
    async with _get_client() as client:
        try:
            env = await client.environments.get(environment_id)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    row = {
        "id": str(env.id),
        "name": env.name,
        "cluster": env.cluster.name,
        "config": str(env.config) if env.config else "",
    }
    print_table([row], columns=["id", "name", "cluster", "config"], title="Environment")


@app.command()
async def delete(
    environment_id: str = typer.Argument(..., help="UUID of the environment to delete"),
) -> None:
    """Delete an environment."""
    async with _get_client() as client:
        try:
            await client.environments.delete(environment_id)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    print_success("Environment deleted.")
