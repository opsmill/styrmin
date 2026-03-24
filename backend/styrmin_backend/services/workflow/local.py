from typing import Any

from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.workflows.models import (
    WorkflowDefinition,
    WorkflowInfo,
)

from . import StyrminWorkflowExecutor, Return


class WorkflowLocalExecutor(StyrminWorkflowExecutor):
    async def execute_workflow(
        self,
        workflow: WorkflowDefinition,
        expected_return: type[Return] | None = None,
        parameters: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        context: GlobalContext | None = None,
    ) -> Any:
        fn = workflow.get_function()
        parameters = parameters or {}
        if context is not None:
            parameters = self._inject_context(fn, parameters, context)
        return await fn(**parameters)

    async def submit_workflow(
        self,
        workflow: WorkflowDefinition,
        parameters: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> WorkflowInfo:
        return await self.execute_workflow(
            workflow=workflow,
            parameters=parameters,
        )

    async def submit_workflow_uuid(
        self,
        workflow_uuid: WorkflowDefinition,
        parameters: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> WorkflowInfo:
        raise NotImplementedError(
            "WorkflowLocalExecutor.submit_workflow_uuid is not implemented"
        )
