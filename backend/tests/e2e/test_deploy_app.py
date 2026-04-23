import asyncio
import time

import httpx
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Service as AsyncService
from tests.e2e.conftest import _wait_for_http
from tests.e2e.drivers import ScenarioDriver


@pytest.mark.ci
async def test_deploy_simple_app(
    deployed_simple_app: dict,
    vcluster: dict,
) -> None:
    # Read-only observation of a running simple-app. Reuses the session-
    # scoped deployment (parametrized by driver_mode via
    # ``session_scenario_driver``) instead of deploying per-test — a deploy
    # costs ~30–60s and this test doesn't mutate the running state.
    kubeconfig_path = vcluster["kubeconfig_path"]
    namespace = deployed_simple_app["namespace"]

    # External-state assertion — identical across both entrypoints.
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    services: list[AsyncService] = [
        svc
        async for svc in AsyncService.list(namespace=namespace, api=kr8s_api)
        if isinstance(svc, AsyncService)
    ]
    simple_app_svc = next(
        (
            svc
            for svc in services
            if "simple-app" in svc.name and "postgresql" not in svc.name
        ),
        None,
    )

    assert simple_app_svc, (
        f"Could not find simple-app service. Available services:\n{[svc.name for svc in services]}"
    )

    async with simple_app_svc.portforward(
        remote_port=8000, local_port="auto"
    ) as local_port:
        # Wait for the simple-app to be reachable
        await _wait_for_http(
            f"http://localhost:{local_port}/health",
            timeout=10.0,
            interval=3.0,
        )

        # Check the /count endpoint
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(
                f"http://localhost:{local_port}/count", timeout=10
            )
            assert response.status_code == 200


@pytest.mark.ci
async def test_upgrade_simple_app(
    scenario_driver: ScenarioDriver,
    scenario_environment_id: str,
    styrmin_resources: dict,  # noqa: ARG001 — transitive: builds cluster/BSL/driver
    simple_app_image: str,  # noqa: ARG001 — v0.1.0 image
    simple_app_image_v2: str,  # noqa: ARG001 — v0.2.0 image
    vcluster: dict,
) -> None:
    deployment = await scenario_driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=scenario_environment_id,
    )
    deployment = await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment.id
    )
    namespace = f"styrmin-{deployment.id}"

    await scenario_driver.upgrade_deployment(
        deployment_id=deployment.id, version="0.2.0"
    )
    await scenario_driver.wait_for_deployment_running(deployment_id=deployment.id)

    kubeconfig_path = vcluster["kubeconfig_path"]
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    services: list[AsyncService] = [
        svc
        async for svc in AsyncService.list(namespace=namespace, api=kr8s_api)
        if isinstance(svc, AsyncService)
    ]
    simple_app_svc = next(
        (
            svc
            for svc in services
            if "simple-app" in svc.name and "postgresql" not in svc.name
        ),
        None,
    )

    assert simple_app_svc, (
        f"Could not find simple-app service. Available services:\n{[svc.name for svc in services]}"
    )

    async with simple_app_svc.portforward(
        remote_port=8000, local_port="auto"
    ) as local_port:
        await _wait_for_http(
            f"http://localhost:{local_port}/health",
            timeout=60.0,
            interval=3.0,
        )

        # The operator flips displayState=Running once HelmRelease is Ready,
        # which does not wait for the k8s rolling update to complete. Port-
        # forward may hit an old v0.1.0 pod still in the Service endpoints
        # until the rollout finishes, and requests in flight while a pod
        # terminates surface as ``RemoteProtocolError`` / ``ReadError`` /
        # ``ConnectError``. Poll until the Service returns the new version,
        # treating transport errors as "try again".
        deadline = time.time() + 120.0
        last_version: str | None = None
        async with httpx.AsyncClient() as http_client:
            while time.time() < deadline:
                try:
                    response = await http_client.get(
                        f"http://localhost:{local_port}/version", timeout=10
                    )
                except httpx.HTTPError:
                    await asyncio.sleep(3.0)
                    continue
                if response.status_code != 200:
                    await asyncio.sleep(3.0)
                    continue
                last_version = response.json()["version"]
                if last_version == "0.2.0":
                    break
                await asyncio.sleep(3.0)
            assert last_version == "0.2.0", (
                f"Service still serving {last_version!r} after 120s; "
                "rolling update to 0.2.0 did not complete"
            )
