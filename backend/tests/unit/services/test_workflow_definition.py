from uuid import uuid4

import pytest

from styrmin_backend import config
from styrmin_backend.context.models.config import (
    ClusterConfig,
    DedicatedIngressConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
)
from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterContext,
    DeploymentContext,
    EnvironmentContext,
    GlobalContext,
    InstanceContext,
)
from styrmin_backend.context.models.helm import ChartInfo, HelmInfo, RepositoryInfo
from styrmin_backend.services.workflow.local import WorkflowLocalExecutor
from styrmin_backend.workflows.constants import WorkflowType
from styrmin_backend.workflows.models import GitSourceWorkflowDefinition


@pytest.fixture
def git_workflow_definition():
    return GitSourceWorkflowDefinition(
        name="remote_application_execution",
        type=WorkflowType.INTERNAL,
        module="tests.unit.services.test_workflow_definition",
        function="git_sourced_function",
        repository=config.SETTINGS.agent_code.repository,
        branch=config.SETTINGS.agent_code.branch,
        token=config.SETTINGS.agent_code.token,
        namespace="test",
    )


# TODO: Relocate this fixture
@pytest.fixture
def runtime_context():
    cluster_config = ClusterConfig(
        ingress_class="nginx",
        runtime_class="k8s",
        node_selector="node-type=worker",
        dedicated_ingress=DedicatedIngressConfig(),
    )
    environment_config = EnvironmentConfig(
        ip_whitelist=["10.0.0.0/8"],
        db_size="1Gi",
    )
    deployment_config = DeploymentConfig()
    resolved_config = ResolvedConfig(
        ip_whitelist=["10.0.0.0/8"],
        ingress_class="nginx",
        db_size="1Gi",
        runtime_class="k8s",
        node_selector="node-type=worker",
        dedicated_ingress=DedicatedIngressConfig(),
    )
    helm_info = HelmInfo(
        chart=ChartInfo(
            id=uuid4(),
            name="myapp-chart",
            version="1.0.0",
            values_template="",
        ),
        repository=RepositoryInfo(
            id=uuid4(),
            url="https://charts.example.com",
        ),
    )
    return GlobalContext(
        cluster=ClusterContext(config=cluster_config),
        environment=EnvironmentContext(name="test", config=environment_config),
        deployment=DeploymentContext(config=deployment_config),
        instance=InstanceContext(
            config=resolved_config,
            deployment_id=uuid4(),
            namespace="default",
            release_reference="myapp-release",
        ),
        app=ApplicationContext(
            name="myapp",
            version="1.0.0",
            helm=helm_info,
        ),
    )


async def git_sourced_function(context: GlobalContext):
    """A dummy function to be executed by the workflow executor, sourced from this very repository."""
    return isinstance(context, GlobalContext)


async def test_git_application_instantiation_workflow(
    git_workflow_definition, runtime_context, mocker
):
    # Mock get_function to avoid actual git clone operations
    mocker.patch.object(
        GitSourceWorkflowDefinition,
        "get_function",
        return_value=git_sourced_function,
    )

    executor = WorkflowLocalExecutor()
    result = await executor.execute_workflow(
        workflow=git_workflow_definition,
        context=runtime_context,
    )
    assert result is True
