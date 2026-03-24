from styrmin_backend.services.workflow import StyrminWorkflowExecutor

from styrmin_backend.services.workflow.worker import WorkflowWorkerExecutor


def get_workflow_executor() -> StyrminWorkflowExecutor:
    return WorkflowWorkerExecutor()
