from fast_depends import Depends, inject

from styrmin_backend.services.workflow import StyrminWorkflowExecutor
from styrmin_backend.services.workflow.dependency import get_workflow_executor


@inject
async def init_workflow_executor(
    workflow_executor: StyrminWorkflowExecutor = Depends(get_workflow_executor),
) -> None:
    await workflow_executor.initialize()
