from uuid import UUID

from fast_depends import Depends, inject

from styrmin_backend.domain.models import (
    Task,
    TaskStatus,
    TaskType,
)
from styrmin_backend.services.exceptions import (
    DeploymentNotFoundError,
    NoInstanceError,
)
from styrmin_backend.services.reconciliation import (
    apply_state,
    generate_instance_from_deployment,
)
from styrmin_backend.services.unit_of_work import UnitOfWork
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.manager import PrefectManager
from styrmin_backend.workflows.models import PrefectAction


@inject(cast_result=False)  # type: ignore[arg-type]
async def run_job(
    deployment_id: UUID,
    commands: list[str],
    image: str,
    env: list[dict],
    uow: UnitOfWork,
    prefect_manager: PrefectManager = Depends(get_manager),
) -> Task:
    """Run a job for a deployment by its ID.

    Args:
        deployment_id (UUID): The ID of the deployment to run the job for.
        commands (list[str]): The list of commands to run.
        image (str): The image to use for the job.
        env (dict): The environment variables to set for the job.

    Raises:
        DeploymentNotFoundError: If the deployment is not found.

    Returns:
        Task: The task created for the deployment refresh.
    """
    async with uow:
        # Get the deployment
        deployment = await uow.deployments.find(id=deployment_id)
        if deployment is None:
            raise DeploymentNotFoundError(
                f"Deployment with ID {deployment_id} not found"
            )

        if deployment.active_instance is None:
            raise NoInstanceError(
                f"Deployment with ID {deployment_id} has no active instance"
            )

        # Get the runtime class
        runtime_class = deployment.active_instance.context.cluster.config.runtime_class

        # Get the namespace to run the job in
        namespace = deployment.active_instance.context.instance.namespace

        # Create a task
        task = Task.create(
            type=TaskType.RUN_JOB,
            deployment_id=deployment.id,
            prefect_flow_run_id=None,
            status=TaskStatus.PENDING,
        )

        # Run the prefect flow
        flow_run = await prefect_manager.run_action(
            action=PrefectAction.RUN_JOB,
            parameters={
                "runtime_class": runtime_class,
                "commands": commands,
                "env": env,
                "image": image,
                "namespace": namespace,
                "task_id": task.id,
            },
        )

        # Bind the prefect flow run id to the task
        task.prefect_flow_run_id = flow_run.id

        await uow.tasks.save(task=task)

        await uow.commit()

        result = await uow.tasks.find(id=task.id)
        assert result is not None, "Task not found"
        return result


async def stop_components(
    deployment_id: UUID,
    components: list[str],
    uow: UnitOfWork,
) -> Task:
    """Stop components for a deployment by its ID.

    Args:
        deployment_id (UUID): The ID of the deployment to stop components for.
        components (list[str]): The list of component names to stop.
        uow (UnitOfWork): The unit of work to use.

    Raises:
        DeploymentNotFoundError: If the deployment is not found.

    Returns:
        Task: The task created for the deployment refresh.
    """
    async with uow:
        # Get the deployment
        deployment = await uow.deployments.find(id=deployment_id)
        if deployment is None:
            raise DeploymentNotFoundError(
                f"Deployment with ID {deployment_id} not found"
            )

        # Handle unknown components name
        unknown_components = set(components) - set(deployment.get_components_names())
        if unknown_components:
            raise ValueError(f"Unknown components: {', '.join(unknown_components)}")

        # Stop the components
        for component_name in components:
            deployment.update_component(name=component_name, enabled=False)

        current_instance = deployment.active_instance
        # Generate the instance from the deployment
        instance = await generate_instance_from_deployment(
            deployment=deployment,
            uow=uow,
        )
        # Set the new instance as the active one
        deployment.set_active_instance(instance=instance)

        # Get the task from the reconciliation workflow
        task = await apply_state(
            deployment=deployment,
            current_instance=current_instance,
            uow=uow,
            task_type=TaskType.STOP_COMPONENTS,
        )

        await uow.deployments.save(deployment=deployment)

        await uow.tasks.save(task=task)

        await uow.commit()

        result = await uow.tasks.find(id=task.id)
        assert result is not None, "Task not found"
        return result


async def start_components(
    deployment_id: UUID,
    components: list[str],
    uow: UnitOfWork,
) -> Task:
    """Start components for a deployment by its ID.

    Args:
        deployment_id (UUID): The ID of the deployment to start components for.
        components (list[str]): The list of component names to start.
        uow (UnitOfWork): The unit of work to use.

    Raises:
        DeploymentNotFoundError: If the deployment is not found.

    Returns:
        Task: The task created for the deployment refresh.
    """
    async with uow:
        # Get the deployment
        deployment = await uow.deployments.find(id=deployment_id)
        if deployment is None:
            raise DeploymentNotFoundError(
                f"Deployment with ID {deployment_id} not found"
            )

        # Handle unknown components name
        unknown_components = set(components) - set(deployment.get_components_names())
        if unknown_components:
            raise ValueError(f"Unknown components: {', '.join(unknown_components)}")

        # Start the components
        for component_name in components:
            deployment.update_component(name=component_name, enabled=True)

        current_instance = deployment.active_instance
        # Generate the instance from the deployment
        instance = await generate_instance_from_deployment(
            deployment=deployment,
            uow=uow,
        )
        # Set the new instance as the active one
        deployment.set_active_instance(instance=instance)

        # Get the task from the reconciliation workflow
        task = await apply_state(
            deployment=deployment,
            current_instance=current_instance,
            uow=uow,
            task_type=TaskType.START_COMPONENTS,
        )

        await uow.deployments.save(deployment=deployment)

        await uow.tasks.save(task=task)

        await uow.commit()

        result = await uow.tasks.find(id=task.id)
        assert result is not None, "Task not found"
        return result
