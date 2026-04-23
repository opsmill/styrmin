import httpx
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Service as AsyncService

from tests.e2e.conftest import (
    _wait_for_http,
)
from tests.e2e.drivers import ScenarioDriver


@pytest.mark.e2e
async def test_deploy_semaphore(
    scenario_driver: ScenarioDriver,
    scenario_environment_id: str,
    load_semaphore: dict,  # noqa: ARG001 — loads the semaphore driver version into the stack
    vcluster: dict,
) -> None:
    deployment = await scenario_driver.create_deployment(
        name="semaphore",
        driver="semaphore",
        version="2.16.47",
        environment_id=scenario_environment_id,
    )
    deployment = await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment.id
    )

    kubeconfig_path = vcluster["kubeconfig_path"]
    namespace = f"styrmin-{deployment.id}"

    # External-state assertion — identical across both entrypoints.
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    services: list[AsyncService] = [
        svc
        async for svc in AsyncService.list(namespace=namespace, api=kr8s_api)
        if isinstance(svc, AsyncService)
    ]
    semaphore_svc = next(
        (
            svc
            for svc in services
            if "semaphore" in svc.name and "postgresql" not in svc.name
        ),
        None,
    )

    assert semaphore_svc, (
        f"Could not find semaphore service. Available services:\n{[svc.name for svc in services]}"
    )

    async with semaphore_svc.portforward(
        remote_port=3000, local_port="auto"
    ) as local_port:
        # Wait for Semaphore to be reachable
        await _wait_for_http(
            f"http://localhost:{local_port}/api/ping",
            timeout=60.0,
            interval=3.0,
        )

        # Verify the /api/ping endpoint
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(
                f"http://localhost:{local_port}/api/ping", timeout=10
            )
            assert response.status_code == 200
