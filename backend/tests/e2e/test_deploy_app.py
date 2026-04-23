import httpx
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Service as AsyncService
from tests.e2e.conftest import _wait_for_http
from tests.e2e.drivers import ScenarioDriver


@pytest.mark.ci
async def test_deploy_simple_app(
    scenario_driver: ScenarioDriver,
    scenario_environment_id: str,
    styrmin_resources: dict,  # noqa: ARG001 — transitive: builds cluster/BSL/driver
    simple_app_image: str,  # noqa: ARG001 — required for the image to be built
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

    kubeconfig_path = vcluster["kubeconfig_path"]
    namespace = f"styrmin-{deployment.id}"

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

        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(
                f"http://localhost:{local_port}/version", timeout=10
            )
            assert response.status_code == 200
            data = response.json()
            assert data["version"] == "0.2.0", (
                f"Expected version 0.2.0 but got {data['version']}"
            )
