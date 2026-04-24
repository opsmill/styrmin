import asyncio
import logging
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator

import httpx
import kr8s.asyncio
import pytest
import yaml
from dulwich import porcelain
from kr8s.asyncio.objects import Service as AsyncService
from kubernetes_asyncio import client as kubeclient
from kubernetes_asyncio.client.exceptions import ApiException as K8sApiException
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import StyrminError

from tests.e2e.drivers import ScenarioDriver
from tests.e2e.drivers.api_driver import ApiScenarioDriver
from tests.e2e.drivers.errors import ScenarioActionError
from tests.e2e.drivers.refs import DeploymentRef
from tests.e2e.drivers.ui_driver import UiScenarioDriver

if TYPE_CHECKING:
    from playwright.async_api import Page

from playwright.async_api import async_playwright

_LOG = logging.getLogger(__name__)

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
    interval: float = 10.0,  # noqa: ARG001 — preserved for call-site compatibility
) -> DeploymentRef:
    """Shim for api-only tests that drive the SDK directly.

    Delegates to :class:`ApiScenarioDriver` so the polling logic lives in one
    place. Returns a ``DeploymentRef`` (callers only assert ``is not None``).
    """
    driver = ApiScenarioDriver(client)
    return await driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=timeout
    )


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
        "infrahub": {
            "source": PROJECT_ROOT / "driver" / "examples" / "infrahub",
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
    except K8sApiException as exc:
        if exc.status != 409:
            raise

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
# Dual-entrypoint session fixtures — driver_mode, session_ui_page,
# session_scenario_driver
# ---------------------------------------------------------------------------
#
# CI runs each mode in its own job with a fresh vcluster (`-k api-chromium`
# vs `-k ui-chromium`), so the session-scoped setup is exercised through
# both the SDK (api mode) and Playwright (ui mode) over the course of CI.
@pytest.fixture(
    scope="session",
    params=[
        pytest.param("api", id="api"),
        pytest.param("ui", id="ui"),
    ],
)
def driver_mode(request: pytest.FixtureRequest) -> str:
    """Selects the ScenarioDriver entrypoint for the whole session."""
    return request.param


@pytest.fixture(scope="session")
async def session_ui_page(
    driver_mode: str,
    styrmin_deployment: str,
    browser_name: str,  # noqa: ARG001 — declared so pytest-playwright parametrizes node IDs with `-chromium`
) -> AsyncGenerator["Page | None", None]:
    """Playwright page at session scope for styrmin_resources UI-mode setup.

    pytest-playwright-asyncio's ``page`` fixture is function-scoped and its
    ``browser`` fixture is async — requesting the latter from inside this
    async fixture triggers ``Runner.run() cannot be called from a running
    event loop`` because pytest-asyncio spins up a nested runner for each
    async fixture resolution. We bypass it by driving ``async_playwright``
    directly, which also keeps the ``browser_name`` declaration cheap
    (string-only) so the API-only CI job still doesn't pay for the browser
    binary — it never enters this branch.

    ``browser_name`` is kept as a declared parameter so pytest-playwright
    adds ``-chromium`` to node IDs — that's what the CI filters
    ``-k "api-chromium"`` / ``-k "ui-chromium"`` match.
    """
    if driver_mode != "ui":
        yield None
        return
    # Headless + the NETLINK_ROUTE LD_PRELOAD shim (scoped to the browser
    # process so it doesn't leak into pytest / kubectl / helm subprocesses).
    # Chromium's AddressTrackerLinux otherwise reacts to Docker/veth netlink
    # churn mid-test and occasionally wedges.
    launch_kwargs: dict[str, object] = {"headless": True}
    no_netlink_so = os.environ.get("NO_NETLINK_SO")
    if no_netlink_so:
        launch_kwargs["env"] = {**os.environ, "LD_PRELOAD": no_netlink_so}
    async with async_playwright() as p:
        browser = await p.chromium.launch(**launch_kwargs)
        context = await browser.new_context(base_url=styrmin_deployment)
        page = await context.new_page()
        try:
            yield page
        finally:
            await page.close()
            await context.close()
            await browser.close()


@pytest.fixture(scope="session")
async def session_scenario_driver(
    driver_mode: str,
    styrmin_deployment: str,
    session_ui_page: "Page | None",
) -> AsyncGenerator[tuple[ScenarioDriver, StyrminClient], None]:
    """Session-scoped driver used by ``styrmin_resources`` for platform setup.

    Yields ``(driver, client)``. The SDK client is exposed alongside the
    driver so session-scoped fixtures that still drive SDK-only flows
    (auxiliary driver loads, infrahub setup, etc.) keep working until
    they're converted to the driver abstraction.
    """
    async with StyrminClient(server_address=styrmin_deployment) as client:
        driver: ScenarioDriver
        if driver_mode == "api":
            driver = ApiScenarioDriver(client)
        else:
            assert session_ui_page is not None, (
                "session_ui_page must be built in ui mode"
            )
            driver = UiScenarioDriver(page=session_ui_page, base_url=styrmin_deployment)
        yield driver, client


# ---------------------------------------------------------------------------
# Fixture: styrmin_resources
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def styrmin_resources(
    git_server: dict[str, str],
    styrmin_deployment: str,
    driver_mode: str,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> AsyncGenerator[dict, None]:
    styrmin_url = styrmin_deployment
    git_url = git_server["simple-app"]

    driver, client = session_scenario_driver

    cluster = await driver.create_cluster(
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

    environment = await driver.create_environment(
        name="test-environment",
        cluster_id=cluster.id,
        config={"ip_whitelist": ["127.0.0.1"]},
    )

    bsl = await driver.create_backup_storage_location(
        name="test-bsl",
        endpoint="http://minio.styrmin.svc:9000",
        bucket="velero",
        region="minio",
        access_key_id="minioadmin",
        secret_access_key="minioadmin",
    )

    await driver.assign_bsl_to_environment(environment_id=environment.id, bsl_id=bsl.id)

    driver_version = await driver.load_driver_version(git_url=git_url, ref="master")

    yield {
        "cluster_id": cluster.id,
        "environment_id": environment.id,
        "bsl_id": bsl.id,
        "bsl_name": bsl.name,
        "driver_id": driver_version.application_driver_id,
        "styrmin_url": styrmin_url,
        "driver_mode": driver_mode,
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
    styrmin_resources: dict,  # noqa: ARG001 — transitive: cluster/BSL/driver
    scenario_environment_id: str,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    simple_app_image: str,  # noqa: ARG001 — builds the image
    vcluster: dict,
) -> dict:
    """Deploy simple-app and return deployment info for reuse by tests.

    Deploys into the session-scoped ``scenario_environment_id`` (shared
    across all tests in the same driver mode) rather than the bootstrap
    ``styrmin_resources`` env. Two envs would mean two dedicated-ingress
    controllers, which confuses ``test_traffic_routes_through_*`` when
    picking "the" Traefik service.
    """
    driver, _ = session_scenario_driver
    deployment = await driver.create_deployment(
        driver="simple-app", version="0.1.0", environment_id=scenario_environment_id
    )
    deployment = await driver.wait_for_deployment_running(deployment_id=deployment.id)

    return {
        "deployment_id": deployment.id,
        "instance_id": deployment.instance_id,
        "namespace": f"styrmin-{deployment.id}",
        "kubeconfig_path": vcluster["kubeconfig_path"],
    }


# ---------------------------------------------------------------------------
# Fixture: load_infrahub
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def load_infrahub(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    git_server: dict[str, str],
) -> AsyncGenerator[dict, None]:
    """Load the infrahub application driver from the in-cluster git server."""
    driver, _ = session_scenario_driver
    version = await driver.load_driver_version(
        git_url=git_server["infrahub"], ref="master"
    )
    yield {**styrmin_resources, "infrahub_driver_id": version.application_driver_id}


# ---------------------------------------------------------------------------
# Fixture: deployed_infrahub_app
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def deployed_infrahub_app(
    load_infrahub: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    vcluster: dict,
) -> dict:
    """Deploy infrahub and return deployment info for reuse by tests."""
    driver, _ = session_scenario_driver
    environment_id = load_infrahub["environment_id"]

    deployment = await driver.create_deployment(
        driver="infrahub", version="1.6.0", environment_id=environment_id
    )
    # Infrahub has many components — wait longer than the default.
    deployment = await driver.wait_for_deployment_running(
        deployment_id=deployment.id, timeout=600.0
    )

    return {
        "deployment_id": deployment.id,
        "instance_id": deployment.instance_id,
        "namespace": f"styrmin-{deployment.id}",
        "kubeconfig_path": vcluster["kubeconfig_path"],
    }


# ---------------------------------------------------------------------------
# Fixture: load_semaphore
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def load_semaphore(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    git_server: dict[str, str],
) -> AsyncGenerator[dict, None]:
    """Load the Semaphore application driver from the git server."""
    driver, _ = session_scenario_driver
    version = await driver.load_driver_version(
        git_url=git_server["semaphore"], ref="master"
    )
    yield {**styrmin_resources, "semaphore_driver_id": version.application_driver_id}


# ---------------------------------------------------------------------------
# Fixture: deployed_semaphore
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def deployed_semaphore(
    load_semaphore: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    vcluster: dict,
) -> dict:
    """Deploy Semaphore and return deployment info for reuse by tests."""
    driver, _ = session_scenario_driver
    environment_id = load_semaphore["environment_id"]

    deployment = await driver.create_deployment(
        driver="semaphore",
        version="2.16.47",
        environment_id=environment_id,
        name="semaphore",
    )
    deployment = await driver.wait_for_deployment_running(
        deployment_id=deployment.id, timeout=300.0
    )

    return {
        "deployment_id": deployment.id,
        "instance_id": deployment.instance_id,
        "namespace": f"styrmin-{deployment.id}",
        "kubeconfig_path": vcluster["kubeconfig_path"],
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
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    git_server: dict[str, str],
) -> AsyncGenerator[dict, None]:
    """Load the db-test application driver from the git server."""
    driver, _ = session_scenario_driver
    version = await driver.load_driver_version(
        git_url=git_server["db-test"], ref="master"
    )
    yield {**styrmin_resources, "db_test_driver_id": version.application_driver_id}


# ---------------------------------------------------------------------------
# Fixture: deployed_db_test
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def deployed_db_test(
    load_db_test: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    db_test_image: str,  # noqa: ARG001 — builds the image
    vcluster: dict,
) -> dict:
    """Deploy db-test and return deployment info for reuse by tests."""
    driver, _ = session_scenario_driver
    environment_id = load_db_test["environment_id"]

    deployment = await driver.create_deployment(
        driver="db-test", version="0.1.0", environment_id=environment_id
    )
    deployment = await driver.wait_for_deployment_running(
        deployment_id=deployment.id, timeout=300.0
    )

    return {
        "deployment_id": deployment.id,
        "instance_id": deployment.instance_id,
        "namespace": f"styrmin-{deployment.id}",
        "kubeconfig_path": vcluster["kubeconfig_path"],
    }


# ---------------------------------------------------------------------------
# Dual-entrypoint E2E — Playwright + ScenarioDriver wiring
# ---------------------------------------------------------------------------
#
# Every E2E scenario that takes ``scenario_driver`` runs twice — once through
# ``ApiScenarioDriver`` (SDK-based) and once through ``UiScenarioDriver``
# (Playwright-based). See specs/001-dual-e2e-entrypoints/.


@pytest.fixture
async def scenario_driver(
    driver_mode: str,
    styrmin_resources: dict,
    styrmin_deployment: str,
    session_ui_page: "Page | None",
) -> AsyncGenerator[ScenarioDriver, None]:
    """Per-test ScenarioDriver. Inherits its mode from session-scoped driver_mode.

    For UI mode we reuse the session-scoped Playwright ``Page`` rather than
    pytest-playwright's function-scoped ``page`` fixture. That fixture is
    async and resolving it from inside this async fixture triggers
    ``Runner.run() cannot be called from a running event loop`` — the same
    pattern the session fixture already avoids. Since every UI scenario
    calls ``create_deployment`` via a freshly-built scenario state, reusing
    the session page is safe: the driver navigates to the relevant URL at
    the start of each action.
    """
    if driver_mode == "api":
        client: StyrminClient = styrmin_resources["client"]
        yield ApiScenarioDriver(client)
        return

    assert session_ui_page is not None, "session_ui_page must be built in ui mode"
    yield UiScenarioDriver(page=session_ui_page, base_url=styrmin_deployment)


@pytest.fixture(scope="session")
async def scenario_environment_id(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    driver_mode: str,
) -> AsyncGenerator[str, None]:
    """Session-scoped environment shared by all scenarios in the mode.

    Parametrized through ``session_scenario_driver`` (which inherits
    ``driver_mode``), so ``[api]`` and ``[ui]`` variants each get their
    own env — isolation between modes is preserved, but tests within a
    single mode share one env. That avoids paying ``create_environment``
    + ``assign_bsl`` + ``delete_environment`` per test (minor in itself)
    and, more importantly, lets ``deployed_simple_app`` and friends be
    reused across tests that merely observe a running deployment.

    Multiple tests deploying the same driver into this shared env must
    pass a unique ``service_name_overrides`` to avoid the per-env
    service-name uniqueness check. ``test_service_discovery`` already
    does this; ``test_upgrade_simple_app``, ``test_deployment_timeline_*``,
    and ``test_backup_and_restore_lifecycle`` do the same for that
    reason.
    """
    driver, client = session_scenario_driver
    name = f"scenario-env-{uuid.uuid4().hex[:8]}"
    env = await driver.create_environment(
        name=name,
        cluster_id=styrmin_resources["cluster_id"],
        config={"ip_whitelist": ["127.0.0.1"]},
    )
    env_id = env.id
    try:
        await driver.assign_bsl_to_environment(
            environment_id=env_id, bsl_id=styrmin_resources["bsl_id"]
        )
    except ScenarioActionError as exc:
        pytest.skip(
            f"BSL assign failed for env {env_id} (driver_mode={driver_mode}): {exc}"
        )
    try:
        yield env_id
    finally:
        try:
            await client.environments.delete(environment_id=env_id)
        except StyrminError as exc:
            _LOG.warning("Env cleanup failed for env %s: %s", env_id, exc)


# ---------------------------------------------------------------------------
# pytest_collection_modifyitems — api_only / ui_only enforcement + UI retry
# ---------------------------------------------------------------------------


def _get_entrypoint_marker(item: pytest.Item) -> tuple[str | None, str | None]:
    """Return ``(mode, reason)`` if item has api_only/ui_only, else ``(None, None)``.

    Fails collection if both markers are set or the reason is empty.
    """
    api_only = item.get_closest_marker("api_only")
    ui_only = item.get_closest_marker("ui_only")
    if api_only is not None and ui_only is not None:
        pytest.fail(f"{item.nodeid}: cannot declare both api_only and ui_only")
    for mode, marker in (("api", api_only), ("ui", ui_only)):
        if marker is None:
            continue
        reason = marker.kwargs.get("reason") or (
            marker.args[0] if marker.args else None
        )
        if not reason or not str(reason).strip():
            pytest.fail(
                f"{item.nodeid}: @pytest.mark.{mode}_only requires a non-empty "
                "reason=..."
            )
        return mode, str(reason)
    return None, None


def _driver_param_id(item: pytest.Item) -> str | None:
    """Return the driver_mode param id ('api' / 'ui') for a parametrized item."""
    callspec = getattr(item, "callspec", None)
    if callspec is None:
        return None
    return callspec.params.get("driver_mode")


def pytest_collection_modifyitems(
    config: pytest.Config,  # noqa: ARG001
    items: list[pytest.Item],
) -> None:
    """Enforce api_only/ui_only contract."""
    for item in items:
        driver_id = _driver_param_id(item)
        if driver_id is None:
            continue

        only_mode, reason = _get_entrypoint_marker(item)
        if only_mode is not None and only_mode != driver_id:
            item.add_marker(pytest.mark.skip(reason=f"{only_mode}_only: {reason}"))
