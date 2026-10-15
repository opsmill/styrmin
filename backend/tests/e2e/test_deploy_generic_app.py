"""End-to-end coverage for the bundled ``generic-app`` driver.

Deploys ``traefik/whoami``, a one-container HTTP image that listens on port 80
until ``WHOAMI_PORT_NUMBER`` says otherwise. The driver publishes the
application on port 8080, so the page answering there proves the whole path:
the deployment's environment variable reaches the component container, the
driver's Service targets the right port, and the health check passes.

Asserts on the resulting workload and network policies, read back from the
vcluster API server.
"""

from __future__ import annotations

import httpx
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Deployment as AsyncDeployment
from kr8s.asyncio.objects import NetworkPolicy as AsyncNetworkPolicy
from kr8s.asyncio.objects import Service as AsyncService
from styrmin_sdk import StyrminClient
from styrmin_sdk.models import (
    ComponentConfigInput,
    DeploymentConfigInput,
    EnvVarInput,
    ParameterValueInput,
)

from tests.e2e.conftest import _portforward, _wait_for_http
from tests.e2e.drivers import ScenarioDriver
from tests.e2e.helpers.workloads import container_spec

pytestmark = [
    pytest.mark.shard_general,
]

# Fixed by the generic-app values template's ``fullnameOverride``.
WORKLOAD = "styrmin-app"
WHOAMI_VERSION = "1.10.3"


@pytest.mark.api_only(
    reason="Creates the deployment with a typed configuration and reads the "
    "workload back with kr8s; the [ui-chromium] variant would re-run the same SDK call.",
)
@pytest.mark.e2e
async def test_deploy_generic_app(
    scenario_driver: ScenarioDriver,
    scenario_environment_id: str,
    load_generic_app: dict,  # noqa: ARG001 — loads the generic-app driver version into the stack
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    vcluster: dict,
) -> None:
    _, client = session_scenario_driver
    scenario_driver.attach_to_deployment(environment_id=scenario_environment_id)

    task = await client.deployments.create(
        driver="generic-app",
        version=WHOAMI_VERSION,
        environment_id=scenario_environment_id,
        name="whoami",
        parameters=[
            ParameterValueInput(name="image_repository", value="traefik/whoami"),
            ParameterValueInput(name="image_tag", value=f"v{WHOAMI_VERSION}"),
            ParameterValueInput(name="health_path", value="/health"),
        ],
        config=DeploymentConfigInput(
            components=[
                ComponentConfigInput(
                    name="app",
                    env_vars=[EnvVarInput(name="WHOAMI_PORT_NUMBER", value="8080")],
                )
            ]
        ),
    )
    deployment = await scenario_driver.wait_for_deployment_running(
        deployment_id=str(task.deployment_id)
    )
    namespace = f"styrmin-{deployment.id}"
    kr8s_api = await kr8s.asyncio.api(kubeconfig=vcluster["kubeconfig_path"])

    # The workload carries the component label and the deployment's env var,
    # and rolls out in place because the deployment has no volume.
    workload = await AsyncDeployment.get(WORKLOAD, namespace=namespace, api=kr8s_api)
    assert workload.metadata.labels["styrmin/component"] == "app"
    container = container_spec(workload, "app")
    assert container is not None, "the pod template has no container named app"
    assert {e.name: e.value for e in container.env or []}[
        "WHOAMI_PORT_NUMBER"
    ] == "8080"
    assert workload.spec.strategy.type == "RollingUpdate"

    # The application answers on the driver's port through the Service.
    service = await AsyncService.get(WORKLOAD, namespace=namespace, api=kr8s_api)
    async with _portforward(service, remote_port=8080) as local_port:
        await _wait_for_http(f"http://localhost:{local_port}/health")
        async with httpx.AsyncClient() as http:
            response = await http.get(f"http://localhost:{local_port}/", timeout=10)
        assert response.status_code == 200
        assert "Hostname:" in response.text

    # The driver declares the policies that let the environment's applications
    # reach each other (Styrmin's own policies only admit its ingress controller).
    policies = {
        policy.name
        async for policy in AsyncNetworkPolicy.list(namespace=namespace, api=kr8s_api)
    }
    assert {f"{WORKLOAD}-ingress", f"{WORKLOAD}-egress"} <= policies, sorted(policies)
