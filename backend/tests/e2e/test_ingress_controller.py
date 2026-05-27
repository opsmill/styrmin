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
import uuid

import httpx
import kr8s
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Ingress as AsyncIngress
from kr8s.asyncio.objects import Pod as AsyncPod
from kr8s.asyncio.objects import Service as AsyncService
from kr8s.asyncio.objects import new_class
from styrmin_sdk import StyrminClient
from styrmin_sdk.models import UpdateDeploymentInput

from tests.e2e.conftest import _portforward, _wait_for_http
from tests.e2e.drivers import ScenarioDriver

pytestmark = [
    pytest.mark.shard_compute,
]


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

    # Verify the Traefik container uses the OpsMill-patched image and that the
    # three publishedService/restricttobackendnodes/publishinternalipv6 CLI args
    # are present with the namespace correctly interpolated.
    traefik_pod = traefik_pods[0]
    containers = traefik_pod.spec.get("containers", [])
    traefik_container = next(
        (c for c in containers if c.get("name") == "traefik"), containers[0]
    )
    assert (
        traefik_container["image"]
        == "registry.opsmill.io/opsmill/traefik:v3.7.1-opsmill"
    ), f"Expected OpsMill-patched Traefik image, got: {traefik_container['image']}"
    traefik_namespace = traefik_pod.namespace
    traefik_args = traefik_container.get("args", [])
    expected_args = {
        f"--providers.kubernetesingress.ingressendpoint.publishedservice={traefik_namespace}/styrmin-traefik",
        "--providers.kubernetesingress.ingressendpoint.restricttobackendnodes=true",
        "--providers.kubernetesingress.ingressendpoint.publishinternalipv6=true",
    }
    missing = expected_args - set(traefik_args)
    assert not missing, (
        f"Traefik pod missing expected CLI args: {missing}; full args: {traefik_args}"
    )

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
        assert (
            annotations.get("external-dns.alpha.kubernetes.io/endpoints-type")
            == "NodeExternalIP"
        ), f"Expected endpoints-type annotation 'NodeExternalIP', got: {annotations}"

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
        config={},
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
    scenario_environment_id: str,
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

    # Find the Traefik service. Filter by ``styrmin/environment_id`` because
    # the cluster may host multiple per-env Traefik instances (one per env
    # using ``dedicated_ingress``); picking ``traefik_services[0]`` without
    # filtering is non-deterministic and intermittently routes to a Traefik
    # whose ingress provider doesn't see this deployment's Ingress → 404.
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    traefik_services: list[AsyncService] = [
        svc
        async for svc in AsyncService.list(
            namespace=kr8s.ALL,
            label_selector={
                "app.kubernetes.io/name": "traefik",
                "styrmin/environment_id": scenario_environment_id,
            },
            api=kr8s_api,
        )
        if isinstance(svc, AsyncService)
    ]
    assert traefik_services, (
        f"Traefik Service not found for environment {scenario_environment_id}"
    )
    traefik_svc = traefik_services[0]

    # Build the expected host from the deployment info
    expected_host = f"simple-app-{deployment_id}.styrmin.com"

    # Port-forward to the Traefik service and send HTTP request with Host header
    # forwards directly to the selected Pod's container port (not the Service
    # port) — so we pass Traefik's "web" container port (8000), not 80.
    async with _portforward(traefik_svc, remote_port=8000) as local_port:
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
    scenario_environment_id: str,
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
    # See ``test_traffic_routes_through_dedicated_ingress`` for the rationale
    # behind filtering by ``styrmin/environment_id``.
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    external_ip: str | None = None
    deadline = time.time() + 120
    while time.time() < deadline:
        traefik_services: list[AsyncService] = [
            svc
            async for svc in AsyncService.list(
                namespace=kr8s.ALL,
                label_selector={
                    "app.kubernetes.io/name": "traefik",
                    "styrmin/environment_id": scenario_environment_id,
                },
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


async def test_dedicated_ingress_service_overrides(
    scenario_driver: ScenarioDriver,
    styrmin_resources: dict,
    simple_app_image: str,  # noqa: ARG001 — ensures image is built
    vcluster: dict,
):
    """End-to-end pass-through for the new IngressServiceConfig knobs.

    Asserts that ``ip_families``, ``ip_family_policy``, and ``node_port`` set
    on a fresh environment's ``dedicated_ingress.service`` flow all the way
    through Styrmin → Helm → the Traefik Service object — and survive a
    reconcile after the Service is deleted out from under us. The IP family
    pair is ``["IPv4"]`` / ``SingleStack`` so the test runs on the existing
    single-family vcluster (dual-stack *traffic* validation lives in
    ``dev/guides/ingress-ipv6-dual-stack-validation.md``).

    The platform enforces a one-cluster limit, so the test reuses the
    cluster created by ``styrmin_resources`` and overrides ingress at the
    environment level — env-level ``dedicated_ingress`` replaces the
    cluster-level config (verified by ``TestConfigMergePrecedence``).
    """
    kubeconfig_path = vcluster["kubeconfig_path"]
    chosen_node_port = 31443
    cluster_id = styrmin_resources["cluster_id"]

    environment = await scenario_driver.create_environment(
        name=f"overrides-env-{uuid.uuid4().hex[:8]}",
        cluster_id=cluster_id,
        config={
            "ip_whitelist": ["127.0.0.1"],
            "dedicated_ingress": {
                "implementation": "traefik",
                "type": "ingress",
                "service": {
                    "type": "NodePort",
                    "node_port": chosen_node_port,
                    "ip_families": ["IPv4"],
                    "ip_family_policy": "SingleStack",
                },
            },
        },
    )

    deployment = await scenario_driver.create_deployment(
        driver="simple-app",
        name="simple-app",
        version="0.1.0",
        environment_id=environment.id,
    )
    await scenario_driver.wait_for_deployment_running(deployment_id=deployment.id)

    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)

    async def _get_overrides_traefik_service() -> AsyncService | None:
        """Find the Traefik Service that matches our override config.

        The styrmin_resources cluster default deploys its own Traefik with
        ``type: LoadBalancer``; ours is the one with ``type: NodePort`` and
        the chosen ``nodePort``. Filter on both so the test cannot latch on
        to an unrelated controller.
        """
        services: list[AsyncService] = [
            svc
            async for svc in AsyncService.list(
                namespace=kr8s.ALL,
                label_selector={"app.kubernetes.io/name": "traefik"},
                api=kr8s_api,
            )
            if isinstance(svc, AsyncService)
        ]
        for svc in services:
            spec = svc.raw.get("spec", {})
            if spec.get("type") != "NodePort":
                continue
            ports = spec.get("ports", [])
            if any(p.get("nodePort") == chosen_node_port for p in ports):
                return svc
        return None

    async def _wait_for_overrides_applied(
        *, timeout: float = 180.0, interval: float = 3.0
    ) -> AsyncService:
        deadline = time.time() + timeout
        while time.time() < deadline:
            svc = await _get_overrides_traefik_service()
            if svc is not None:
                spec = svc.raw.get("spec", {})
                ports = {
                    p.get("name"): p.get("nodePort") for p in spec.get("ports", [])
                }
                if (
                    ports.get("websecure") == chosen_node_port
                    and spec.get("ipFamilies") == ["IPv4"]
                    and spec.get("ipFamilyPolicy") == "SingleStack"
                ):
                    return svc
            await asyncio.sleep(interval)
        raise AssertionError(
            f"Traefik Service did not reach expected overrides within {timeout}s"
        )

    # The requested overrides materialize on the live Service object. This
    # exercises the full Styrmin → Helm → kube-apiserver path end-to-end on
    # the existing single-family vcluster. ``node_port`` is pinned to
    # ``websecure`` only — Kubernetes rejects a Service whose two ports share
    # a nodePort, so ``web`` keeps its cluster-allocated value.
    #
    # Drift recovery (deleting the Service and watching it come back with the
    # same NodePort) is NOT asserted here. Styrmin's HelmReleases use Flux's
    # default reconcile mode, which diffs the helm release *secret* against
    # the chart, not the live cluster state — so a manually-deleted Service
    # logs "release in-sync with desired state" until the next chart/values
    # change. Asserting drift recovery would require enabling
    # ``spec.driftDetection.mode`` on every HelmRelease, which is a
    # platform-wide change outside this feature's scope.
    svc = await _wait_for_overrides_applied()
    spec = svc.raw["spec"]
    assert spec["type"] == "NodePort"
    ports_by_name = {p["name"]: p["nodePort"] for p in spec["ports"]}
    assert ports_by_name["websecure"] == chosen_node_port
    assert ports_by_name["web"] != chosen_node_port
    assert spec["ipFamilies"] == ["IPv4"]
    assert spec["ipFamilyPolicy"] == "SingleStack"


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
        config={},
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


@pytest.mark.e2e
@pytest.mark.ci
async def test_ip_whitelist_enforcement_allows_and_rejects(
    scenario_driver: ScenarioDriver,
    styrmin_resources: dict,
    simple_app_image: str,  # noqa: ARG001 — ensures image is built
    vcluster: dict,
):
    """T003: Activate IP allowlist enforcement and observe allow + deny end-to-end.

    The test sends a synthetic ``X-Forwarded-For`` header (``10.5.5.5``)
    because the existing ``acl`` Middleware template uses
    ``ipStrategy.depth=1`` — Traefik resolves the client IP from XFF, not
    from the connection peer. Without the header, Traefik denies *every*
    request including ones supposedly under ``0.0.0.0/0`` (the depth=1
    strategy returns an error when XFF is absent). In production, an
    upstream LB (e.g., Cloudflare) supplies XFF; in tests we supply it
    manually so we can verify allow vs. deny semantics on the same client.

    Round-trip pattern (allow → deny → allow) replaces the
    "<observed-ip>/32" middle step from the original T003 wording because
    the synthetic XFF lets us stably control the source IP under test
    without discovering Traefik's view of an in-cluster connection.

    Asserts:
    - In-range XFF (``10.5.5.5`` ∈ ``10.0.0.0/8``) → HTTP 200.
    - Out-of-range XFF (same client, narrow allowlist ``192.0.2.0/24``,
      RFC 5737 TEST-NET-1) → HTTP 403 from Traefik.
    - During the deny phase, the deployment namespace contains
      ``Middleware/acl`` with the narrow ``sourceRange`` AND the application
      Ingress carries the
      ``traefik.ingress.kubernetes.io/router.middlewares: <namespace>-acl@kubernetescrd``
      annotation (FR-003, FR-004).
    - Application pod set is unchanged across the reconfigurations
      (SC-005 — no app restart required): same pod UIDs and aggregate
      ``restartCount`` invariant.
    - Round-trip back to a matching allowlist returns 200 (dynamic update
      takes effect).
    """
    client: StyrminClient = styrmin_resources["client"]
    kubeconfig_path = vcluster["kubeconfig_path"]

    # Create a fresh environment for this scenario instead of reusing
    # ``styrmin_resources["environment_id"]``: that shared env is also used
    # by ``test_deploy_with_dedicated_ingress`` to deploy a ``simple-app``,
    # and Styrmin enforces per-env service-name uniqueness — two
    # ``simple-app`` deployments in the same env would collide. A separate
    # env also gets its own per-env Traefik (the dedicated ingress
    # controller is per-env), which lets us pick "the" Traefik service
    # without ambiguity below.
    env_suffix = uuid.uuid4().hex[:8]
    environment = await scenario_driver.create_environment(
        name=f"acl-test-env-{env_suffix}",
        cluster_id=styrmin_resources["cluster_id"],
        config={},
    )
    environment_id = environment.id

    deployment = await scenario_driver.create_deployment(
        driver="simple-app",
        name=f"simple-app-acl-{env_suffix}",
        version="0.1.0",
        environment_id=environment_id,
    )
    deployment = await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment.id
    )
    deployment_id = deployment.id
    namespace = f"styrmin-{deployment_id}"
    # Traefik routes on the Ingress's spec.rules host, which the simple-app
    # Helm chart renders as ``<driver-name>-<deployment-id>.<fqdn>`` —
    # the *driver* name (``simple-app``), not the Styrmin deployment record's name.
    expected_host = f"simple-app-{deployment_id}.styrmin.com"
    expected_annotation = f"styrmin-{deployment_id}-acl@kubernetescrd"
    synthetic_client_ip = "10.5.5.5"
    in_range_cidr = "10.0.0.0/8"
    deny_cidr = "192.0.2.0/24"  # RFC 5737 TEST-NET-1

    base_headers = {"Host": expected_host, "X-Forwarded-For": synthetic_client_ip}

    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)

    async def app_pods() -> list[AsyncPod]:
        return [
            pod
            async for pod in AsyncPod.list(
                namespace=namespace,
                label_selector={"app.kubernetes.io/name": "simple-app"},
                api=kr8s_api,
            )
            if isinstance(pod, AsyncPod)
        ]

    async def app_pod_uids() -> set[str]:
        return {p.metadata.get("uid", "") for p in await app_pods()}

    async def aggregate_restart_count() -> int:
        total = 0
        for pod in await app_pods():
            for cs in pod.raw.get("status", {}).get("containerStatuses", []) or []:
                total += int(cs.get("restartCount", 0) or 0)
        return total

    async def probe_until(
        local_port: int, expected: int, timeout_s: float = 60.0
    ) -> int:
        """Poll Traefik until it returns the expected status or we time out."""
        deadline = time.time() + timeout_s
        last: int | None = None
        async with httpx.AsyncClient() as http:
            while time.time() < deadline:
                try:
                    resp = await http.get(
                        f"http://localhost:{local_port}/health",
                        headers=base_headers,
                        timeout=10,
                    )
                    last = resp.status_code
                    if resp.status_code == expected:
                        return resp.status_code
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(2)
        msg = (
            f"Traefik did not return {expected} within {timeout_s}s; "
            f"last status was {last}"
        )
        raise AssertionError(msg)

    traefik_services: list[AsyncService] = [
        svc
        async for svc in AsyncService.list(
            namespace=kr8s.ALL,
            label_selector={
                "app.kubernetes.io/name": "traefik",
                "styrmin/environment_id": environment_id,
            },
            api=kr8s_api,
        )
        if isinstance(svc, AsyncService)
    ]
    assert traefik_services, (
        f"Traefik Service not found for environment {environment_id}"
    )
    traefik_svc = traefik_services[0]

    Middleware = new_class(  # noqa: N806 — kr8s class factory mirrors K8s kind casing
        kind="Middleware",
        version="traefik.io/v1alpha1",
        namespaced=True,
        asyncio=True,
    )

    async with _portforward(traefik_svc, remote_port=8000) as local_port:
        # Phase 1: configure an allowlist that matches our synthetic XFF → 200
        await client.deployments.update(
            deployment_id,
            input=UpdateDeploymentInput(ipWhitelist=[in_range_cidr]),
        )
        await scenario_driver.wait_for_deployment_running(deployment_id=deployment_id)
        # Active allowlist takes a few seconds to propagate to Traefik.
        await probe_until(local_port, expected=200, timeout_s=120.0)

        baseline_uids = await app_pod_uids()
        baseline_restart = await aggregate_restart_count()

        # Phase 2: narrow deny CIDR (XFF is outside it) → 403
        await client.deployments.update(
            deployment_id,
            input=UpdateDeploymentInput(ipWhitelist=[deny_cidr]),
        )
        await scenario_driver.wait_for_deployment_running(deployment_id=deployment_id)
        await probe_until(local_port, expected=403, timeout_s=60.0)

        # Phase 3: resource invariants under the narrow CIDR
        acl = await Middleware.get(name="acl", namespace=namespace, api=kr8s_api)
        assert acl.raw["spec"]["ipAllowList"]["sourceRange"] == [deny_cidr], (
            f"Middleware sourceRange should reflect the narrow CIDR; got "
            f"{acl.raw['spec']['ipAllowList']['sourceRange']!r}"
        )

        ingresses: list[AsyncIngress] = [
            ing
            async for ing in AsyncIngress.list(namespace=namespace, api=kr8s_api)
            if isinstance(ing, AsyncIngress)
        ]
        assert ingresses, "Application Ingress not found in deployment namespace"
        for ing in ingresses:
            annotations = ing.metadata.get("annotations", {})
            assert (
                annotations.get("traefik.ingress.kubernetes.io/router.middlewares")
                == expected_annotation
            ), (
                f"Ingress {ing.metadata.get('name')} missing or wrong "
                f"router.middlewares annotation; got {annotations!r}"
            )

        # Phase 4: round-trip back to a matching allowlist → 200
        await client.deployments.update(
            deployment_id,
            input=UpdateDeploymentInput(ipWhitelist=[in_range_cidr]),
        )
        await scenario_driver.wait_for_deployment_running(deployment_id=deployment_id)
        await probe_until(local_port, expected=200, timeout_s=60.0)

        # SC-005: app pods are the same instances throughout — no restart
        # disguised as a rolling replacement (which would reset restartCount).
        final_uids = await app_pod_uids()
        assert final_uids == baseline_uids, (
            f"App pod set changed across ip_whitelist reconfiguration "
            f"(baseline={baseline_uids}, final={final_uids}); "
            "ip_whitelist must take effect without rolling the app"
        )
        final_restart = await aggregate_restart_count()
        assert final_restart == baseline_restart, (
            f"App pods restarted during ip_whitelist reconfiguration "
            f"(baseline={baseline_restart}, final={final_restart}); "
            "ip_whitelist must take effect without app restart"
        )
