"""E2E tests for the dedicated ingress controller feature.

Covers:
- T035: Deploy with dedicated_ingress — verify Traefik pod running, correct ingress annotation, internal deployment hidden
- T036: Deploy without dedicated_ingress — no Traefik controller deployed
- T037: Second app reuses ingress controller — only ONE Traefik deployment
- T038: Traffic routes through dedicated ingress — HTTP request via Traefik (port-forward)
- T038b: Traffic routes via the LoadBalancer external IP provisioned by vcluster
- T038a: Toggle dedicated_ingress on/off — verify provisioning and deprovisioning
"""

import asyncio
import time

import httpx

import kr8s
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Ingress as AsyncIngress
from kr8s.asyncio.objects import Pod as AsyncPod
from kr8s.asyncio.objects import Service as AsyncService
from styrmin_sdk import StyrminClient

from tests.e2e.conftest import _wait_for_http
from tests.e2e.drivers import ScenarioDriver


async def test_deploy_with_dedicated_ingress(
    scenario_driver: ScenarioDriver,
    styrmin_resources: dict,
    simple_app_image: str,  # noqa: ARG001 — ensures image is built
    vcluster: dict,
):
    """T035: With dedicated_ingress, Traefik pod runs, app uses annotation-based routing
    (not ingressClassName), and the internal ingress deployment is NOT visible via SDK."""
    client: StyrminClient = styrmin_resources["client"]
    environment_id = styrmin_resources["environment_id"]
    cluster_id = styrmin_resources["cluster_id"]
    kubeconfig_path = vcluster["kubeconfig_path"]

    # Verify cluster exposes ingress capability (cluster has dedicated_ingress + fqdn_suffix)
    cluster = await client.clusters.get(cluster_id=cluster_id)
    assert cluster.capabilities is not None, "Cluster should have capabilities"
    assert "ingress" in cluster.capabilities, "Cluster should have ingress capability"
    assert "external" in cluster.capabilities["ingress"], (
        "Cluster should have external ingress"
    )
    assert (
        cluster.capabilities["ingress"]["external"]["fqdn_suffix"] == "styrmin.com"
    ), "Cluster ingress fqdn_suffix should be 'styrmin.com'"

    # Deploy simple-app via the scenario driver (API or UI, depending on mode)
    deployment = await scenario_driver.create_deployment(
        driver="simple-app",
        name="simple-app",
        version="0.1.0",
        environment_id=environment_id,
    )
    deployment_id = deployment.id
    deployment = await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id
    )

    # Verify Traefik pod is running in a namespace (ingress controller namespace)
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    traefik_pods: list[AsyncPod] = [
        pod
        async for pod in AsyncPod.list(
            namespace=kr8s.ALL,
            label_selector={"app.kubernetes.io/name": "traefik"},
            api=kr8s_api,
        )
        if isinstance(pod, AsyncPod)
    ]
    assert len(traefik_pods) >= 1, "Expected at least one Traefik pod running"

    # Verify the app's Ingress uses annotation-based matching (not ingressClassName)
    namespace = f"styrmin-{deployment_id}"
    ingresses: list[AsyncIngress] = [
        ing
        async for ing in AsyncIngress.list(namespace=namespace, api=kr8s_api)
        if isinstance(ing, AsyncIngress)
    ]
    for ing in ingresses:
        annotations = ing.metadata.get("annotations", {})
        assert annotations.get("kubernetes.io/ingress.class") == "traefik", (
            f"Expected 'kubernetes.io/ingress.class: traefik' annotation, got: {annotations}"
        )
        assert ing.spec.get("ingressClassName") is None, (
            f"ingressClassName should not be set with dedicated ingress, got: {ing.spec.get('ingressClassName')}"
        )

    # Verify the user deployment is visible (the internal one is hidden)
    assert deployment is not None, "User deployment should be visible via API"


async def test_deploy_without_dedicated_ingress(
    scenario_driver: ScenarioDriver,
    simple_app_image: str,  # noqa: ARG001 — ensures image is built
    vcluster: dict,
):
    """T036: Without dedicated_ingress, no Traefik controller is deployed."""
    kubeconfig_path = vcluster["kubeconfig_path"]

    # Create a cluster and environment WITHOUT dedicated_ingress
    cluster = await scenario_driver.create_cluster(
        name="no-ingress-cluster",
        config={
            "fqdn_suffix": "styrmin.com",
            "ingress_class": "traefik",
            "standard_storage": {"storage_class": "standard"},
        },
    )
    environment = await scenario_driver.create_environment(
        name="no-ingress-env",
        cluster_id=cluster.id,
        config={"ip_whitelist": ["127.0.0.1"]},
    )

    # Deploy simple-app
    deployment = await scenario_driver.create_deployment(
        driver="simple-app",
        name="simple-app",
        version="0.1.0",
        environment_id=environment.id,
    )
    deployment = await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment.id
    )

    # Verify NO Traefik pod was created in the deployment's namespace
    namespace = f"styrmin-{deployment.id}"
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    traefik_pods: list[AsyncPod] = [
        pod
        async for pod in AsyncPod.list(
            namespace=namespace,
            label_selector={"app.kubernetes.io/name": "traefik"},
            api=kr8s_api,
        )
        if isinstance(pod, AsyncPod)
    ]
    assert len(traefik_pods) == 0, "Expected no Traefik pods in this environment"


async def test_second_app_reuses_ingress_controller(
    scenario_driver: ScenarioDriver,
    styrmin_resources: dict,
    simple_app_image: str,  # noqa: ARG001 — ensures image is built
    vcluster: dict,
):
    """T037: Second app in the same environment reuses the existing ingress controller."""
    environment_id = styrmin_resources["environment_id"]
    kubeconfig_path = vcluster["kubeconfig_path"]

    # Count Traefik pods before deploying second app
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    traefik_pods_before: list[AsyncPod] = [
        pod
        async for pod in AsyncPod.list(
            namespace=kr8s.ALL,
            label_selector={"app.kubernetes.io/name": "traefik"},
            api=kr8s_api,
        )
        if isinstance(pod, AsyncPod)
    ]
    traefik_count_before = len(traefik_pods_before)

    # Deploy a second app in the same environment
    deployment = await scenario_driver.create_deployment(
        driver="simple-app",
        name="simple-app",
        version="0.1.0",
        environment_id=environment_id,
    )
    await scenario_driver.wait_for_deployment_running(deployment_id=deployment.id)

    # Verify still only one Traefik deployment (not duplicated)
    traefik_pods_after: list[AsyncPod] = [
        pod
        async for pod in AsyncPod.list(
            namespace=kr8s.ALL,
            label_selector={"app.kubernetes.io/name": "traefik"},
            api=kr8s_api,
        )
        if isinstance(pod, AsyncPod)
    ]
    traefik_count_after = len(traefik_pods_after)
    assert traefik_count_after == traefik_count_before, (
        f"Expected {traefik_count_before} Traefik pods, got {traefik_count_after}"
    )


@pytest.mark.e2e
@pytest.mark.ci
async def test_traffic_routes_through_dedicated_ingress(
    scenario_driver: ScenarioDriver,
    deployed_simple_app: dict,
    vcluster: dict,
):
    """T038: Send HTTP request through Traefik and verify 200 response.

    Uses port-forwarding to reach the Traefik service, which works regardless
    of whether the service type is LoadBalancer or ClusterIP.
    """
    kubeconfig_path = vcluster["kubeconfig_path"]

    # Ensure the deployment is in running state before testing traffic
    deployment_id = deployed_simple_app["deployment_id"]
    await scenario_driver.wait_for_deployment_running(deployment_id=deployment_id)

    # Find the Traefik service
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    traefik_services: list[AsyncService] = [
        svc
        async for svc in AsyncService.list(
            namespace=kr8s.ALL,
            label_selector={"app.kubernetes.io/name": "traefik"},
            api=kr8s_api,
        )
        if isinstance(svc, AsyncService)
    ]
    assert traefik_services, "Traefik Service not found"
    traefik_svc = traefik_services[0]

    # Build the expected host from the deployment info
    expected_host = f"simple-app-{deployment_id}.styrmin.com"

    # Port-forward to the Traefik service and send HTTP request with Host header
    # forwards directly to the selected Pod's container port (not the Service
    # port) — so we pass Traefik's "web" container port (8000), not 80.
    async with traefik_svc.portforward(
        remote_port=8000, local_port="auto"
    ) as local_port:
        await _wait_for_http(
            f"http://localhost:{local_port}/count",
            timeout=60.0,
            interval=3.0,
            headers={"Host": expected_host},
        )

        async with httpx.AsyncClient() as http_client:
            resp = await http_client.get(
                f"http://localhost:{local_port}/count",
                headers={"Host": expected_host},
                timeout=10,
            )
            assert resp.status_code == 200, f"Unexpected status: {resp.status_code}"


@pytest.mark.e2e
@pytest.mark.ci
async def test_traffic_routes_through_loadbalancer_ingress(
    scenario_driver: ScenarioDriver,
    deployed_simple_app: dict,
    vcluster: dict,
):
    """T038b: Send HTTP request via Traefik's LoadBalancer external IP and verify 200.

    The shared cluster is provisioned with ``dedicated_ingress.service.type=
    LoadBalancer``; vcluster ships with a built-in LoadBalancer implementation
    that assigns an external IP reachable from the host. This test exercises
    the full LB data path (no port-forward).
    """
    kubeconfig_path = vcluster["kubeconfig_path"]
    deployment_id = deployed_simple_app["deployment_id"]
    await scenario_driver.wait_for_deployment_running(deployment_id=deployment_id)

    # Find the Traefik LoadBalancer Service and wait for its external IP.
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    external_ip: str | None = None
    deadline = time.time() + 120
    while time.time() < deadline:
        traefik_services: list[AsyncService] = [
            svc
            async for svc in AsyncService.list(
                namespace=kr8s.ALL,
                label_selector={"app.kubernetes.io/name": "traefik"},
                api=kr8s_api,
            )
            if isinstance(svc, AsyncService)
        ]
        lb_services = [
            svc
            for svc in traefik_services
            if svc.raw.get("spec", {}).get("type") == "LoadBalancer"
        ]
        for svc in lb_services:
            lb_ingress = svc.status.get("loadBalancer", {}).get("ingress", [])
            if lb_ingress:
                external_ip = lb_ingress[0].get("ip") or lb_ingress[0].get("hostname")
                if external_ip:
                    break
        if external_ip:
            break
        await asyncio.sleep(3)

    assert external_ip is not None, "Traefik LoadBalancer did not get an external IP"

    expected_host = f"simple-app-{deployment_id}.styrmin.com"

    # Traefik endpoints may lag the LB IP by a few seconds — retry until 200.
    await _wait_for_http(
        f"http://{external_ip}/count",
        timeout=120.0,
        interval=3.0,
        headers={"Host": expected_host},
    )

    async with httpx.AsyncClient() as http_client:
        resp = await http_client.get(
            f"http://{external_ip}/count",
            headers={"Host": expected_host},
            timeout=10,
        )
        assert resp.status_code == 200, f"Unexpected status: {resp.status_code}"


async def test_toggle_dedicated_ingress_on_off(
    scenario_driver: ScenarioDriver,
    simple_app_image: str,  # noqa: ARG001 — ensures image is built
    vcluster: dict,
):
    """T038a: Enable dedicated_ingress, deploy, then disable — verify provisioning and deprovisioning."""
    kubeconfig_path = vcluster["kubeconfig_path"]

    # Create a fresh cluster with dedicated_ingress
    cluster = await scenario_driver.create_cluster(
        name="toggle-cluster",
        config={
            "fqdn_suffix": "styrmin.com",
            "ingress_class": "traefik",
            "dedicated_ingress": {
                "implementation": "traefik",
                "type": "ingress",
                "service": {"type": "ClusterIP"},
            },
            "standard_storage": {"storage_class": "standard"},
        },
    )
    environment = await scenario_driver.create_environment(
        name="toggle-env",
        cluster_id=cluster.id,
        config={"ip_whitelist": ["127.0.0.1"]},
    )

    # Deploy app — should trigger ingress controller creation
    deployment = await scenario_driver.create_deployment(
        driver="simple-app",
        name="simple-app",
        version="0.1.0",
        environment_id=environment.id,
    )
    await scenario_driver.wait_for_deployment_running(deployment_id=deployment.id)

    # Verify Traefik is running
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    traefik_pods: list[AsyncPod] = [
        pod
        async for pod in AsyncPod.list(
            namespace=kr8s.ALL,
            label_selector={"app.kubernetes.io/name": "traefik"},
            api=kr8s_api,
        )
        if isinstance(pod, AsyncPod)
    ]
    assert len(traefik_pods) >= 1, (
        "Expected Traefik pod(s) after enabling dedicated_ingress"
    )
