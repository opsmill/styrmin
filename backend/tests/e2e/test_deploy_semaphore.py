import httpx
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Service as AsyncService

from tests.e2e.conftest import (
    _wait_for_http,
)


@pytest.mark.e2e
async def test_deploy_semaphore(
    load_semaphore: dict,
    deployed_semaphore: dict,
    vcluster: dict,
) -> None:
    kubeconfig_path = vcluster["kubeconfig_path"]
    namespace = deployed_semaphore["namespace"]

    # Find the semaphore service via kr8s
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
