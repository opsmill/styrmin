"""End-to-end coverage for per-component image overrides
(018-component-image-overrides).

Drives the user-facing path: ``set_component_image`` (SDK ``updateDeployment``
or the Settings edit drawer's ``Image for <component>`` input) → server
reconciler → HelmRelease post-render patch on the declared component container
→ rendered pod spec on the vcluster. Asserts on the live workload and on
``Deployment.componentImageOverrides``. The upgrade test also covers the
pinned-override listing and a ``{{ app.version }}`` override following an
upgrade. The one-call upgrade test (#431) sets an override and an env var
with the version change while the HelmRelease is suspended, and asserts the
driver's upgrade Job runs with both before the workload has them.
The misnamed-container test (SC-005) deploys a driver variant whose
``server`` component container is ``wrong-name`` and asserts an override fails
the deployment instead of adding a container.

The replica test (023-per-component-replicas) runs first on the same
deployment: it scales ``server`` to 2 and back through ``set_component_replicas``
and reads each workload once after the update task completes, so the counts
prove that the task waited for the pods. It also checks that the singleton
``database`` stays at 1 and that an override of 2 on it is rejected. A
finalizer clears the ``server`` override, so the image tests start at 1 replica.

The override images are the simple-app builds re-tagged by the session fixture
``simple_app_override_images`` under ``registry.example/acme/simple-app-patched``;
the vcluster nodes pull them from the host Docker daemon like the base images.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Callable

import pytest
from kubernetes_asyncio import client as kubeclient
from styrmin_sdk import StyrminClient
from styrmin_sdk._queries import load_query
from styrmin_sdk.exceptions import OperationFailedError
from styrmin_sdk.models import (
    ComponentConfigInput,
    EnvVarInput,
    UpdateDeploymentInput,
)

from tests.e2e.drivers import ScenarioDriver
from tests.e2e.drivers.api_driver import ApiScenarioDriver
from tests.e2e.helpers.drivers import (
    MISNAMED_CONTAINER,
    MISNAMED_DRIVER_NAME,
    publish_misnamed_simple_app_driver,
)
from tests.e2e.helpers.workloads import (
    _wait_for_pod_template,
    container_spec,
    read_workload_replicas,
    wait_for_ready_container_image,
)
from tests.e2e.pages.deployment_detail import DeploymentDetailPage

pytestmark = [
    pytest.mark.shard_configuration,
]

RECONCILE_TIMEOUT_SECONDS = 480.0
SERVER_SELECTOR = "app.kubernetes.io/name=simple-app"
SERVER_CONTAINER = "simple-app"
CHART_IMAGE = "simple-app:0.1.0"
TOKEN_IMAGE = "registry.example/acme/simple-app-patched:{{ app.version }}"
# Fixed by the simple-app values template's ``fullnameOverride``.
SERVER_WORKLOAD = "styrmin-simple-app"
# Two 5s operator timer ticks plus the Flux reconcile and the 5s status report, with headroom.
GUARD_FAILURE_TIMEOUT_SECONDS = 120.0
# The bitnami subchart's ``fullnameOverride`` in the simple-app values template.
DATABASE_WORKLOAD = "styrmin-postgresql"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def image_override_environment(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> AsyncGenerator[dict, None]:
    driver, client = session_scenario_driver
    env = await driver.create_environment(
        name=f"image-override-e2e-{uuid.uuid4().hex[:8]}",
        cluster_id=styrmin_resources["cluster_id"],
        config={},
    )
    yield {"environment_id": str(env.id), "client": client}


@pytest.fixture(scope="module")
async def image_override_deployment(
    image_override_environment: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    simple_app_override_images: dict[str, str],  # noqa: ARG001 — builds and tags
    vcluster: dict,
) -> dict:
    driver, _ = session_scenario_driver
    deployment = await driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=image_override_environment["environment_id"],
        name="image-override-a",
    )
    deployment = await driver.wait_for_deployment_running(deployment_id=deployment.id)
    return {
        "deployment_id": str(deployment.id),
        "namespace": f"styrmin-{deployment.id}",
        "kubeconfig_path": vcluster["kubeconfig_path"],
    }


@pytest.fixture(scope="module")
async def image_override_upgrade_deployment(
    image_override_environment: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    simple_app_override_images: dict[str, str],  # noqa: ARG001 — builds and tags
) -> dict:
    """A deployment of its own at 0.1.0 for the upgrade test; it renames its
    service because service names are unique per environment."""
    driver, _ = session_scenario_driver
    deployment = await driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=image_override_environment["environment_id"],
        name="image-override-b",
        service_name_overrides=[
            {"driverServiceName": "simple-app", "overrideName": "simple-app-b"}
        ],
    )
    deployment = await driver.wait_for_deployment_running(deployment_id=deployment.id)
    return {
        "deployment_id": str(deployment.id),
        "namespace": f"styrmin-{deployment.id}",
    }


@pytest.fixture
def _io_driver_bound(
    image_override_environment: dict,
    image_override_deployment: dict,  # noqa: ARG001 — force fixture ordering
    scenario_driver: ScenarioDriver,
) -> None:
    scenario_driver.attach_to_deployment(
        environment_id=image_override_environment["environment_id"]
    )


@pytest.fixture
async def _clear_server_replicas(
    image_override_environment: dict,
    image_override_deployment: dict,
) -> AsyncGenerator[None, None]:
    """Clear a ``server`` replica override the test leaves behind and wait for
    the scale-down, so the image tests that share the deployment see 1 replica."""
    yield
    client: StyrminClient = image_override_environment["client"]
    deployment_id = image_override_deployment["deployment_id"]
    if await _stored_replicas(client, deployment_id, "server") is None:
        return
    known = await _task_ids(client, deployment_id)
    await ApiScenarioDriver(client).set_component_replicas(
        deployment_id=deployment_id, component="server", replicas=None
    )
    await _wait_for_new_task_succeeded(client, deployment_id, known)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _stored_replicas(
    client: StyrminClient, deployment_id: str, component: str
) -> int | None:
    config = (await client.deployments.get(deployment_id)).config or {}
    block = (config.get("components") or {}).get(component) or {}
    return block.get("replicas")


async def _task_ids(client: StyrminClient, deployment_id: str) -> set[str]:
    return {
        str(e.task.id) for e in await client.deployments.get_timeline(deployment_id)
    }


async def _wait_for_new_task_succeeded(
    client: StyrminClient, deployment_id: str, known: set[str]
) -> str:
    """Wait for the one task created after ``known`` to end; assert its task
    result is ``SUCCEEDED`` and return its id.

    ``Deployment.status`` stays ``running`` through an update, so only the
    task result tells that the rollout (the operator's HelmRelease step) ended.
    """
    deadline = time.monotonic() + RECONCILE_TIMEOUT_SECONDS
    new: list[Any] = []
    while time.monotonic() < deadline:
        timeline = await client.deployments.get_timeline(deployment_id)
        new = [e.task for e in timeline if str(e.task.id) not in known]
        assert len(new) <= 1, [(str(t.id), t.type_, t.result.value) for t in new]
        if new and new[0].result.value != "RUNNING":
            task = new[0]
            assert task.result.value == "SUCCEEDED", (
                f"task {task.id} ({task.type_}) ended {task.result.value}: "
                f"{[(step.name, step.status, step.error) for step in task.steps]}"
            )
            return str(task.id)
        await asyncio.sleep(2)
    raise TimeoutError(
        f"No new task on deployment {deployment_id} ended within "
        f"{RECONCILE_TIMEOUT_SECONDS}s: {[(str(t.id), t.result.value) for t in new]}"
    )


async def _read_component_replicas(
    client: StyrminClient, deployment_id: str
) -> dict[str, dict]:
    raw = await client._transport.execute(
        load_query("get_deployment_component_replicas_full"),
        {"deploymentId": deployment_id},
    )
    assert "errors" not in raw, raw
    return {
        row["component"]: row for row in raw["data"]["deployment"]["componentReplicas"]
    }


def _all_counts(n: int) -> dict[str, int]:
    return {"spec": n, "status": n, "updated": n, "ready": n, "available": n}


async def _read_image_overrides(
    client: StyrminClient, deployment_id: str
) -> dict[str, dict]:
    raw = await client._transport.execute(
        load_query("get_deployment_component_image_overrides_full"),
        {"deploymentId": deployment_id},
    )
    assert "errors" not in raw, raw
    return {
        row["component"]: row
        for row in raw["data"]["deployment"]["componentImageOverrides"]
    }


def _server_image(workload: Any) -> str | None:
    container = container_spec(workload, SERVER_CONTAINER)
    return container.image if container is not None else None


def _pod_shape(workload: Any) -> dict[str, Any]:
    """Everything the override must leave alone: container names, init
    containers, and the server container's env and pull policy."""
    pod_spec = workload.spec.template.spec
    server = container_spec(workload, SERVER_CONTAINER)
    assert server is not None, f"no {SERVER_CONTAINER!r} container"
    return {
        "containers": [c.name for c in pod_spec.containers or []],
        "init_containers": [c.to_dict() for c in pod_spec.init_containers or []],
        "server_env": [e.to_dict() for e in server.env or []],
        "server_pull_policy": server.image_pull_policy,
    }


async def _wait_for_deployment_status(
    client: StyrminClient,
    deployment_id: str,
    predicate: Callable[[dict], bool],
    *,
    description: str,
    timeout: float = RECONCILE_TIMEOUT_SECONDS,
) -> dict:
    """Poll ``Deployment.status`` and ``crdStatus`` until ``predicate`` holds."""
    deadline = time.monotonic() + timeout
    deployment: dict = {}
    while time.monotonic() < deadline:
        raw = await client._transport.execute(
            load_query("get_deployment_status"), {"deploymentId": deployment_id}
        )
        assert "errors" not in raw, raw
        deployment = raw["data"]["deployment"] or {}
        if deployment and predicate(deployment):
            return deployment
        await asyncio.sleep(2)
    raise TimeoutError(
        f"Timed out after {timeout}s waiting for {description} on deployment "
        f"{deployment_id}; last seen: {deployment}"
    )


async def _wait_for_server_image(vcluster: dict, namespace: str, image: str) -> Any:
    return await _wait_for_pod_template(
        vcluster,
        namespace=namespace,
        label_selector=SERVER_SELECTOR,
        predicate=lambda d: _server_image(d) == image,
        description=f"{SERVER_CONTAINER} container image == {image}",
    )


async def _read_server_workload(vcluster: dict, namespace: str) -> Any:
    apps = kubeclient.AppsV1Api(vcluster["api"])
    return await apps.read_namespaced_deployment(SERVER_WORKLOAD, namespace)


async def _suspend_helmrelease(
    vcluster: dict, namespace: str, *, suspend: bool
) -> None:
    """Set ``spec.suspend`` on the namespace's one HelmRelease; the operator keeps it."""
    custom = kubeclient.CustomObjectsApi(vcluster["api"])
    crd = {
        "group": "helm.toolkit.fluxcd.io",
        "version": "v2",
        "namespace": namespace,
        "plural": "helmreleases",
    }
    listed = await custom.list_namespaced_custom_object(**crd)
    assert len(listed["items"]) == 1, [i["metadata"]["name"] for i in listed["items"]]
    await custom.patch_namespaced_custom_object(
        **crd,
        name=listed["items"][0]["metadata"]["name"],
        body=[{"op": "add", "path": "/spec/suspend", "value": suspend}],
    )


async def _wait_for_upgrade_job(vcluster: dict, namespace: str) -> Any:
    """Return the Job that the driver's upgrade action starts (``execute_commands``)."""
    batch = kubeclient.BatchV1Api(vcluster["api"])
    deadline = time.monotonic() + RECONCILE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        jobs = await batch.list_namespaced_job(namespace)
        upgrade_jobs = [
            j
            for j in jobs.items
            if j.spec.template.spec.containers[0].name == "user-job"
        ]
        if upgrade_jobs:
            assert len(upgrade_jobs) == 1, [j.metadata.name for j in upgrade_jobs]
            return upgrade_jobs[0]
        await asyncio.sleep(2)
    raise TimeoutError(
        f"No upgrade Job in {namespace} after {RECONCILE_TIMEOUT_SECONDS}s"
    )


# ---------------------------------------------------------------------------
# 023 — scale a component, singleton guard
# ---------------------------------------------------------------------------


@pytest.mark.ci
async def test_scale_server_and_singleton_guard(
    image_override_environment: dict,
    image_override_deployment: dict,
    vcluster: dict,
    scenario_driver: ScenarioDriver,
    driver_mode: str,
    session_ui_page: Any,
    _io_driver_bound: None,
    _clear_server_replicas: None,
) -> None:
    """023 US1 (research D-012): ``server`` scaled to 2 runs 2 ready pods when
    the update task completes, and 1 again once the override is cleared. The
    singleton ``database`` stays at 1, shows a fixed field in the edit drawer,
    and an override of 2 on it is rejected before any task is created.

    Each workload is read once right after its task ends, without polling:
    the counts prove that the task waited for the scale-up and the scale-down
    (SC-002, critique E7)."""
    client: StyrminClient = image_override_environment["client"]
    deployment_id = image_override_deployment["deployment_id"]
    namespace = image_override_deployment["namespace"]
    apps = kubeclient.AppsV1Api(vcluster["api"])

    rows = await _read_component_replicas(client, deployment_id)
    assert rows["server"]["source"] == "CHART", rows
    assert rows["server"]["override"] is None, rows

    # 1. Scale ``server`` to 2.
    known = await _task_ids(client, deployment_id)
    await scenario_driver.set_component_replicas(
        deployment_id=deployment_id, component="server", replicas=2
    )
    await _wait_for_new_task_succeeded(client, deployment_id, known)
    assert await read_workload_replicas(
        apps, namespace=namespace, kind="Deployment", name=SERVER_WORKLOAD
    ) == _all_counts(2)

    rows = await _read_component_replicas(client, deployment_id)
    assert set(rows) == {"server", "database"}, rows
    assert rows["server"] == {
        "component": "server",
        "count": 2,
        "source": "OVERRIDE",
        "override": 2,
        "singleton": False,
        "isOrphaned": False,
        "isApplicable": True,
    }

    # 2. The singleton ``database`` stays at 1.
    assert await read_workload_replicas(
        apps, namespace=namespace, kind="StatefulSet", name=DATABASE_WORKLOAD
    ) == _all_counts(1)
    assert rows["database"] == {
        "component": "database",
        "count": 1,
        "source": "DRIVER_DEFAULT",
        "override": None,
        "singleton": True,
        "isOrphaned": False,
        "isApplicable": True,
    }
    if driver_mode == "ui":
        assert session_ui_page is not None
        detail = DeploymentDetailPage(session_ui_page)
        await detail.goto(
            environment_id=image_override_environment["environment_id"],
            deployment_id=deployment_id,
        )
        assert await detail.read_component_replicas_field(component="database") == {
            "value": "1 (singleton)",
            "read_only": True,
        }

    # 3. An override of 2 on ``database`` is rejected; nothing changes.
    config_before = (await client.deployments.get(deployment_id)).config
    known = await _task_ids(client, deployment_id)
    with pytest.raises(OperationFailedError) as exc_info:
        await client.deployments.update(
            deployment_id,
            input=UpdateDeploymentInput(
                components=[
                    ComponentConfigInput(name="server", replicas=2),
                    ComponentConfigInput(name="database", replicas=2),
                ]
            ),
        )
    assert exc_info.value.typename == "SINGLETON_REPLICA_OVERRIDE", exc_info.value
    assert "'database'" in str(exc_info.value)
    assert await _task_ids(client, deployment_id) == known
    assert (await client.deployments.get(deployment_id)).config == config_before

    # 4. Clear the override: back to the chart's 1 replica.
    await scenario_driver.set_component_replicas(
        deployment_id=deployment_id, component="server", replicas=None
    )
    await _wait_for_new_task_succeeded(client, deployment_id, known)
    assert await read_workload_replicas(
        apps, namespace=namespace, kind="Deployment", name=SERVER_WORKLOAD
    ) == _all_counts(1)

    rows = await _read_component_replicas(client, deployment_id)
    assert rows["server"]["count"] is None, rows
    assert rows["server"]["source"] == "CHART", rows
    assert rows["server"]["override"] is None, rows
    assert await _stored_replicas(client, deployment_id, "server") is None


# ---------------------------------------------------------------------------
# US1 (+ US3) — override, then clear
# ---------------------------------------------------------------------------


@pytest.mark.ci
async def test_override_then_clear(
    image_override_environment: dict,
    image_override_deployment: dict,
    simple_app_override_images: dict[str, str],
    vcluster: dict,
    scenario_driver: ScenarioDriver,
    _io_driver_bound: None,
) -> None:
    """US1: an image override on ``server`` replaces only the component
    container's image; the pod keeps its containers, init container and env,
    and the read surface shows the override applied. US3: clearing it restores
    the chart image on the next reconcile and the read surface lists nothing."""
    client: StyrminClient = image_override_environment["client"]
    deployment_id = image_override_deployment["deployment_id"]
    namespace = image_override_deployment["namespace"]
    patched = simple_app_override_images["0.1.0"]

    baseline = await _wait_for_server_image(vcluster, namespace, CHART_IMAGE)
    baseline_shape = _pod_shape(baseline)
    assert await _read_image_overrides(client, deployment_id) == {}

    # Set half (US1).
    await scenario_driver.set_component_image(
        deployment_id=deployment_id, component="server", image=patched
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )
    workload = await _wait_for_server_image(vcluster, namespace, patched)
    assert _pod_shape(workload) == baseline_shape
    await wait_for_ready_container_image(
        vcluster,
        namespace=namespace,
        label_selector=SERVER_SELECTOR,
        container_name=SERVER_CONTAINER,
        image=patched,
    )

    rows = await _read_image_overrides(client, deployment_id)
    assert set(rows) == {"server"}, rows
    assert rows["server"]["reference"] == patched
    assert rows["server"]["resolvedReference"] == patched
    assert rows["server"]["isApplicable"] is True
    assert rows["server"]["isOrphaned"] is False

    # Clear half (US3): the next render drops the patch, so the chart image returns.
    await scenario_driver.set_component_image(
        deployment_id=deployment_id, component="server", image=None
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )
    workload = await _wait_for_server_image(vcluster, namespace, CHART_IMAGE)
    assert _pod_shape(workload) == baseline_shape
    await wait_for_ready_container_image(
        vcluster,
        namespace=namespace,
        label_selector=SERVER_SELECTOR,
        container_name=SERVER_CONTAINER,
        image=CHART_IMAGE,
    )
    assert await _read_image_overrides(client, deployment_id) == {}


@pytest.mark.ci
@pytest.mark.api_only(
    reason="the upgrade dialog does not send the config; only the API sets it with the version"
)
async def test_override_with_version_change_reaches_upgrade_job(
    image_override_environment: dict,
    image_override_deployment: dict,
    simple_app_override_images: dict[str, str],
    vcluster: dict,
) -> None:
    """#431: one ``updateDeploymentVersion`` call sets an image override and an
    env var on ``server`` and moves to 0.2.0. The HelmRelease is suspended until
    the driver's upgrade action has started its Job, so the action reads a
    workload that still runs 0.1.0 without the override, as when Flux renders
    late. The Job must still run the override's build at 0.2.0 with the env var.

    Runs after ``test_override_then_clear``, which leaves the deployment at 0.1.0
    without overrides."""
    client: StyrminClient = image_override_environment["client"]
    deployment_id = image_override_deployment["deployment_id"]
    namespace = image_override_deployment["namespace"]
    patched_v2 = simple_app_override_images["0.2.0"]
    marker = EnvVarInput(name="STYRMIN_E2E_UPGRADE_MARKER", value="one-call")

    await _wait_for_server_image(vcluster, namespace, CHART_IMAGE)
    await _suspend_helmrelease(vcluster, namespace, suspend=True)
    try:
        await client.deployments.update_version(
            deployment_id,
            "0.2.0",
            input=UpdateDeploymentInput(
                components=[
                    ComponentConfigInput(
                        name="server", image=TOKEN_IMAGE, env_vars=[marker]
                    )
                ]
            ),
        )
        job = await _wait_for_upgrade_job(vcluster, namespace)
        # The workload had not changed when the action read it.
        assert _server_image(await _read_server_workload(vcluster, namespace)) == (
            CHART_IMAGE
        )
    finally:
        await _suspend_helmrelease(vcluster, namespace, suspend=False)

    job_container = job.spec.template.spec.containers[0]
    assert job_container.image == patched_v2
    job_env = {e.name: e.value for e in job_container.env or []}
    assert job_env.get(marker.name) == marker.value, job_env

    await _wait_for_deployment_status(
        client,
        deployment_id,
        lambda d: d["status"] == "running",
        description="status == running",
    )
    await _wait_for_server_image(vcluster, namespace, patched_v2)


# ---------------------------------------------------------------------------
# US2 — follow the application version
# ---------------------------------------------------------------------------


@pytest.mark.ci
async def test_token_follows_upgrade_and_action_job(
    image_override_environment: dict,
    image_override_upgrade_deployment: dict,
    simple_app_override_images: dict[str, str],
    vcluster: dict,
    scenario_driver: ScenarioDriver,
) -> None:
    """US2: a literal-tag override is listed as pinned before an upgrade; a
    ``{{ app.version }}`` override is not, and after upgrading to 0.2.0 the
    ``server`` container runs the 0.2.0 override image."""
    client: StyrminClient = image_override_environment["client"]
    deployment_id = image_override_upgrade_deployment["deployment_id"]
    namespace = image_override_upgrade_deployment["namespace"]
    patched_v1 = simple_app_override_images["0.1.0"]
    patched_v2 = simple_app_override_images["0.2.0"]
    scenario_driver.attach_to_deployment(
        environment_id=image_override_environment["environment_id"]
    )

    # A literal tag stays pinned across the upgrade (FR-008).
    await scenario_driver.set_component_image(
        deployment_id=deployment_id, component="server", image=patched_v1
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )
    assert await scenario_driver.pinned_image_components(
        deployment_id=deployment_id, target_version="0.2.0"
    ) == ["server"]

    # The token follows the application version, so nothing is pinned.
    await scenario_driver.set_component_image(
        deployment_id=deployment_id, component="server", image=TOKEN_IMAGE
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )
    assert (
        await scenario_driver.pinned_image_components(
            deployment_id=deployment_id, target_version="0.2.0"
        )
        == []
    )
    await _wait_for_server_image(vcluster, namespace, patched_v1)
    rows = await _read_image_overrides(client, deployment_id)
    assert rows["server"]["reference"] == TOKEN_IMAGE
    assert rows["server"]["resolvedReference"] == patched_v1

    await scenario_driver.upgrade_deployment(
        deployment_id=deployment_id, version="0.2.0"
    )
    upgraded = await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )
    assert upgraded.application_version == "0.2.0"

    await _wait_for_server_image(vcluster, namespace, patched_v2)
    await wait_for_ready_container_image(
        vcluster,
        namespace=namespace,
        label_selector=SERVER_SELECTOR,
        container_name=SERVER_CONTAINER,
        image=patched_v2,
    )

    # The upgrade Job's image is asserted by test_override_with_version_change_reaches_upgrade_job.

    rows = await _read_image_overrides(client, deployment_id)
    assert rows["server"]["reference"] == TOKEN_IMAGE
    assert rows["server"]["resolvedReference"] == patched_v2
    assert rows["server"]["isApplicable"] is True


# ---------------------------------------------------------------------------
# US4 — a misnamed component container fails loudly (SC-005)
# ---------------------------------------------------------------------------


@pytest.mark.ci
@pytest.mark.api_only(
    reason="asserts operator status and live workload only; no UI flow"
)
async def test_misnamed_container_never_added(
    image_override_environment: dict,
    simple_app_override_images: dict[str, str],
    git_server: dict[str, str],
    vcluster: dict,
    tmp_path: Path,
) -> None:
    """SC-005 / FR-007: on a driver whose ``server`` component container is
    ``wrong-name``, an image override fails the deployment with a message naming
    the component and the container; the live workload keeps its one container
    and the chart image."""
    client: StyrminClient = image_override_environment["client"]
    patched = simple_app_override_images["0.1.0"]

    loaded = await publish_misnamed_simple_app_driver(
        client=client, vcluster=vcluster, git_server=git_server, tmp_path=tmp_path
    )
    assert loaded.application_driver.name == MISNAMED_DRIVER_NAME
    server_config = next(c for c in loaded.component_configs if c.name == "server")
    assert server_config.container == MISNAMED_CONTAINER

    # Without an override no patch is emitted, so the misnamed driver deploys normally.
    task = await client.deployments.create(
        driver=MISNAMED_DRIVER_NAME,
        version="0.1.0",
        environment_id=image_override_environment["environment_id"],
        name="image-override-misnamed",
        service_name_overrides=[
            {"driverServiceName": "simple-app", "overrideName": "simple-app-misnamed"}
        ],
    )
    assert task.deployment_id is not None
    deployment_id = str(task.deployment_id)
    namespace = f"styrmin-{deployment_id}"
    await _wait_for_deployment_status(
        client,
        deployment_id,
        lambda d: d["status"] == "running",
        description="status == running",
    )
    baseline = await _wait_for_server_image(vcluster, namespace, CHART_IMAGE)
    assert [c.name for c in baseline.spec.template.spec.containers] == [
        SERVER_CONTAINER
    ]

    await client.deployments.update(
        deployment_id,
        input=UpdateDeploymentInput(
            components=[ComponentConfigInput(name="server", image=patched)]
        ),
    )
    failed = await _wait_for_deployment_status(
        client,
        deployment_id,
        lambda d: d["status"] == "failed",
        description="status == failed",
        timeout=GUARD_FAILURE_TIMEOUT_SECONDS,
    )

    crd_status = failed["crdStatus"]
    assert crd_status["phase"] == "Failed", crd_status
    message = crd_status["message"]
    assert "Component 'server'" in message, message
    assert f"component container '{MISNAMED_CONTAINER}' was not found" in message, (
        message
    )
    helm_condition = next(
        c for c in crd_status["conditions"] if c["type"] == "HelmReleaseReady"
    )
    assert helm_condition["status"] == "False", helm_condition
    assert helm_condition["reason"] == "ComponentContainerNotFound", helm_condition

    # Nothing was applied: no container added, the chart image still runs.
    apps = kubeclient.AppsV1Api(vcluster["api"])
    workload = await apps.read_namespaced_deployment(SERVER_WORKLOAD, namespace)
    containers = workload.spec.template.spec.containers
    assert [c.name for c in containers] == [SERVER_CONTAINER]
    assert containers[0].image == CHART_IMAGE
