from fast_depends import Depends, inject
from loguru import logger

from styrmin_backend.domain.models import (
    Deployment,
    Instance,
    Task,
    TaskType,
)
from styrmin_backend.services.context import generate_context_from_deployment
from styrmin_backend.services.unit_of_work import UnitOfWork
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.manager import PrefectManager
from styrmin_backend.workflows.models import PrefectAction


async def generate_instance_from_deployment(
    deployment: Deployment,
    uow: UnitOfWork,
) -> Instance:
    """Generate an instance from a deployment."""
    context = await generate_context_from_deployment(deployment=deployment, uow=uow)

    instance = Instance.create(
        application_version=deployment.application_version,
        deployment_id=deployment.id,
        application_driver_version_id=deployment.application_driver_version_id,
        context=context,
    )

    instance.context.instance.id = instance.id
    return instance


@inject(cast_result=False)  # type: ignore[arg-type]
async def apply_state(
    deployment: Deployment,
    current_instance: Instance | None,
    uow: UnitOfWork,  # noqa: ARG001  retained for caller-shape stability
    prefect_manager: PrefectManager = Depends(get_manager),
) -> Task:
    """Schedule a reconciliation pass for the deployment.

    Server-side responsibility: create the Task row and kick off the
    Prefect ``apply_state`` flow with the IDs the flow needs to load
    fresh state. The flow itself computes the diff and remediation
    against a freshly-loaded deployment — see
    `agent/tasks/orchestration.py::apply_state`. Pre-#237 this function
    pre-computed a Remediation and serialized it across the Prefect
    boundary, which froze the plan against a snapshot of the world and
    produced staleness bugs whenever DB writes landed between the
    snapshot and the flow start.
    """
    new_instance = deployment.active_instance
    assert new_instance is not None, "Deployment must have an active instance"

    task = Task.create(
        type=TaskType.NOOP,
        deployment_id=deployment.id,
        prefect_flow_run_id=None,
    )

    logger.info(
        "Scheduling apply_state flow: task_id={} deployment_id={} "
        "current_instance_id={} new_instance_id={}",
        task.id,
        deployment.id,
        current_instance.id if current_instance else None,
        new_instance.id,
    )

    flow_info = await prefect_manager.run_action(
        action=PrefectAction.APPLY_STATE,
        parameters={
            "task_id": task.id,
            "deployment_id": deployment.id,
            "new_instance_id": new_instance.id,
            "current_instance_id": (current_instance.id if current_instance else None),
        },
    )
    task.prefect_flow_run_id = flow_info.id
    return task
