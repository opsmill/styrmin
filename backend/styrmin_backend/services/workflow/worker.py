from __future__ import annotations

from typing import TYPE_CHECKING, Any, overload
from uuid import UUID

from prefect.client.schemas.objects import StateType
from prefect.deployments.flow_runs import arun_deployment
from prefect.exceptions import MissingResult
from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.workflows.models import WorkflowDefinition, WorkflowInfo

from . import StyrminWorkflowExecutor, Return

if TYPE_CHECKING:
    from prefect.client.schemas.objects import FlowRun


class WorkflowWorkerExecutor(StyrminWorkflowExecutor):
    async def initialize(self) -> None:
        """Initialize the Workflow engine"""

    @overload
    async def execute_workflow(
        self,
        workflow: WorkflowDefinition,
        expected_return: type[Return],
        parameters: dict[str, Any] | None = ...,
        tags: list[str] | None = ...,
        context: GlobalContext | None = ...,
    ) -> Return: ...

    @overload
    async def execute_workflow(
        self,
        workflow: WorkflowDefinition,
        expected_return: None = ...,
        parameters: dict[str, Any] | None = ...,
        tags: list[str] | None = ...,
        context: GlobalContext | None = ...,
    ) -> Any: ...

    async def execute_workflow(
        self,
        workflow: WorkflowDefinition,
        expected_return: type[Return] | None = None,
        parameters: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        context: GlobalContext | None = None,
    ) -> Any:
        response: FlowRun = await arun_deployment(
            name=workflow.full_name,
            poll_interval=1,
            parameters=parameters or {},
            tags=tags,
        )  # type: ignore[return-value, misc]

        if not response.state:
            raise RuntimeError("Unable to read state from the response")

        if response.state.type == StateType.CRASHED:
            raise RuntimeError(response.state.message)

        try:
            return await response.state.result(raise_on_failure=True)  # type: ignore[call-overload]
        except MissingResult:
            if response.state.is_failed():
                raise RuntimeError(f"Workflow failed: {response.state.message}")
            return None

    async def submit_workflow(
        self,
        workflow: WorkflowDefinition,
        parameters: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> WorkflowInfo:
        flow_run = await arun_deployment(
            name=workflow.full_name,
            timeout=0,
            parameters=parameters or {},
            tags=tags,
        )  # type: ignore[return-value, misc]
        return WorkflowInfo.from_flow(flow_run=flow_run)

    async def submit_workflow_uuid(  # type: ignore[override]
        self,
        workflow_uuid: UUID,
        parameters: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> WorkflowInfo:
        flow_run = await arun_deployment(
            name=workflow_uuid,
            timeout=0,
            parameters=parameters or {},
            tags=tags,
        )
        return WorkflowInfo.from_flow(flow_run=flow_run)
