import os
import subprocess
import uuid
from pathlib import Path
from typing import AsyncGenerator

import pytest
import yaml
from kubernetes_asyncio import client as kubeclient
from kubernetes_asyncio import config as kubeconfig
from pytest_asyncio import is_async_test
from testcontainers.core.container import DockerContainer

from styrmin_backend import config
from styrmin_backend.workflows.catalogue import PrefectCatalogue
from tests.helpers.utils import (
    get_exposed_port,
    get_kubernetes_cluster_role_binding_from_path,
    get_kubernetes_deployment_from_path,
    get_kubernetes_service_account_from_path,
    get_kubernetes_service_from_path,
    wait_for_http_code,
)


async def load_crds_from_path(kubernetes: kubeclient.ApiClient, path: Path):
    loaded_crd = 0

    for entry in Path(path).iterdir():
        with Path.open(entry) as file:
            crds = kubeclient.ApiextensionsV1Api(kubernetes)

            await crds.create_custom_resource_definition(body=yaml.safe_load(file))
            loaded_crd += 1

    res: kubeclient.V1CustomResourceDefinitionList = (
        await crds.list_custom_resource_definition()
    )
    assert len(res.items) == loaded_crd


async def load_controllers(
    kubernetes: kubeclient.ApiClient, namespace: str, path: Path
):
    """Create Helm-controller and source-controller deployments."""
    # Create service account
    core_v1_api = kubeclient.CoreV1Api(kubernetes)
    await core_v1_api.create_namespaced_service_account(
        namespace=namespace,
        body=get_kubernetes_service_account_from_path(
            path=path / "serviceaccount.yaml"
        ),
    )

    rbac_api = kubeclient.RbacAuthorizationV1Api(kubernetes)
    await rbac_api.create_cluster_role_binding(
        body=get_kubernetes_cluster_role_binding_from_path(
            path=path / "clusterrolebinding.yaml"
        )
    )

    # Create service
    await core_v1_api.create_namespaced_service(
        namespace=namespace,
        body=get_kubernetes_service_from_path(
            path=path / "source-controller" / "service.yaml"
        ),
    )
    service = await core_v1_api.read_namespaced_service(
        namespace=namespace, name="source-controller"
    )
    assert service is not None

    apps_v1_api = kubeclient.AppsV1Api(kubernetes)

    await apps_v1_api.create_namespaced_deployment(
        namespace=namespace,
        body=get_kubernetes_deployment_from_path(
            path=path / "helm-controller" / "deployment.yaml"
        ),
    )

    await apps_v1_api.create_namespaced_deployment(
        namespace=namespace,
        body=get_kubernetes_deployment_from_path(
            path=path / "source-controller" / "deployment.yaml"
        ),
    )

    deployments = await apps_v1_api.list_namespaced_deployment(namespace=namespace)
    assert len(deployments.items) == 2


@pytest.fixture(scope="session")
async def fake_kubernetes(
    request: pytest.FixtureRequest,
) -> AsyncGenerator[kubeclient.ApiClient, None]:
    container = DockerContainer(
        image="registry.k8s.io/kwok/cluster:v0.4.0-k8s.v1.28.0"
    ).with_exposed_ports(8080)

    container.start()
    request.addfinalizer(container.stop)
    wait_for_http_code(container=container, status_code=200, port=8080, path="/")

    configuration = kubeclient.Configuration(
        host=f"http://localhost:{get_exposed_port(container, 8080)}"
    )
    async with kubeclient.ApiClient(configuration) as api:
        await load_crds_from_path(
            kubernetes=api,
            path=Path(__file__).parent.resolve() / "integration" / "fixtures" / "crds",
        )

        yield api


@pytest.fixture(scope="session")
async def vcluster(
    request: pytest.FixtureRequest, tmp_path_factory
) -> AsyncGenerator[dict, None]:
    """Create a vCluster (vind) cluster and yield connection details."""
    kubeconfig_path = str(tmp_path_factory.mktemp("vcluster") / "kubeconfig")
    cluster_name = f"pytest-{uuid.uuid4()}"

    vcluster_dir = os.environ.get("VCLUSTER_DIR")

    def teardown():
        delete_cmd = ["vcluster", "delete", cluster_name, "--driver=docker"]
        if vcluster_dir:
            delete_cmd.extend(["--config", vcluster_dir])
        subprocess.run(delete_cmd, check=True)

    request.addfinalizer(teardown)

    create_cmd = [
        "vcluster",
        "create",
        cluster_name,
        "--connect=false",
        "--driver=docker",
    ]

    if vcluster_dir:
        create_cmd.extend(["--config", vcluster_dir])
    subprocess.run(create_cmd, check=True)

    # Export kubeconfig from vcluster
    connect_cmd = ["vcluster", "connect", cluster_name, "--print", "--driver=docker"]
    if vcluster_dir:
        connect_cmd.extend(["--config", vcluster_dir])
    result = subprocess.run(
        connect_cmd,
        capture_output=True,
        text=True,
        check=True,
    )
    Path(kubeconfig_path).write_text(result.stdout)

    await kubeconfig.load_kube_config(config_file=kubeconfig_path)
    async with kubeclient.ApiClient() as api:
        yield {
            "api": api,
            "cluster_name": cluster_name,
            "kubeconfig_path": kubeconfig_path,
        }


@pytest.fixture(scope="session")
async def real_kubernetes(
    vcluster: dict,
) -> AsyncGenerator[kubeclient.ApiClient, None]:
    api: kubeclient.ApiClient = vcluster["api"]

    await load_crds_from_path(
        kubernetes=api,
        path=Path(__file__).parent.resolve() / "integration" / "fixtures" / "crds",
    )

    core_api = kubeclient.CoreV1Api(api)
    await core_api.create_namespace(
        body=kubeclient.V1Namespace(metadata=kubeclient.V1ObjectMeta(name="styrmin"))
    )

    await load_controllers(
        kubernetes=api,
        namespace="styrmin",
        path=Path(__file__).parent.resolve() / "integration" / "fixtures" / "templates",
    )

    yield api


def pytest_collection_modifyitems(items):
    pytest_asyncio_tests = (item for item in items if is_async_test(item))
    session_scope_marker = pytest.mark.asyncio(loop_scope="session")
    for async_test in pytest_asyncio_tests:
        async_test.add_marker(session_scope_marker, append=False)


@pytest.fixture(autouse=True, scope="session")
def load_styrmin_config():
    config.SETTINGS.initialize_and_exit()


@pytest.fixture(autouse=True, scope="session")
def load_workflow_catalogue(load_styrmin_config):
    PrefectCatalogue()

    return PrefectCatalogue
