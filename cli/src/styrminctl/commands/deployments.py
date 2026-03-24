"""Deployment management commands."""

from __future__ import annotations

from typing import Annotated

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
    driver: str = typer.Argument(..., help="Application driver name"),
    version: str = typer.Argument(..., help="Application version to deploy"),
    environment_id: str = typer.Argument(..., help="UUID of the target environment"),
    name: str | None = typer.Option(None, "--name", "-n", help="Custom deployment name (auto-generated if omitted)"),
    config: str | None = typer.Option(None, "--config", "-c", help="JSON config (inline string or @filepath)"),
) -> None:
    """Create a new deployment (deploy an application)."""
    parsed_config = parse_json_argument(config)

    async with _get_client() as client:
        try:
            task = await client.deployments.create(
                driver=driver, version=version, environment_id=environment_id, name=name, config=parsed_config
            )
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    print_success(f"Deployment in progress (deployment: {task.deployment_id}, task: {task.id})")
    console.print(f"  Status: {task.status}")


@app.command()
async def get(
    deployment_id: str = typer.Argument(..., help="UUID of the deployment"),
) -> None:
    """Get a deployment by ID."""
    async with _get_client() as client:
        try:
            deployment = await client.deployments.get(deployment_id)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    console.print(f"  ID: {deployment.id}")
    console.print(f"  Name: {deployment.name}")
    console.print(f"  Status: {deployment.status}")
    console.print(f"  Application version: {deployment.application_version}")
    console.print(f"  Driver version ID: {deployment.application_driver_version_id}")
    console.print(f"  Environment ID: {deployment.environment_id}")
    console.print(f"  Config: {deployment.config or ''}")

    if deployment.application_instance:
        instance = deployment.application_instance
        console.print(f"  Instance: {instance.id} (status: {instance.status})")

    if deployment.components:
        rows = [{"id": str(c.id), "name": c.name, "enabled": str(c.enabled)} for c in deployment.components]
        print_table(rows, columns=["id", "name", "enabled"], title="Components")


@app.command()
async def update(
    deployment_id: str = typer.Argument(..., help="UUID of the deployment to update"),
    config: str = typer.Option(..., "--config", "-c", help="JSON config (inline string or @filepath)"),
) -> None:
    """Update a deployment's configuration."""
    parsed_config = parse_json_argument(config)

    async with _get_client() as client:
        try:
            task = await client.deployments.update(deployment_id, config=parsed_config)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    print_success(f"Deployment update in progress (task: {task.id})")
    console.print(f"  Status: {task.status}")


@app.command(name="update-version")
async def update_version(
    deployment_id: str = typer.Argument(..., help="UUID of the deployment"),
    version: str = typer.Argument(..., help="New application version"),
) -> None:
    """Update a deployment's application version (internal API)."""
    async with _get_client() as client:
        try:
            task = await client.deployments.update_version(deployment_id, version=version)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    print_success(f"Version update in progress (task: {task.id})")
    console.print(f"  Status: {task.status}")


@app.command(name="start-components")
async def start_components(
    deployment_id: str = typer.Argument(..., help="UUID of the deployment"),
    components: Annotated[
        list[str], typer.Option("--component", "-c", help="Component name (repeat for multiple)")
    ] = ...,  # type: ignore[assignment]
) -> None:
    """Start components of a deployment (internal API)."""
    async with _get_client() as client:
        try:
            task = await client.deployments.start_components(deployment_id, components=components)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    print_success(f"Components starting (task: {task.id})")
    console.print(f"  Status: {task.status}")


@app.command(name="stop-components")
async def stop_components(
    deployment_id: str = typer.Argument(..., help="UUID of the deployment"),
    components: Annotated[
        list[str], typer.Option("--component", "-c", help="Component name (repeat for multiple)")
    ] = ...,  # type: ignore[assignment]
) -> None:
    """Stop components of a deployment (internal API)."""
    async with _get_client() as client:
        try:
            task = await client.deployments.stop_components(deployment_id, components=components)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    print_success(f"Components stopping (task: {task.id})")
    console.print(f"  Status: {task.status}")


@app.command(name="run-job")
async def run_job(
    deployment_id: str = typer.Argument(..., help="UUID of the deployment"),
    image: str = typer.Option(..., "--image", "-i", help="Container image to use"),
    commands: Annotated[list[str], typer.Option("--command", help="Command to run (repeat for multiple)")] = ...,  # type: ignore[assignment]
    env: str = typer.Option(..., "--env", "-e", help="Environment variables as JSON (inline string or @filepath)"),
) -> None:
    """Run a job on a deployment (internal API)."""
    parsed_env = parse_json_argument(env)

    async with _get_client() as client:
        try:
            task = await client.deployments.run_job(deployment_id, image=image, commands=commands, env=parsed_env)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    print_success(f"Job running (task: {task.id})")
    console.print(f"  Status: {task.status}")


@app.command()
async def context(
    deployment_id: str = typer.Argument(..., help="UUID of the deployment"),
) -> None:
    """Get the context of a deployment."""
    async with _get_client() as client:
        try:
            ctx = await client.deployments.get_context(deployment_id)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    console.print_json(data=ctx.context)
