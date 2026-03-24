from __future__ import annotations

from inspect import Parameter, signature
from typing import TYPE_CHECKING, Any, Callable, ParamSpec, TypeVar, overload

from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.services.workflow.exceptions import (
    ContextInCallParametersError,
    ContextRedefinitionError,
)
from styrmin_backend.workflows.models import (
    GitSourceWorkflowDefinition,
    LocalSourceWorkflowDefinition,
)

if TYPE_CHECKING:
    from styrmin_backend.workflows.models import (
        WorkflowInfo,
    )

Return = TypeVar("Return")
Params = ParamSpec("Params")

FuncType = Callable[Params, Return]


RESERVED_CONTEXT_PARAMETER_NAME: str = "context"


class StyrminWorkflowExecutor:
    async def initialize(self) -> None:
        """Initialize the Workflow engine

        Kept here just in case.
        """

    def _inject_context(
        self, function: Callable, parameters: dict[str, Any], context: GlobalContext
    ) -> dict[str, Any]:
        """Inject the computed context into the workflow function parameters.

        This is required to make the context available in workflow functions.

        Raises:
            ValueError: If the context parameter is defined and not of type `GlobalContext` in the function signature
            ValueError: If the context parameter is given in the arguments to be used at runtime.
        """

        if RESERVED_CONTEXT_PARAMETER_NAME in parameters:
            raise ContextInCallParametersError(
                f"`{RESERVED_CONTEXT_PARAMETER_NAME}` reserved parameter is not allowed in workflow function parameters"
            )

        # Get the function signature
        function_signature = signature(function)
        function_parameters = function_signature.parameters

        context_parameter: Parameter | None = function_parameters.get(
            RESERVED_CONTEXT_PARAMETER_NAME
        )
        if context_parameter is not None:
            # Inject the context in function call parameters if the function uses a context with a compatible annotated type
            if (
                context_parameter.annotation is GlobalContext
                or context_parameter.annotation is Parameter.empty
            ):
                parameters[RESERVED_CONTEXT_PARAMETER_NAME] = context
            else:
                raise ContextRedefinitionError(
                    f"`{RESERVED_CONTEXT_PARAMETER_NAME}` reserved parameter should be of type `GlobalContext`"
                )

        return parameters

    @overload
    async def execute_workflow(
        self,
        workflow: LocalSourceWorkflowDefinition,
        expected_return: type[Return],
        parameters: dict[str, Any] | None = ...,
        tags: list[str] | None = ...,
        context: GlobalContext | None = ...,
    ) -> Return: ...

    @overload
    async def execute_workflow(
        self,
        workflow: LocalSourceWorkflowDefinition,
        expected_return: None = ...,
        parameters: dict[str, Any] | None = ...,
        tags: list[str] | None = ...,
        context: GlobalContext | None = ...,
    ) -> Any: ...

    async def execute_workflow(
        self,
        workflow: LocalSourceWorkflowDefinition,
        expected_return: type[Return] | None = None,
        parameters: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        context: GlobalContext | None = None,
    ) -> Any:
        raise NotImplementedError(
            "InfrahubWorkflow.execute_workflow is an abstract method"
        )

    async def submit_workflow(
        self,
        workflow: LocalSourceWorkflowDefinition,
        parameters: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> WorkflowInfo:
        raise NotImplementedError(
            "InfrahubWorkflow.submit_workflow is an abstract method"
        )

    async def submit_workflow_uuid(
        self,
        workflow_uuid: GitSourceWorkflowDefinition,
        parameters: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> WorkflowInfo:
        raise NotImplementedError(
            "InfrahubWorkflow.submit_workflow_uuid is an abstract method"
        )
