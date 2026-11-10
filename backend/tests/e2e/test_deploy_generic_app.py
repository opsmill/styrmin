"""End-to-end coverage for the bundled ``generic-app`` driver.

Deploys ``traefik/whoami``, a one-container HTTP image that listens on port 80
until ``WHOAMI_PORT_NUMBER`` says otherwise. The driver publishes the
application on port 8080, so the page answering there proves the whole path:
the deployment's environment variable reaches the component container, the
driver's Service targets the right port, and the health check passes.

Asserts on the resulting workload, network policies and Ingress, read back from
the vcluster API server, and that both hosts of the Ingress answer 200 through the
dedicated Traefik of the environment (the session cluster has ``dedicated_ingress``).
The Traefik serves only an Ingress with the label ``styrmin/environment_id``, so the
object assertions alone do not show that the Ingress that Styrmin builds is served.

The driver declares its ``app`` service ``scope: external`` and renders no Ingress
of its own (#598, FR-012), so the deployment has exactly one Ingress, the one that
Styrmin builds for the service (SC-006). The test deletes the deployment at the end
and asserts that the Ingress goes with it.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Deployment as AsyncDeployment
from kr8s.asyncio.objects import Ingress as AsyncIngress
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
from tests.e2e.helpers.ingress import traefik_service, wait_for_deployment_status
from tests.e2e.helpers.workloads import container_spec

pytestmark = [
    pytest.mark.shard_general,
]

# Fixed by the generic-app values template's ``fullnameOverride``.
WORKLOAD = "styrmin-app"
WHOAMI_VERSION = "1.10.3"

# The Ingress that Styrmin builds for the ``app`` service (``styrmin-svc-<service name>``).
SERVICE_INGRESS = "styrmin-svc-app"
SERVICE_NAME_LABEL = "styrmin.io/service-name"
# The operator watches the Ingress that Styrmin builds, so kopf adds its own
# bookkeeping annotation. Styrmin's ingress rules do not set it.
OPERATOR_BOOKKEEPING_PREFIX = "kopf.zalando.org/"

# Set by the session fixtures (conftest ``styrmin_resources``): a dedicated ingress
# controller (Traefik) serves the environment, and ``external_dns_endpoints_type`` is
# ``NodeExternalIP``, with no ``ip_whitelist``.
CLUSTER_SUFFIX = "styrmin.com"
DEDICATED_IMPLEMENTATION = "traefik"
# The annotations that the chart Ingress of generic-app carried before it stopped
# rendering one: the post-render patch of Styrmin set them on it (ADR-071).
FORMER_CHART_INGRESS_ANNOTATION_KEYS = {
    "traefik.ingress.kubernetes.io/router.entrypoints",
    "external-dns.alpha.kubernetes.io/hostname",
    "external-dns.alpha.kubernetes.io/cloudflare-proxied",
    "external-dns.alpha.kubernetes.io/endpoints-type",
    "kubernetes.io/ingress.class",
}

# The ``web`` container port of Traefik (the Service port differs).
TRAEFIK_WEB_PORT = 8000
INGRESS_TIMEOUT_SECONDS = 120.0
DELETE_TIMEOUT_SECONDS = 480.0


async def _wait_for_service_ingress(
    kr8s_api: Any, namespace: str
) -> dict[str, dict[str, Any]]:
    """The Ingress objects of the namespace, by name, once the Ingress of the ``app`` service exists.

    The operator creates it on its next periodic reconciliation of the HelmRelease, not
    before the deployment is running, so a single read can come too early.
    """
    deadline = time.monotonic() + INGRESS_TIMEOUT_SECONDS
    while True:
        ingresses = {
            ing.name: dict(ing.raw)
            async for ing in AsyncIngress.list(namespace=namespace, api=kr8s_api)
            if isinstance(ing, AsyncIngress)
        }
        if SERVICE_INGRESS in ingresses or time.monotonic() > deadline:
            return ingresses
        await asyncio.sleep(2)


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

    # Exactly one Ingress, built by Styrmin for the ``app`` service: the chart renders
    # none (FR-012, SC-006).
    ingresses = await _wait_for_service_ingress(kr8s_api, namespace)
    assert set(ingresses) == {SERVICE_INGRESS}, (
        "Expected the Ingress that Styrmin builds for the app service and no chart "
        f"Ingress: {sorted(ingresses)}"
    )
    ingress = ingresses[SERVICE_INGRESS]
    assert ingress["metadata"]["labels"][SERVICE_NAME_LABEL] == "app"
    # The dedicated Traefik of the environment selects Ingresses by this label.
    assert (
        ingress["metadata"]["labels"]["styrmin/environment_id"]
        == scenario_environment_id
    )

    # It carries the application address and the readable host (FR-001, FR-002), as
    # the deployment reports them.
    deployment = await client.deployments.get(str(task.deployment_id))
    (app_service,) = [
        s for s in deployment.deployed_services if s.driver_service_name == "app"
    ]
    assert app_service.primary_fqdn.endswith(f"-{deployment.id}.{CLUSTER_SUFFIX}")
    assert app_service.human_readable_fqdn.startswith("app-")
    assert app_service.human_readable_fqdn.endswith(f".{CLUSTER_SUFFIX}")
    hosts = [rule["host"] for rule in ingress["spec"]["rules"]]
    assert sorted(hosts) == sorted(
        [app_service.primary_fqdn, app_service.human_readable_fqdn]
    ), hosts
    for rule in ingress["spec"]["rules"]:
        (path,) = rule["http"]["paths"]
        assert path["backend"]["service"] == {"name": "app", "port": {"number": 8080}}

    # The resolved class and annotations: the ones the chart Ingress carried before.
    # With the dedicated controller, the class is set in the annotation only.
    annotations = {
        key: value
        for key, value in ingress["metadata"].get("annotations", {}).items()
        if not key.startswith(OPERATOR_BOOKKEEPING_PREFIX)
    }
    assert set(annotations) == FORMER_CHART_INGRESS_ANNOTATION_KEYS, annotations
    assert annotations["kubernetes.io/ingress.class"] == DEDICATED_IMPLEMENTATION
    assert ingress["spec"].get("ingressClassName") is None
    assert annotations["external-dns.alpha.kubernetes.io/hostname"].startswith(
        f"styrmin-{deployment.id}-"
    ), "the host name annotation must carry the release reference"
    assert annotations["external-dns.alpha.kubernetes.io/hostname"].endswith(
        f".{CLUSTER_SUFFIX}"
    )
    assert "tls" not in ingress["spec"]

    # Traffic: both hosts answer through the environment's dedicated Traefik, which routes
    # by the ``Host`` header to the app service (the same path as ``test_infrahub_services.py``).
    traefik = await traefik_service(kr8s_api, scenario_environment_id)
    async with _portforward(traefik, remote_port=TRAEFIK_WEB_PORT) as local_port:
        for host in (app_service.primary_fqdn, app_service.human_readable_fqdn):
            await _wait_for_http(
                f"http://localhost:{local_port}/health",
                timeout=120.0,
                interval=2.0,
                headers={"Host": host},
            )

    # Deleting the deployment deletes its namespace, and the Ingress with it.
    await client.deployments.delete(str(task.deployment_id))
    await wait_for_deployment_status(
        client, str(task.deployment_id), "deleted", timeout=DELETE_TIMEOUT_SECONDS
    )
    remaining = [
        ing.name
        async for ing in AsyncIngress.list(namespace=namespace, api=kr8s_api)
        if isinstance(ing, AsyncIngress)
    ]
    assert remaining == [], f"Ingress left after the deletion: {remaining}"
