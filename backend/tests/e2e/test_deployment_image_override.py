"""End-to-end coverage for per-component image overrides
(018-component-image-overrides).

Drives the user-facing path: ``set_component_image`` (SDK ``updateDeployment``
or the Settings edit drawer's ``Image for <component>`` input) → server
reconciler → HelmRelease post-render patch on the declared component container
→ rendered pod spec on the vcluster. Asserts on the live workload and on
``Deployment.componentImageOverrides``.

The override images are the simple-app builds re-tagged by the session fixture
``simple_app_override_images`` under ``registry.example/acme/simple-app-patched``;
the vcluster nodes pull them from the host Docker daemon like the base images.
"""

from __future__ import annotations

import uuid
from typing import Any, AsyncGenerator

import pytest
from styrmin_sdk import StyrminClient
from styrmin_sdk._queries import load_query

from tests.e2e.drivers import ScenarioDriver
from tests.e2e.helpers.workloads import (
    _wait_for_pod_template,
    container_spec,
    wait_for_ready_container_image,
)

pytestmark = [
    pytest.mark.shard_configuration,
]

RECONCILE_TIMEOUT_SECONDS = 480.0
SERVER_SELECTOR = "app.kubernetes.io/name=simple-app"
SERVER_CONTAINER = "simple-app"
CHART_IMAGE = "simple-app:0.1.0"


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


@pytest.fixture
def _io_driver_bound(
    image_override_environment: dict,
    image_override_deployment: dict,  # noqa: ARG001 — force fixture ordering
    scenario_driver: ScenarioDriver,
) -> None:
    scenario_driver.attach_to_deployment(
        environment_id=image_override_environment["environment_id"]
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


async def _wait_for_server_image(vcluster: dict, namespace: str, image: str) -> Any:
    return await _wait_for_pod_template(
        vcluster,
        namespace=namespace,
        label_selector=SERVER_SELECTOR,
        predicate=lambda d: _server_image(d) == image,
        description=f"{SERVER_CONTAINER} container image == {image}",
    )


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
    and the read surface shows the override applied."""
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

    # Clear half (US3): added by T054.
