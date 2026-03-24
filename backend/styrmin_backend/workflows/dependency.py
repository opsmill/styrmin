from fast_depends import Depends, inject

from styrmin_backend.services.workflow import StyrminWorkflowExecutor
from styrmin_backend.services.workflow.dependency import get_workflow_executor
from styrmin_backend.workflows.catalogue import PrefectCatalogue
from styrmin_backend.workflows.manager import PrefectManager


def get_catalogue() -> PrefectCatalogue:
    """Get the Prefect catalogue instance.

    This function is used as a dependency injector.
    """
    return PrefectCatalogue()


@inject
def get_manager(
    catalogue: PrefectCatalogue = Depends(get_catalogue),
    workflow_executor: StyrminWorkflowExecutor = Depends(get_workflow_executor),
) -> PrefectManager:
    """Get the Prefect manager instance.

    This function is used as a dependency injector.
    """
    return PrefectManager(catalogue=catalogue, workflow_executor=workflow_executor)
