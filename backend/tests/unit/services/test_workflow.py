import pytest

from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.services.workflow import RESERVED_CONTEXT_PARAMETER_NAME
from styrmin_backend.services.workflow.exceptions import (
    ContextInCallParametersError,
    ContextRedefinitionError,
)
from styrmin_backend.services.workflow.local import WorkflowLocalExecutor
from styrmin_backend.workflows.models import (
    LocalSourceWorkflowDefinition,
)


async def workflow_function_without_context():
    return "execution successful"


async def workflow_function_without_context_with_parameters(key: str):
    assert key == "value"
    return "execution successful"


async def workflow_function_with_context(context: GlobalContext):
    return context


async def workflow_function_context_redefinition(context: str):
    return context


async def workflow_function_with_context_and_parameters(
    key: str, context: GlobalContext
):
    assert key == "value"
    return context


@pytest.fixture
def workflow_definition_without_context():
    definition = LocalSourceWorkflowDefinition(
        name="test_workflow",
        module="services.test_workflow",
        function="workflow_function_without_context",
    )
    definition.validate_workflow()
    yield definition


@pytest.fixture
def workflow_definition_with_context():
    definition = LocalSourceWorkflowDefinition(
        name="test_workflow",
        module="services.test_workflow",
        function="workflow_function_with_context",
    )
    definition.validate_workflow()
    yield definition


@pytest.fixture
def workflow_definition_with_context_and_parameters():
    definition = LocalSourceWorkflowDefinition(
        name="test_workflow",
        module="services.test_workflow",
        function="workflow_function_with_context_and_parameters",
    )
    definition.validate_workflow()
    yield definition


@pytest.fixture
def workflow_definition_without_context_with_parameters():
    definition = LocalSourceWorkflowDefinition(
        name="test_workflow",
        module="services.test_workflow",
        function="workflow_function_without_context_with_parameters",
    )
    definition.validate_workflow()
    yield definition


@pytest.fixture
def workflow_definition_context_redefinition():
    definition = LocalSourceWorkflowDefinition(
        name="test_workflow",
        module="services.test_workflow",
        function="workflow_function_context_redefinition",
    )
    definition.validate_workflow()
    yield definition


async def test_workflow_function_execution_without_context_and_no_parameters(
    workflow_definition_without_context, mocker
):
    executor = WorkflowLocalExecutor()
    context = mocker.Mock(spec=GlobalContext)

    result = await executor.execute_workflow(
        workflow=workflow_definition_without_context, context=context
    )
    assert result == "execution successful"


async def test_workflow_function_execution_with_context_and_no_parameters(
    workflow_definition_with_context, mocker
):
    executor = WorkflowLocalExecutor()
    context = mocker.Mock(spec=GlobalContext)

    returned_context = await executor.execute_workflow(
        workflow=workflow_definition_with_context, context=context
    )
    assert returned_context is context


async def test_workflow_function_execution_with_context_and_parameters(
    workflow_definition_with_context_and_parameters, mocker
):
    executor = WorkflowLocalExecutor()
    context = mocker.Mock(spec=GlobalContext)
    parameters = {"key": "value"}

    returned_context = await executor.execute_workflow(
        workflow=workflow_definition_with_context_and_parameters,
        context=context,
        parameters=parameters,
    )
    assert returned_context is context


async def test_workflow_function_execution_without_context_with_parameters(
    workflow_definition_without_context_with_parameters, mocker
):
    executor = WorkflowLocalExecutor()
    context = mocker.Mock(spec=GlobalContext)
    parameters = {"key": "value"}

    result = await executor.execute_workflow(
        workflow=workflow_definition_without_context_with_parameters,
        context=context,
        parameters=parameters,
    )
    assert result == "execution successful"


async def test_context_in_arguments_fails(workflow_definition_with_context, mocker):
    executor = WorkflowLocalExecutor()
    context = mocker.Mock(spec=GlobalContext)
    with pytest.raises(
        ContextInCallParametersError,
        match=f"`{RESERVED_CONTEXT_PARAMETER_NAME}` reserved parameter is not allowed in workflow function parameters",
    ):
        await executor.execute_workflow(
            workflow=workflow_definition_with_context,
            context=context,
            parameters={"context": context},
        )


async def test_context_redefinition_fails(
    workflow_definition_context_redefinition, mocker
):
    executor = WorkflowLocalExecutor()
    context = mocker.Mock(spec=GlobalContext)
    with pytest.raises(
        ContextRedefinitionError,
        match=f"`{RESERVED_CONTEXT_PARAMETER_NAME}` reserved parameter should be of type `GlobalContext`",
    ):
        await executor.execute_workflow(
            workflow=workflow_definition_context_redefinition,
            context=context,
        )
