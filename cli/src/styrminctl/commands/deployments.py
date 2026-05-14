"""Deployment management commands."""

from __future__ import annotations

from typing import Annotated

from cyclopts import App, Parameter

# ``PLC2701`` is the ruff-preview "private-name import" rule; the codegen
# package is private by convention but is the only source of truth for the
# typed ``UpdateDeploymentInput`` model, so the suppression is intentional.
from styrmin_sdk.graphql._generated.input_types import (  # noqa: PLC2701
    UpdateDeploymentInput,
)

from styrminctl import client
from styrminctl.output import console, parse_json_argument, print_success, print_table, styrmin_error_handler
from styrminctl.types import ClusterContextId, ClusterContextName, DeploymentId, EnvironmentName, OptionalEnvironmentId

deployments_app = App(name="deployments", help="Manage deployments.")


@deployments_app.command
async def create(
    driver: Annotated[str, Parameter(help="Application driver name.")],
    version: Annotated[str, Parameter(help="Application version to deploy.")],
    environment: EnvironmentName = None,
    *,
    id: OptionalEnvironmentId = None,
    cluster: ClusterContextName = "default",
    cluster_id: ClusterContextId = None,
    name: Annotated[str | None, Parameter(help="Custom deployment name (auto-generated if omitted).")] = None,
    config: Annotated[str | None, Parameter(help="JSON config (inline or @filepath).")] = None,
) -> None:
    """Create a new deployment (deploy an application)."""
    with styrmin_error_handler():
        if environment is not None and id is not None:
            raise ValueError("Provide either an environment name or --id, not both")
        if environment is None and id is None:
            raise ValueError("Either an environment name or --id is required")
        if cluster_id is not None and cluster != "default":
            raise ValueError("Provide either --cluster or --cluster-id, not both")

        parsed_config = parse_json_argument(config)
        async with client.get_client() as sdk:
            task = await sdk.deployments.create(
                driver=driver,
                version=version,
                environment_id=id,
                environment_name=environment,
                cluster_id=cluster_id,
                cluster_name=cluster if cluster_id is None and id is None else None,
                name=name,
                config=parsed_config,
            )

    print_success(f"Deployment in progress (deployment: {task.deployment_id}, task: {task.id})")
    console.print(f"  Status: {task.status}")


@deployments_app.command
async def get(deployment_id: DeploymentId) -> None:
    """Get a deployment by ID."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            deployment = await sdk.deployments.get(deployment_id)

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


@deployments_app.command
async def update(
    deployment_id: DeploymentId,
    *,
    config: Annotated[
        str,
        Parameter(
            help="JSON UpdateDeploymentInput payload (inline or @filepath); snake_case or camelCase keys accepted."
        ),
    ],
) -> None:
    """Update a deployment's configuration."""
    with styrmin_error_handler():
        parsed_config = parse_json_argument(config)
        update_input = UpdateDeploymentInput.model_validate(parsed_config)
        async with client.get_client() as sdk:
            task = await sdk.deployments.update(deployment_id, input=update_input)

    print_success(f"Deployment update in progress (task: {task.id})")
    console.print(f"  Status: {task.status}")


@deployments_app.command(name="update-version")
async def update_version(
    deployment_id: DeploymentId,
    version: Annotated[str, Parameter(help="New application version.")],
) -> None:
    """Update a deployment's application version (internal API)."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            task = await sdk.deployments.update_version(deployment_id, version=version)

    print_success(f"Version update in progress (task: {task.id})")
    console.print(f"  Status: {task.status}")


@deployments_app.command(name="start-components")
async def start_components(
    deployment_id: DeploymentId,
    *,
    component: Annotated[list[str], Parameter(help="Component name (repeat for multiple).")],
) -> None:
    """Start components of a deployment (internal API)."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            task = await sdk.deployments.start_components(deployment_id, components=component)

    print_success(f"Components starting (task: {task.id})")
    console.print(f"  Status: {task.status}")


@deployments_app.command(name="stop-components")
async def stop_components(
    deployment_id: DeploymentId,
    *,
    component: Annotated[list[str], Parameter(help="Component name (repeat for multiple).")],
) -> None:
    """Stop components of a deployment (internal API)."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            task = await sdk.deployments.stop_components(deployment_id, components=component)

    print_success(f"Components stopping (task: {task.id})")
    console.print(f"  Status: {task.status}")


@deployments_app.command(name="run-job")
async def run_job(
    deployment_id: DeploymentId,
    *,
    image: Annotated[str, Parameter(help="Container image to use.")],
    command: Annotated[list[str], Parameter(help="Command to run (repeat for multiple).")],
    env: Annotated[str, Parameter(help="Environment variables as JSON (inline or @filepath).")],
) -> None:
    """Run a job on a deployment (internal API)."""
    with styrmin_error_handler():
        parsed_env = parse_json_argument(env)
        async with client.get_client() as sdk:
            task = await sdk.deployments.run_job(deployment_id, image=image, commands=command, env=parsed_env)

    print_success(f"Job running (task: {task.id})")
    console.print(f"  Status: {task.status}")


@deployments_app.command
async def context(deployment_id: DeploymentId) -> None:
    """Get the context of a deployment."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            ctx = await sdk.deployments.get_context(deployment_id)

    console.print_json(data=ctx.context)
