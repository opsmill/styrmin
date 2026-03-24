from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import yaml
from fast_depends import dependency_provider
from prefect.testing.utilities import prefect_test_harness

from styrmin_backend.agent.service.kubernetes.dependency import get_api_client
from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterConfig,
    EnvironmentConfig,
    GlobalContext,
    ResolvedConfig,
)
from styrmin_backend.db.models import HelmChart, HelmRepository
from styrmin_backend.services.helm.renderer import (
    render_helm_chart_spec,
    # render_helm_release_spec,
    render_helm_repository_spec,
)
from styrmin_backend.services.workflow import StyrminWorkflowExecutor
from styrmin_backend.services.workflow.local import WorkflowLocalExecutor
from styrmin_backend.workflows.catalogue import PrefectCatalogue
from styrmin_backend.workflows.models import LocalSourceWorkflowDefinition


@pytest.fixture(autouse=True)
async def prefect_server():
    with prefect_test_harness():
        yield


@pytest.fixture
def workflow_executor() -> StyrminWorkflowExecutor:
    return WorkflowLocalExecutor()


@pytest.fixture
def instantiate_application_workflow_definition() -> LocalSourceWorkflowDefinition:
    return PrefectCatalogue.INSTANTIATE_APPLICATION  # type: ignore[attr-defined]


@pytest.fixture
def chart_values() -> dict:
    with open(Path(__file__).parent / "fixtures" / "chart_values.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture
def test_helm_repository() -> HelmRepository:
    return HelmRepository(id=uuid4(), url="oci://charts.example.com/test")


@pytest.fixture
def test_helm_chart(test_helm_repository: HelmRepository) -> HelmChart:
    return HelmChart(
        id=uuid4(),
        name="infrahub",
        version="4.1.4",
        repository_id=test_helm_repository.id,
    )


@pytest.fixture
def helm_chart_spec(test_helm_chart) -> dict:
    return render_helm_chart_spec(test_helm_chart)  # type: ignore[call-arg]


@pytest.fixture
def fixture_helm_repository_spec(
    test_helm_repository: HelmRepository,
) -> dict[str, Any]:  # type: ignore[name-defined]
    return render_helm_repository_spec(test_helm_repository)  # type: ignore[arg-type, call-arg]


@pytest.fixture
def runtime_context():
    return GlobalContext(
        cluster=ClusterConfig(
            ingress_class="nginx",
            runtime_class="k8s",
            node_selector="node-type=worker",
            dedicated_ingress="true",
        ),
        environment=EnvironmentConfig(
            ip_whitelist=["10.0.0.0/8"],
            db_size="1Gi",
        ),
        instance=ResolvedConfig(
            ip_whitelist=["10.0.0.0/8"],
            ingress_class="nginx",
            db_size="1Gi",
            runtime_class="k8s",
            node_selector="node-type=worker",
            dedicated_ingress="true",
        ),
        app=ApplicationContext(
            name="myapp",
            version="1.0.0",
        ),
    )


@pytest.fixture
async def use_real_kubernetes(real_kubernetes):
    async def get_test_api_client():
        yield real_kubernetes

    dependency_provider.dependency_overrides[get_api_client] = get_test_api_client
    yield
    dependency_provider.dependency_overrides.clear()


# @pytest.mark.usefixtures("use_real_kubernetes", "load_styrmin_config")
# async def test_instantiate_application_workflow(
#     workflow_executor: StyrminWorkflowExecutor,
#     instantiate_application_workflow_definition: LocalSourceWorkflowDefinition,
#     test_helm_chart: HelmChart,
#     chart_values: dict,
#     helm_chart_spec: dict,
#     helm_repo_spec: dict,
#     runtime_context: GlobalContext,
#     real_kubernetes: kubeclient.ApiClient,
# ):
#     instance_id: UUID = uuid4()
#     namespace = get_kubernetes_reference(instance_id)
#     kwargs = {
#         "namespace": namespace,
#         "release_spec": render_helm_release_spec(
#             helm_chart=test_helm_chart,
#             instance_id=instance_id,
#             chart_values=chart_values,
#         ),
#         "helm_repositories": [helm_repo_spec],
#         "charts": [helm_chart_spec],
#     }

#     await workflow_executor.submit_workflow(
#         workflow=instantiate_application_workflow_definition,
#         context=runtime_context,
#         parameters=kwargs,
#         tags=None,
#     )

#     core_api = kubeclient.CoreV1Api(real_kubernetes)
#     pods = await core_api.list_namespaced_pod(namespace=namespace)

#     assert any("infrahub" in pod.metadata.name for pod in pods.items)

#     endpoints: V1Endpoints = await core_api.read_namespaced_endpoints(
#         namespace=namespace,
#         name="cloud-infrahub-server",
#     )
#     assert len(endpoints.subsets) > 0
#     assert any(
#         "infrahub" in subset.addresses[0].target_ref.name
#         for subset in endpoints.subsets
#     )
