"""Environment management commands."""

from __future__ import annotations

from typing import Annotated

from cyclopts import App, Parameter

from styrminctl import client
from styrminctl.output import console, parse_json_argument, print_success, print_table, styrmin_error_handler
from styrminctl.types import ClusterContextId, ClusterContextName, EnvironmentName, OptionalEnvironmentId

environments_app = App(name="environments", help="Manage environments.")


@environments_app.command
async def create(
    name: Annotated[str, Parameter(help="Name of the environment.")],
    *,
    cluster: ClusterContextName = "default",
    cluster_id: ClusterContextId = None,
    config: Annotated[str | None, Parameter(alias="-c", help="JSON config (inline or @filepath).")] = None,
) -> None:
    """Create a new environment in a cluster."""
    with styrmin_error_handler():
        if cluster_id is not None and cluster != "default":
            raise ValueError("Provide either --cluster or --cluster-id, not both")

        parsed_config = parse_json_argument(config)
        async with client.get_client() as sdk:
            env = await sdk.environments.create(
                name=name,
                cluster_id=cluster_id,
                cluster_name=cluster if cluster_id is None else None,
                config=parsed_config,
            )

    print_success(f"Environment '{env.name}' created in cluster '{env.cluster.name}' (id: {env.id})")


@environments_app.command(name="list")
async def list_environments() -> None:
    """List all environments."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            environments = await sdk.environments.list()

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


@environments_app.command
async def get(
    name: EnvironmentName = None,
    *,
    id: OptionalEnvironmentId = None,
    cluster: ClusterContextName = "default",
    cluster_id: ClusterContextId = None,
) -> None:
    """Get an environment by name or ID."""
    with styrmin_error_handler():
        if name is not None and id is not None:
            raise ValueError("Provide either a name or --id, not both")
        if name is None and id is None:
            raise ValueError("Either a name or --id is required")
        if cluster_id is not None and cluster != "default":
            raise ValueError("Provide either --cluster or --cluster-id, not both")

        async with client.get_client() as sdk:
            if id is not None:
                env = await sdk.environments.get(environment_id=id)
            else:
                env = await sdk.environments.get(
                    environment_name=name,
                    cluster_id=cluster_id,
                    cluster_name=cluster if cluster_id is None else None,
                )

    row = {
        "id": str(env.id),
        "name": env.name,
        "cluster": env.cluster.name,
        "config": str(env.config) if env.config else "",
    }
    print_table([row], columns=["id", "name", "cluster", "config"], title="Environment")


@environments_app.command
async def delete(
    name: EnvironmentName = None,
    *,
    id: OptionalEnvironmentId = None,
    cluster: ClusterContextName = "default",
    cluster_id: ClusterContextId = None,
) -> None:
    """Delete an environment by name or ID."""
    with styrmin_error_handler():
        if name is not None and id is not None:
            raise ValueError("Provide either a name or --id, not both")
        if name is None and id is None:
            raise ValueError("Either a name or --id is required")
        if cluster_id is not None and cluster != "default":
            raise ValueError("Provide either --cluster or --cluster-id, not both")

        async with client.get_client() as sdk:
            if id is not None:
                await sdk.environments.delete(environment_id=id)
            else:
                await sdk.environments.delete(
                    environment_name=name,
                    cluster_id=cluster_id,
                    cluster_name=cluster if cluster_id is None else None,
                )

    print_success("Environment deleted.")
