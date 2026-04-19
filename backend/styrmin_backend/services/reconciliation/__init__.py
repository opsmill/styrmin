from fast_depends import Depends, inject
from loguru import logger

from styrmin_backend.domain.models import (
    Deployment,
    Instance,
    Task,
    TaskType,
)
from styrmin_backend.services.context import generate_context_from_deployment
from styrmin_backend.services.reconciliation.diffs.comparison import Comparator
from styrmin_backend.services.reconciliation.remediation import Remediator
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

    # Tag the context with the instance id so the CRD carries it and
    # the server can correlate agent status reports to the active instance.
    instance.context.instance.id = instance.id

    return instance


@inject(cast_result=False)  # type: ignore[arg-type]
async def apply_state(
    deployment: Deployment,
    current_instance: Instance | None,
    uow: UnitOfWork,
    prefect_manager: PrefectManager = Depends(get_manager),
) -> Task:
    """Reconciliate the running application instance with the new one."""
    new_instance = deployment.active_instance

    logger.info(
        "Reconciling deployment_id={}: current_instance={} -> new_instance={}",
        deployment.id,
        current_instance.id if current_instance else "None",
        new_instance.id if new_instance else "None",
    )

    # Generate diffs between the current instance and the new one
    comparator = Comparator(
        current_instance=current_instance,
        new_instance=new_instance,
    )
    diff_report = comparator.compare()
    logger.info("Diff report: {}", diff_report)

    # Generate remediation for the diffs
    remediator = Remediator(uow=uow)
    remediation = await remediator.generate_remediation(diff_report=diff_report)

    if remediation:
        logger.info(
            "Remediation generated: type={} instance_id={}",
            remediation.type,
            remediation.instance.id,
        )
    else:
        logger.info("No remediation needed, deployment is up to date")

    task = Task.create(
        type=TaskType(remediation.type.value) if remediation else TaskType.NOOP,
        deployment_id=deployment.id,
        prefect_flow_run_id=None,
    )

    logger.info(
        "Running apply_state workflow: task_id={} task_type={}",
        task.id,
        task.type,
    )
    flow_info = await prefect_manager.run_action(
        action=PrefectAction.APPLY_STATE,
        parameters={
            "deployment_id": deployment.id,
            "remediation": remediation,
            "task_id": task.id,
        },
    )
    task.prefect_flow_run_id = flow_info.id
    logger.info(
        "Apply state workflow started: task_id={} flow_run_id={}",
        task.id,
        flow_info.id,
    )

    return task
