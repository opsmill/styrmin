import asyncio
import time

import httpx
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Service as AsyncService

from tests.e2e.conftest import (
    _wait_for_http,
)


@pytest.mark.ci
async def test_deploy_simple_app(
    styrmin_resources: dict,
    deployed_simple_app: dict,
    kind_cluster: dict,
) -> None:
    kubeconfig_path = kind_cluster["kubeconfig_path"]
    namespace = deployed_simple_app["namespace"]

    # Find the simple-app service via kr8s
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
    styrmin_resources: dict,
    deployed_simple_app: dict,
    simple_app_image_v2: str,
    kind_cluster: dict,
) -> None:
    from styrmin_sdk import StyrminClient
    from styrmin_sdk.exceptions import StyrminError

    client: StyrminClient = styrmin_resources["client"]
    deployment_id = deployed_simple_app["deployment_id"]
    kubeconfig_path = kind_cluster["kubeconfig_path"]
    namespace = deployed_simple_app["namespace"]

    # Trigger upgrade to version 0.2.0
    await client.deployments.update_version(deployment_id, "0.2.0")

    # Poll deployment status until ready
    deadline = time.time() + 180
    deployment_ready = False
    while time.time() < deadline:
        try:
            deployment = await client.deployments.get(deployment_id)
            if deployment.status in ("deployed", "running"):
                deployment_ready = True
                break
        except StyrminError:
            pass
        await asyncio.sleep(10)

    assert deployment_ready, "Deployment did not reach ready state after upgrade"

    # Find the simple-app service via kr8s
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
        # Wait for the upgraded simple-app to be reachable
        await _wait_for_http(
            f"http://localhost:{local_port}/health",
            timeout=60.0,
            interval=3.0,
        )

        # Verify the /version endpoint returns 0.2.0
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(
                f"http://localhost:{local_port}/version", timeout=10
            )
            assert response.status_code == 200
            data = response.json()
            assert data["version"] == "0.2.0", (
                f"Expected version 0.2.0 but got {data['version']}"
            )
