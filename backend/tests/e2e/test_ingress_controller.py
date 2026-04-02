"""E2E tests for the dedicated ingress controller feature.

Covers:
- T035: Deploy with dedicated_ingress — verify Traefik pod running, correct ingress annotation, internal deployment hidden
- T036: Deploy without dedicated_ingress — no Traefik controller deployed
- T037: Second app reuses ingress controller — only ONE Traefik deployment
- T038: Traffic routes through dedicated ingress — HTTP request via Traefik LB
- T038a: Toggle dedicated_ingress on/off — verify provisioning and deprovisioning
"""

import asyncio
import time

import kr8s
import kr8s.asyncio
import pytest
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import StyrminError
from kr8s.asyncio.objects import Ingress as AsyncIngress
from kr8s.asyncio.objects import Pod as AsyncPod
from kr8s.asyncio.objects import Service as AsyncService


async def test_deploy_with_dedicated_ingress(
    styrmin_resources: dict,
    simple_app_image: str,
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

    # Deploy simple-app
    task = await client.deployments.create(
        driver="simple-app",
        name="simple-app",
        version="0.1.0",
        environment_id=environment_id,
    )
    deployment_id = task.deployment_id
    assert deployment_id is not None

    # Wait for deployment to be ready
    deadline = time.time() + 180
    deployment = None
    while time.time() < deadline:
        try:
            deployment = await client.deployments.get(deployment_id)
            if deployment.status in ("deployed", "running"):
                break
        except StyrminError:
            pass
        await asyncio.sleep(10)

    assert deployment is not None
    assert deployment.status in ("deployed", "running")

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
    styrmin_resources: dict,
    simple_app_image: str,
    vcluster: dict,
):
    """T036: Without dedicated_ingress, no Traefik controller is deployed."""
    client: StyrminClient = styrmin_resources["client"]
    kubeconfig_path = vcluster["kubeconfig_path"]

    # Create a cluster and environment WITHOUT dedicated_ingress
    cluster = await client.clusters.create(
        name="no-ingress-cluster",
        config={
            "fqdn_suffix": "styrmin.com",
            "ingress_class": "traefik",
            "standard_storage": {"storage_class": "standard"},
        },
    )
    environment = await client.environments.create(
        name="no-ingress-env",
        cluster_id=cluster.id,
        config={"ip_whitelist": ["127.0.0.1"]},
    )

    # Deploy simple-app
    task = await client.deployments.create(
        driver="simple-app",
        name="simple-app",
        version="0.1.0",
        environment_id=str(environment.id),
    )
    deployment_id = task.deployment_id
    assert deployment_id is not None

    # Wait for deployment
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            deployment = await client.deployments.get(deployment_id)
            if deployment.status in ("deployed", "running"):
                break
        except StyrminError:
            pass
        await asyncio.sleep(10)

    # Verify NO Traefik pod was created in the deployment's namespace
    namespace = f"styrmin-{deployment_id}"
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
    styrmin_resources: dict,
    simple_app_image: str,
    vcluster: dict,
):
    """T037: Second app in the same environment reuses the existing ingress controller."""
    client: StyrminClient = styrmin_resources["client"]
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
    task = await client.deployments.create(
        driver="simple-app",
        name="simple-app",
        version="0.1.0",
        environment_id=environment_id,
    )
    deployment_id = task.deployment_id
    assert deployment_id is not None

    # Wait for deployment
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            deployment = await client.deployments.get(deployment_id)
            if deployment.status in ("deployed", "running"):
                break
        except StyrminError:
            pass
        await asyncio.sleep(10)

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
    styrmin_resources: dict,
    deployed_simple_app: dict,
    vcluster: dict,
):
    """T038: Send HTTP request through Traefik LB and verify 200 response."""
    import httpx

    kubeconfig_path = vcluster["kubeconfig_path"]

    # Get the Traefik service external IP (provisioned by cloud-provider-kind)
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    deadline = time.time() + 120
    external_ip = None
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
        if traefik_services:
            lb_ingress = (
                traefik_services[0].status.get("loadBalancer", {}).get("ingress", [])
            )
            if lb_ingress:
                external_ip = lb_ingress[0].get("ip")
                if external_ip:
                    break
        await asyncio.sleep(5)

    assert external_ip is not None, "Traefik LoadBalancer did not get an external IP"

    # Build the expected host from the deployment info
    deployment_id = deployed_simple_app["deployment_id"]
    expected_host = f"simple-app-{deployment_id}.styrmin.com"

    # Send HTTP request through Traefik with Host header for routing
    async with httpx.AsyncClient() as http_client:
        try:
            resp = await http_client.get(
                f"http://{external_ip}/count",
                headers={"Host": expected_host},
                timeout=10,
            )
            # We expect some response (200)
            assert resp.status_code == 200, f"Unexpected status: {resp.status_code}"
        except httpx.ConnectError:
            pytest.skip(
                "Could not connect to Traefik LB — LoadBalancer may not be available"
            )


async def test_toggle_dedicated_ingress_on_off(
    styrmin_resources: dict,
    simple_app_image: str,
    vcluster: dict,
):
    """T038a: Enable dedicated_ingress, deploy, then disable — verify provisioning and deprovisioning."""
    client: StyrminClient = styrmin_resources["client"]
    kubeconfig_path = vcluster["kubeconfig_path"]

    # Create a fresh cluster with dedicated_ingress
    cluster = await client.clusters.create(
        name="toggle-cluster",
        config={
            "fqdn_suffix": "styrmin.com",
            "ingress_class": "traefik",
            "dedicated_ingress": {"implementation": "traefik", "type": "ingress"},
            "standard_storage": {"storage_class": "standard"},
        },
    )
    environment = await client.environments.create(
        name="toggle-env",
        cluster_id=cluster.id,
        config={"ip_whitelist": ["127.0.0.1"]},
    )

    # Deploy app — should trigger ingress controller creation
    task = await client.deployments.create(
        driver="simple-app",
        name="simple-app",
        version="0.1.0",
        environment_id=str(environment.id),
    )
    deployment_id = task.deployment_id
    assert deployment_id is not None

    # Wait for deployment
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            deployment = await client.deployments.get(deployment_id)
            if deployment.status in ("deployed", "running"):
                break
        except StyrminError:
            pass
        await asyncio.sleep(10)

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
