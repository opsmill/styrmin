import asyncio
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import AsyncGenerator

from dulwich import porcelain

import httpx
import kr8s.asyncio
import pytest
import yaml
from styrmin_sdk import StyrminClient
from kr8s.asyncio.objects import Service as AsyncService
from kubernetes_asyncio import client as kubeclient

PROJECT_ROOT = Path(__file__).parent.resolve().parents[2]
FIXTURES_DIR = Path(__file__).parent.resolve() / "fixtures"


# ---------------------------------------------------------------------------
# Hook + fixture: dump k8s logs on test failure
# ---------------------------------------------------------------------------
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)


def _dump_namespace_logs(kubeconfig: str, namespace: str) -> None:
    """Print pod statuses and container logs for a single namespace."""
    # List pods
    result = subprocess.run(
        [
            "kubectl",
            "--kubeconfig",
            kubeconfig,
            "get",
            "pods",
            "-n",
            namespace,
            "-o",
            "wide",
        ],
        capture_output=True,
        text=True,
    )
    print(f"\n{'=' * 60}")
    print(f"Pods in namespace '{namespace}'")
    print(f"{'=' * 60}")
    print(result.stdout or "(no output)")

    # List additional resources useful for debugging
    for resource in [
        "services",
        "backups.velero.io",
        "restores.velero.io",
        "backupstoragelocations.velero.io",
    ]:
        res_result = subprocess.run(
            [
                "kubectl",
                "--kubeconfig",
                kubeconfig,
                "get",
                resource,
                "-n",
                namespace,
                "-o",
                "wide",
            ],
            capture_output=True,
            text=True,
        )
        print(f"\n{'=' * 60}")
        print(f"{resource} in namespace '{namespace}'")
        print(f"{'=' * 60}")
        print(res_result.stdout or "(no output)")

    # Get pod names
    pod_result = subprocess.run(
        [
            "kubectl",
            "--kubeconfig",
            kubeconfig,
            "get",
            "pods",
            "-n",
            namespace,
            "-o",
            "name",
        ],
        capture_output=True,
        text=True,
    )
    pods = [
        line.strip() for line in pod_result.stdout.strip().splitlines() if line.strip()
    ]

    for pod in pods:
        print(f"\n{'=' * 60}")
        print(f"Logs: {namespace}/{pod}")
        print(f"{'=' * 60}")
        log_result = subprocess.run(
            [
                "kubectl",
                "--kubeconfig",
                kubeconfig,
                "logs",
                pod,
                "-n",
                namespace,
                "--all-containers",
                "--tail=200",
            ],
            capture_output=True,
            text=True,
        )
        print(log_result.stdout or "(no logs)")
        if log_result.stderr:
            print(f"(stderr) {log_result.stderr}")


@pytest.fixture(autouse=True)
def _dump_k8s_logs_on_failure(request, vcluster):
    yield
    rep_setup = getattr(request.node, "rep_setup", None)
    rep_call = getattr(request.node, "rep_call", None)
    setup_failed = rep_setup is not None and rep_setup.failed
    call_failed = rep_call is not None and rep_call.failed
    if not setup_failed and not call_failed:
        return

    kubeconfig = vcluster["kubeconfig_path"]

    # Discover all namespaces starting with "styrmin"
    ns_result = subprocess.run(
        ["kubectl", "--kubeconfig", kubeconfig, "get", "namespaces", "-o", "name"],
        capture_output=True,
        text=True,
    )
    namespaces = [
        line.strip().removeprefix("namespace/")
        for line in ns_result.stdout.strip().splitlines()
        if line.strip().startswith("namespace/styrmin")
    ]

    for namespace in sorted(namespaces):
        _dump_namespace_logs(kubeconfig, namespace)


async def _wait_for_deployment_running(
    client: StyrminClient,
    deployment_id,
    timeout: float = 300.0,
    interval: float = 10.0,
):
    """Poll until a deployment reaches 'running' status.

    Returns the deployment object on success.
    Raises TimeoutError if the deployment doesn't reach 'running' within the timeout.
    """
    from styrmin_sdk.exceptions import StyrminError

    deadline = time.time() + timeout
    deployment = None
    while time.time() < deadline:
        try:
            deployment = await client.deployments.get(deployment_id)
            if deployment.status == "running":
                return deployment
        except StyrminError:
            pass
        await asyncio.sleep(interval)
    status = deployment.status if deployment else "unknown"
    msg = f"Deployment {deployment_id} did not reach 'running' after {timeout}s (status: {status})"
    raise TimeoutError(msg)


async def _wait_for_service_ready(
    core_api: kubeclient.CoreV1Api,
    *,
    name: str,
    namespace: str = "default",
    label_selector: str,
    pod_timeout: float = 120.0,
    endpoint_timeout: float = 60.0,
) -> None:
    """Wait for pods matching *label_selector* to be ready and *name* service to have endpoints."""
    deadline = time.time() + pod_timeout
    while time.time() < deadline:
        pods = await core_api.list_namespaced_pod(
            namespace=namespace, label_selector=label_selector
        )
        if pods.items and all(
            c.ready
            for pod in pods.items
            if pod.status and pod.status.container_statuses
            for c in pod.status.container_statuses
        ):
            break
        await asyncio.sleep(2)
    else:
        msg = f"pods matching '{label_selector}' in {namespace} did not become ready"
        raise TimeoutError(msg)

    deadline = time.time() + endpoint_timeout
    while time.time() < deadline:
        endpoints = await core_api.read_namespaced_endpoints(
            name=name, namespace=namespace
        )
        if endpoints.subsets and any(subset.addresses for subset in endpoints.subsets):
            break
        await asyncio.sleep(2)
    else:
        msg = f"service {name} in {namespace} has no ready endpoints"
        raise TimeoutError(msg)


async def _wait_for_http(
    url: str,
    timeout: float = 120.0,
    interval: float = 2.0,
    expected_status: int = 200,
    headers: dict[str, str] | None = None,
) -> None:
    start = time.time()
    async with httpx.AsyncClient() as client:
        while time.time() - start < timeout:
            try:
                resp = await client.get(url, timeout=5, headers=headers)
                if resp.status_code == expected_status:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(interval)
    msg = f"{url} did not return {expected_status} after {timeout}s"
    raise TimeoutError(msg)


# ---------------------------------------------------------------------------
# Fixture: chart_server
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def chart_server(
    vcluster: dict,
) -> AsyncGenerator[str, None]:
    """Build and deploy a Helm chart HTTP server in the vcluster.

    Packages the simple-app helm chart and serves it via HTTP with an
    ``index.yaml`` so that Flux CD can fetch it as a standard Helm repository.
    """
    kubeconfig_path = vcluster["kubeconfig_path"]
    api: kubeclient.ApiClient = vcluster["api"]

    # Build chart-server Docker image (context is PROJECT_ROOT for COPY paths)
    subprocess.run(
        [
            "docker",
            "build",
            "-t",
            "chart-server:latest",
            "-f",
            str(FIXTURES_DIR / "chart-server" / "Dockerfile"),
            str(PROJECT_ROOT),
        ],
        check=True,
    )

    # Deploy chart-server from manifest
    manifest_path = FIXTURES_DIR / "chart-server" / "deployment.yaml"
    with open(manifest_path) as f:
        docs = list(yaml.safe_load_all(f))

    apps_api = kubeclient.AppsV1Api(api)
    core_api = kubeclient.CoreV1Api(api)

    for doc in docs:
        if doc["kind"] == "Deployment":
            await apps_api.create_namespaced_deployment(namespace="default", body=doc)
        elif doc["kind"] == "Service":
            await core_api.create_namespaced_service(namespace="default", body=doc)

    await _wait_for_service_ready(
        core_api, name="chart-server", label_selector="app=chart-server"
    )

    # Port-forward chart-server service and verify index.yaml is accessible
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    service = await AsyncService.get("chart-server", namespace="default", api=kr8s_api)
    async with service.portforward(remote_port=8080, local_port="auto") as local_port:
        await _wait_for_http(f"http://localhost:{local_port}/index.yaml", timeout=60.0)

        # Yield cluster-internal chart server URL
        chart_server_url = "http://chart-server.default.svc.cluster.local:8080"
        yield chart_server_url


# ---------------------------------------------------------------------------
# Fixture: git_server
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def git_server(
    vcluster: dict,
    tmp_path_factory: pytest.TempPathFactory,
    chart_server: str,
) -> AsyncGenerator[dict[str, str], None]:
    kubeconfig_path = vcluster["kubeconfig_path"]
    api: kubeclient.ApiClient = vcluster["api"]

    # Build git-daemon Docker image
    subprocess.run(
        [
            "docker",
            "build",
            "-t",
            "git-daemon:latest",
            str(FIXTURES_DIR / "git-server"),
        ],
        check=True,
    )

    # Deploy git-daemon from manifest
    manifest_path = FIXTURES_DIR / "git-server" / "deployment.yaml"
    with open(manifest_path) as f:
        docs = list(yaml.safe_load_all(f))

    apps_api = kubeclient.AppsV1Api(api)
    core_api = kubeclient.CoreV1Api(api)

    for doc in docs:
        if doc["kind"] == "Deployment":
            await apps_api.create_namespaced_deployment(namespace="default", body=doc)
        elif doc["kind"] == "Service":
            await core_api.create_namespaced_service(namespace="default", body=doc)

    await _wait_for_service_ready(
        core_api, name="git-server", label_selector="app=git-server"
    )

    # Prepare driver repos for each example driver
    drivers: dict[str, dict[str, Path | str]] = {
        "simple-app": {
            "source": PROJECT_ROOT / "driver" / "examples" / "simple-app",
            "chart_name": "simple-app",
        },
        "db-test": {
            "source": PROJECT_ROOT / "driver" / "examples" / "db-test",
            "chart_name": "db-test",
        },
        "semaphore": {
            "source": PROJECT_ROOT / "driver" / "examples" / "semaphore",
        },
    }

    tmp_repo = tmp_path_factory.mktemp("driver-repo")
    repo_dirs: dict[str, str] = {}

    for name, info in drivers.items():
        dest = tmp_repo / name
        shutil.copytree(info["source"], dest, dirs_exist_ok=True)

        # Update driver.styrmin.yml to point to the chart server
        # (only for drivers that use an embedded chart)
        if "chart_name" in info:
            driver_yaml_path = dest / "driver.styrmin.yml"
            with open(driver_yaml_path) as f:
                driver_config = yaml.safe_load(f)
            driver_config["spec"]["helm"]["main"]["location"] = (
                f"{chart_server}/{info['chart_name']}"
            )
            with open(driver_yaml_path, "w") as f:
                yaml.dump(driver_config, f, default_flow_style=False)

        repo_dir = str(dest)
        porcelain.init(repo_dir)
        porcelain.add(
            repo_dir,
            paths=[
                str(p.relative_to(repo_dir))
                for p in Path(repo_dir).rglob("*")
                if p.is_file() and ".git" not in p.relative_to(repo_dir).parts
            ],
        )
        porcelain.commit(
            repo_dir,
            message=b"initial commit",
            author=b"test <test@test.com>",
            committer=b"test <test@test.com>",
        )
        repo_dirs[name] = repo_dir

    # Port-forward git-daemon service for git push
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    service = await AsyncService.get("git-server", namespace="default", api=kr8s_api)
    async with service.portforward(remote_port=9418, local_port="auto") as local_port:
        for name, repo_dir in repo_dirs.items():
            await asyncio.to_thread(
                porcelain.push,
                repo_dir,
                remote_location=f"git://localhost:{local_port}/{name}.git",
                refspecs=[b"HEAD:refs/heads/master"],
            )

        # Yield cluster-internal git URLs
        git_urls = {
            name: f"git://git-server.default.svc.cluster.local/{name}.git"
            for name in drivers
        }
        yield git_urls


# ---------------------------------------------------------------------------
# Fixture: styrmin_deployment
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def styrmin_deployment(
    vcluster: dict,
) -> AsyncGenerator[str, None]:
    kubeconfig_path = vcluster["kubeconfig_path"]
    api: kubeclient.ApiClient = vcluster["api"]

    # Build styrmin image via docker compose
    subprocess.run(
        ["docker", "compose", "build"],
        cwd=str(PROJECT_ROOT),
        check=True,
    )

    # Check for GITHUB_PAT
    github_pat = os.environ.get("GITHUB_PAT", "default")
    if not github_pat:
        pytest.skip("GITHUB_PAT environment variable not set")

    # Build agent chart dependencies (prefect-worker) before installing styrmin
    subprocess.run(
        ["helm", "dependency", "update", str(PROJECT_ROOT / "helm" / "agent")],
        check=True,
    )

    # Deploy MinIO for Velero backup storage (before Styrmin, since Velero needs it)
    minio_manifest_path = FIXTURES_DIR / "minio" / "deployment.yaml"
    with open(minio_manifest_path) as f:
        minio_docs = list(yaml.safe_load_all(f))

    apps_api = kubeclient.AppsV1Api(api)
    core_api = kubeclient.CoreV1Api(api)

    # Ensure styrmin namespace exists for MinIO
    try:
        await core_api.create_namespace(
            body=kubeclient.V1Namespace(
                metadata=kubeclient.V1ObjectMeta(name="styrmin")
            )
        )
    except Exception:
        pass  # namespace may already exist

    for doc in minio_docs:
        if doc["kind"] == "Deployment":
            await apps_api.create_namespaced_deployment(namespace="styrmin", body=doc)
        elif doc["kind"] == "Service":
            await core_api.create_namespaced_service(namespace="styrmin", body=doc)

    # Install styrmin via helm
    subprocess.run(
        [
            "helm",
            "upgrade",
            "--install",
            "styrmin",
            "--dependency-update",
            "--create-namespace",
            "-n",
            "styrmin",
            str(PROJECT_ROOT / "helm" / "styrmin"),
            "-f",
            str(FIXTURES_DIR / "styrmin-values.yaml"),
            "--set",
            f"styrmin.driver.token={github_pat}",
            "--set",
            f"styrmin.agentSource.token={github_pat}",
            "--kubeconfig",
            kubeconfig_path,
            "--wait",
            "--timeout",
            "5m",
        ],
        check=True,
    )

    # Port-forward styrmin server (must stay alive for tests)
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    service = await AsyncService.get(
        "styrmin-server", namespace="styrmin", api=kr8s_api
    )
    async with service.portforward(remote_port=8000, local_port="auto") as local_port:
        styrmin_url = f"http://localhost:{local_port}"

        # Wait for styrmin to be healthy
        await _wait_for_http(f"{styrmin_url}/health", timeout=120.0)

        yield styrmin_url


# ---------------------------------------------------------------------------
# Fixture: styrmin_resources
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def styrmin_resources(
    git_server: dict[str, str],
    styrmin_deployment: str,
) -> AsyncGenerator[dict, None]:
    styrmin_url = styrmin_deployment
    git_url = git_server["simple-app"]

    async with StyrminClient(server_address=styrmin_url) as client:
        # Create cluster
        cluster = await client.clusters.create(
            name="test-cluster",
            config={
                "fqdn_suffix": "styrmin.com",
                "ingress_class": "traefik",
                "dedicated_ingress": {
                    "implementation": "traefik",
                    "type": "ingress",
                    "service": {"type": "LoadBalancer"},
                },
                "runtime_class": "default",
                "standard_storage": {"storage_class": "local-path"},
            },
        )

        # Create environment
        environment = await client.environments.create(
            name="test-environment",
            cluster_id=cluster.id,
            config={
                "ip_whitelist": ["127.0.0.1"],
            },
        )

        # Create a backup storage location pointing at the test MinIO instance
        bsl = await client.backup_storage_locations.create(
            name="test-bsl",
            endpoint="http://minio.styrmin.svc:9000",
            bucket="velero",
            region="minio",
            access_key_id="minioadmin",
            secret_access_key="minioadmin",
        )

        # Assign BSL to the environment
        await client.backup_storage_locations.assign(environment.id, bsl.id)

        # Load application driver version from git server (implicitly creates the driver)
        driver_version = await client.drivers.load_version(git_url, "master")

        yield {
            "cluster_id": str(cluster.id),
            "environment_id": str(environment.id),
            "bsl_id": str(bsl.id),
            "bsl_name": bsl.name,
            "driver_id": str(driver_version.application_driver_id),
            "styrmin_url": styrmin_url,
            "client": client,
        }


# ---------------------------------------------------------------------------
# Fixture: simple_app_image
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def simple_app_image() -> str:
    # Build simple-app Docker image
    subprocess.run(
        [
            "docker",
            "build",
            "-t",
            "simple-app:0.1.0",
            "-f",
            str(
                PROJECT_ROOT
                / "driver"
                / "examples"
                / "simple-app"
                / "src"
                / "Dockerfile"
            ),
            str(PROJECT_ROOT / "driver" / "examples" / "simple-app" / "src"),
        ],
        check=True,
    )

    return "simple-app:0.1.0"


# ---------------------------------------------------------------------------
# Fixture: simple_app_image_v2
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def simple_app_image_v2() -> str:
    # Build simple-app Docker image for version 0.2.0
    subprocess.run(
        [
            "docker",
            "build",
            "-t",
            "simple-app:0.2.0",
            "--build-arg",
            "APP_VERSION=0.2.0",
            "-f",
            str(
                PROJECT_ROOT
                / "driver"
                / "examples"
                / "simple-app"
                / "src"
                / "Dockerfile"
            ),
            str(PROJECT_ROOT / "driver" / "examples" / "simple-app" / "src"),
        ],
        check=True,
    )

    return "simple-app:0.2.0"


# ---------------------------------------------------------------------------
# Fixture: velero_ready
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def velero_ready(
    styrmin_deployment: str,
    vcluster: dict,
) -> None:
    """Wait for Velero deployment + Node Agent DaemonSet to be ready."""
    api: kubeclient.ApiClient = vcluster["api"]
    core_api = kubeclient.CoreV1Api(api)

    # Wait for Velero server pod to be ready
    await _wait_for_service_ready(
        core_api,
        name="styrmin-velero",
        namespace="styrmin",
        label_selector="app.kubernetes.io/name=velero",
        pod_timeout=180.0,
        endpoint_timeout=60.0,
    )


# ---------------------------------------------------------------------------
# Fixture: deployed_simple_app
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def deployed_simple_app(
    styrmin_resources: dict,
    simple_app_image: str,
    vcluster: dict,
) -> dict:
    """Deploy simple-app and return deployment info for reuse by tests."""
    client = styrmin_resources["client"]
    environment_id = styrmin_resources["environment_id"]
    kubeconfig_path = vcluster["kubeconfig_path"]

    # Deploy the simple-app
    task = await client.deployments.create(
        driver="simple-app", version="0.1.0", environment_id=environment_id
    )
    deployment_id = task.deployment_id
    assert deployment_id is not None, "Task should have a deployment_id"

    deployment = await _wait_for_deployment_running(client, deployment_id)

    namespace = f"styrmin-{deployment_id}"

    # Get the instance_id from the deployment
    instance_id = None
    if deployment and deployment.application_instance:
        instance_id = str(deployment.application_instance.id)

    return {
        "deployment_id": str(deployment_id),
        "instance_id": instance_id,
        "namespace": namespace,
        "kubeconfig_path": kubeconfig_path,
    }


# ---------------------------------------------------------------------------
# Fixture: load_infrahub
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def load_infrahub(
    styrmin_resources: dict,
) -> AsyncGenerator[dict, None]:
    """Create an infrahub application driver and load its version from GitHub."""
    client: StyrminClient = styrmin_resources["client"]

    driver_version = await client.drivers.load_version(
        "https://github.com/opsmill/styrmin-mvp-driver", "develop"
    )

    yield {
        **styrmin_resources,
        "infrahub_driver_id": str(driver_version.application_driver_id),
    }


# ---------------------------------------------------------------------------
# Fixture: deployed_infrahub_app
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def deployed_infrahub_app(
    load_infrahub: dict,
    vcluster: dict,
) -> dict:
    """Deploy infrahub and return deployment info for reuse by tests."""
    client: StyrminClient = load_infrahub["client"]
    environment_id = load_infrahub["environment_id"]
    kubeconfig_path = vcluster["kubeconfig_path"]

    task = await client.deployments.create(
        driver="infrahub", version="1.6.0", environment_id=environment_id
    )
    deployment_id = task.deployment_id
    assert deployment_id is not None, "Task should have a deployment_id"

    # longer timeout for infrahub (many components)
    deployment = await _wait_for_deployment_running(
        client, deployment_id, timeout=600.0
    )

    namespace = f"styrmin-{deployment_id}"
    instance_id = None
    if deployment and deployment.application_instance:
        instance_id = str(deployment.application_instance.id)

    return {
        "deployment_id": str(deployment_id),
        "instance_id": instance_id,
        "namespace": namespace,
        "kubeconfig_path": kubeconfig_path,
    }


# ---------------------------------------------------------------------------
# Fixture: load_semaphore
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def load_semaphore(
    styrmin_resources: dict,
    git_server: dict[str, str],
) -> AsyncGenerator[dict, None]:
    """Load the Semaphore application driver from the git server."""
    client: StyrminClient = styrmin_resources["client"]
    git_url = git_server["semaphore"]

    driver_version = await client.drivers.load_version(git_url, "master")

    yield {
        **styrmin_resources,
        "semaphore_driver_id": str(driver_version.application_driver_id),
    }


# ---------------------------------------------------------------------------
# Fixture: deployed_semaphore
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def deployed_semaphore(
    load_semaphore: dict,
    vcluster: dict,
) -> dict:
    """Deploy Semaphore and return deployment info for reuse by tests."""
    client: StyrminClient = load_semaphore["client"]
    environment_id = load_semaphore["environment_id"]
    kubeconfig_path = vcluster["kubeconfig_path"]

    task = await client.deployments.create(
        name="semaphore",
        driver="semaphore",
        version="2.16.47",
        environment_id=environment_id,
    )
    deployment_id = task.deployment_id
    assert deployment_id is not None, "Task should have a deployment_id"

    deployment = await _wait_for_deployment_running(
        client, deployment_id, timeout=300.0
    )

    namespace = f"styrmin-{deployment_id}"
    instance_id = None
    if deployment and deployment.application_instance:
        instance_id = str(deployment.application_instance.id)

    return {
        "deployment_id": str(deployment_id),
        "instance_id": instance_id,
        "namespace": namespace,
        "kubeconfig_path": kubeconfig_path,
    }


# ---------------------------------------------------------------------------
# Fixture: db_test_image
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def db_test_image() -> str:
    # Build db-test Docker image
    subprocess.run(
        [
            "docker",
            "build",
            "-t",
            "db-test:0.1.0",
            "-f",
            str(
                PROJECT_ROOT / "driver" / "examples" / "db-test" / "src" / "Dockerfile"
            ),
            str(PROJECT_ROOT / "driver" / "examples" / "db-test" / "src"),
        ],
        check=True,
    )

    return "db-test:0.1.0"


# ---------------------------------------------------------------------------
# Fixture: load_db_test
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def load_db_test(
    styrmin_resources: dict,
    git_server: dict[str, str],
) -> AsyncGenerator[dict, None]:
    """Load the db-test application driver from the git server."""
    client: StyrminClient = styrmin_resources["client"]
    git_url = git_server["db-test"]

    driver_version = await client.drivers.load_version(git_url, "master")

    yield {
        **styrmin_resources,
        "db_test_driver_id": str(driver_version.application_driver_id),
    }


# ---------------------------------------------------------------------------
# Fixture: deployed_db_test
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def deployed_db_test(
    load_db_test: dict,
    db_test_image: str,
    vcluster: dict,
) -> dict:
    """Deploy db-test and return deployment info for reuse by tests."""
    client: StyrminClient = load_db_test["client"]
    environment_id = load_db_test["environment_id"]
    kubeconfig_path = vcluster["kubeconfig_path"]

    task = await client.deployments.create(
        driver="db-test", version="0.1.0", environment_id=environment_id
    )
    deployment_id = task.deployment_id
    assert deployment_id is not None, "Task should have a deployment_id"

    deployment = await _wait_for_deployment_running(
        client, deployment_id, timeout=300.0
    )

    namespace = f"styrmin-{deployment_id}"
    instance_id = None
    if deployment and deployment.application_instance:
        instance_id = str(deployment.application_instance.id)

    return {
        "deployment_id": str(deployment_id),
        "instance_id": instance_id,
        "namespace": namespace,
        "kubeconfig_path": kubeconfig_path,
    }
