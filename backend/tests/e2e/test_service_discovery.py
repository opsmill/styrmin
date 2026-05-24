"""E2E test: DNS resolution between services (T041).

Deploy simple-app twice with service name overrides 'intent' and 'executor'.
Call executor's /probe?target=intent endpoint and verify DNS resolution and
HTTP connectivity between the two instances.
"""

import asyncio
import time

import httpx
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Service as AsyncService

from tests.e2e.conftest import _portforward, _wait_for_http
from tests.e2e.drivers import ScenarioDriver

pytestmark = [
    pytest.mark.shard_general,
]


@pytest.mark.ci
async def test_service_discovery_between_apps(
    scenario_driver: ScenarioDriver,
    scenario_environment_id: str,
    styrmin_resources: dict,  # noqa: ARG001 — transitive: cluster/BSL/driver
    simple_app_image: str,  # noqa: ARG001 — ensures image is built
    vcluster: dict,
) -> None:
    """Deploy two simple-app instances and verify they can discover each other via DNS."""
    kubeconfig_path = vcluster["kubeconfig_path"]

    intent = await scenario_driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=scenario_environment_id,
        service_name_overrides=[
            {"driverServiceName": "simple-app", "overrideName": "intent"}
        ],
    )
    executor = await scenario_driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=scenario_environment_id,
        service_name_overrides=[
            {"driverServiceName": "simple-app", "overrideName": "executor"}
        ],
    )

    # Wait for both deployments to be running
    await scenario_driver.wait_for_deployment_running(
        deployment_id=intent.id, timeout=300.0
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=executor.id, timeout=300.0
    )

    # Find the executor service via kr8s.
    # The service-discovery utility creates the service asynchronously after
    # the deployment reaches "running", so we need to poll until it appears.
    executor_namespace = f"styrmin-{executor.id}"
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    executor_svc = None
    svc_deadline = time.time() + 120
    while time.time() < svc_deadline:
        services: list[AsyncService] = [
            svc
            async for svc in AsyncService.list(
                namespace=executor_namespace, api=kr8s_api
            )
            if isinstance(svc, AsyncService)
        ]
        executor_svc = next(
            (
                svc
                for svc in services
                if "executor" in svc.name and "postgresql" not in svc.name
            ),
            None,
        )
        if executor_svc is not None:
            break
        await asyncio.sleep(5)

    assert executor_svc, (
        f"Could not find executor service. Available: {[svc.name for svc in services]}"
    )

    async with _portforward(executor_svc, remote_port=8000) as local_port:
        await _wait_for_http(
            f"http://localhost:{local_port}/health",
            timeout=30.0,
            interval=3.0,
        )

        # Probe the intent service via short DNS name from the executor pod.
        # Retry because the ExternalName alias DNS may take a few seconds to
        # propagate after the service resource is created.
        async with httpx.AsyncClient() as http_client:
            probe_deadline = time.time() + 60
            while True:
                response = await http_client.get(
                    f"http://localhost:{local_port}/probe",
                    params={"target": "http://intent:8000/health"},
                    timeout=10,
                )
                assert response.status_code == 200
                data = response.json()
                if data["status"] == 200:
                    break
                if time.time() >= probe_deadline:
                    assert data["status"] == 200, (
                        f"Expected HTTP 200, got {data['status']}: {data['body']}"
                    )
                await asyncio.sleep(3)


@pytest.mark.api_only(
    reason="Rename flow drives SDK calls + kubectl/kr8s only; the "
    "[ui-chromium] variant would just re-run the same SDK call.",
)
@pytest.mark.ci
async def test_service_rename_creates_new_kubernetes_service(
    scenario_driver: ScenarioDriver,
    scenario_environment_id: str,
    styrmin_resources: dict,  # noqa: ARG001 — transitive: cluster/BSL/driver
    simple_app_image: str,  # noqa: ARG001 — ensures image is built
    vcluster: dict,
) -> None:
    """#237: renaming a deployed service must create the new Service object."""
    kubeconfig_path = vcluster["kubeconfig_path"]

    dep = await scenario_driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=scenario_environment_id,
        service_name_overrides=[
            {"driverServiceName": "simple-app", "overrideName": "before-rename"}
        ],
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=dep.id, timeout=300.0
    )

    namespace = f"styrmin-{dep.id}"
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)

    # Pre-rename: Service "before-rename" exists.
    before = await _find_service(kr8s_api, namespace, "before-rename")
    assert before is not None, "Pre-rename Service should exist"

    # Trigger the rename via the same path that #237 broke.
    await scenario_driver.update_deployment(
        deployment_id=dep.id,
        config={
            "service_name_overrides": [
                {"driverServiceName": "simple-app", "overrideName": "after-rename"}
            ]
        },
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=dep.id, timeout=300.0
    )

    # Post-rename: Service "after-rename" exists. Without the #237 fix this
    # is the assertion that fails — the K8s Service for the new name is
    # never created.
    after_deadline = time.time() + 120
    after = None
    while time.time() < after_deadline:
        after = await _find_service(kr8s_api, namespace, "after-rename")
        if after is not None:
            break
        await asyncio.sleep(5)
    assert after is not None, (
        "Post-rename Service 'after-rename' was never created. "
        "This is #237 regressing — the new instance's context did not "
        "include the renamed service."
    )


async def _find_service(
    kr8s_api: kr8s.asyncio.Api, namespace: str, name_substring: str
) -> AsyncService | None:
    services: list[AsyncService] = [
        svc
        async for svc in AsyncService.list(namespace=namespace, api=kr8s_api)
        if isinstance(svc, AsyncService)
    ]
    return next(
        (
            svc
            for svc in services
            if name_substring in svc.name and "postgresql" not in svc.name
        ),
        None,
    )
