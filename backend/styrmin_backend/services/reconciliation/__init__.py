from uuid import UUID

from fast_depends import Depends, inject
from loguru import logger

from styrmin_backend.domain.models import (
    Deployment,
    Instance,
    Task,
    TaskType,
)
from styrmin_backend.domain.utils import generate_instance_name
from styrmin_backend.services.context import generate_context_from_deployment
from styrmin_backend.services.exceptions import InstanceNameUnavailableError
from styrmin_backend.services.unit_of_work import UnitOfWork
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.manager import PrefectManager
from styrmin_backend.workflows.models import PrefectAction


# Instance names must be unique across all deployments, and a two-word name has
# about 370,000 values, so one random draw can hit a name already in use (#499).
_INSTANCE_NAME_CANDIDATES = 10


async def _pick_instance_name(uow: UnitOfWork) -> str:
    """Return a generated instance name that no stored instance has."""
    candidates = [generate_instance_name() for _ in range(_INSTANCE_NAME_CANDIDATES)]
    used = await uow.application_instances.find_used_names(candidates)
    for name in candidates:
        if name not in used:
            return name
    raise InstanceNameUnavailableError()


async def generate_instance_from_deployment(
    deployment: Deployment,
    uow: UnitOfWork,
    release_reference: str | None = None,
) -> Instance:
    """Generate an instance from a deployment.

    ``release_reference`` is forwarded to
    :func:`~styrmin_backend.services.context.generate_context_from_deployment`;
    only an environment clone's counterpart passes it (it adopts the source
    deployment's Helm release name — 010 research D2).
    """
    context = await generate_context_from_deployment(
        deployment=deployment, uow=uow, release_reference=release_reference
    )

    instance = Instance.create(
        name=await _pick_instance_name(uow),
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
    task_type: TaskType = TaskType.NOOP,
    started_by_step_id: UUID | None = None,
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

    ``task_type`` is the operation the caller starts (019 research D19).
    The task records the new instance so operator reports find it (D4), and
    ``started_by_step_id``, the hook step that started it (D12). The caller
    checks that step with ``check_starting_step`` before it changes anything.

    The caller saves the deployment, and with it the new instance, before this
    call: the flow run starts here, and a database error raised after it does
    not stop the flow run (#499).
    """
    new_instance = deployment.active_instance
    assert new_instance is not None, "Deployment must have an active instance"

    task = Task.create(
        type=task_type,
        deployment_id=deployment.id,
        prefect_flow_run_id=None,
        instance_id=new_instance.id,
        started_by_step_id=started_by_step_id,
    )

    logger.info(
        "Scheduling apply_state flow: task_id={} task_type={} deployment_id={} "
        "current_instance_id={} new_instance_id={} started_by_step_id={}",
        task.id,
        task_type.value,
        deployment.id,
        current_instance.id if current_instance else None,
        new_instance.id,
        started_by_step_id,
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
