"""E2E test: the infrahub driver exposes the Prefect UI as a service (#273).

The infrahub driver declares a ``task-manager`` service (port 4200, component
``task-manager``) so the Prefect UI is reachable through the service-discovery
ClusterIP Service instead of manual port-forwarding to the chart's own
``styrmin-task-manager`` Service.

Deployment reuse
----------------
This is a **read-only** assertion on an already-deployed Infrahub stack, so it
piggybacks on the session-scoped ``deployed_infrahub_enterprise_app`` fixture —
the same stack that ``test_infrahub_enterprise_backup_and_restore_lifecycle``
already boots in the ``shard_infrahub`` shard. It deliberately does **not**
consume ``deployed_infrahub_app`` (the community stack): that fixture's only
other consumer (the community backup/restore test) is ``@pytest.mark.skip``,
so depending on it would resurrect a second full Infrahub boot (~600s +
Neo4j/Prefect/server) in the shard just for these read-only assertions. The
community and enterprise drivers share the identical ``task-manager`` →
``prefect-server`` subchart, so the enterprise deployment exercises the same
service-discovery + FQDN + ingress machinery this test asserts on. See
``dev/guides/e2e-deployment-sharing.md`` ("Reuse before you boot").
"""

from __future__ import annotations

import asyncio
import time

from typing import Any

import httpx
import kr8s
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Deployment as AsyncDeployment
from kr8s.asyncio.objects import Ingress as AsyncIngress
from kr8s.asyncio.objects import Pod as AsyncPod
from kr8s.asyncio.objects import Service as AsyncService

from tests.e2e.conftest import _portforward, _wait_for_http

# human_readable_fqdn of the task-manager service:
# {service-name}-{environment}.{cluster fqdn_suffix} (see conftest
# styrmin_resources: fqdn_suffix="styrmin.com", environment
# "test-environment"). The enterprise deployment renames only the `infrahub`
# service to `infrahub-enterprise`; the `task-manager` service keeps its
# declared name, so the host is identical to the community driver's.
_PREFECT_UI_HOST = "task-manager-test-environment.styrmin.com"

# The task-manager component's workload and its declared component container.
_TASK_MANAGER_DEPLOYMENT = "styrmin-task-manager"
_TASK_MANAGER_CONTAINER = "prefect-server"

pytestmark = [
    pytest.mark.shard_infrahub,
]


async def _ready_task_manager_pods(
    kr8s_api: Any, namespace: str, timeout: float = 300.0
) -> list[AsyncPod]:
    """Wait until the task-manager Deployment is fully rolled out and return its pods."""
    deadline = time.time() + timeout
    last_seen = "Deployment not found"
    while time.time() < deadline:
        try:
            deployment = await AsyncDeployment.get(
                _TASK_MANAGER_DEPLOYMENT, namespace=namespace, api=kr8s_api
            )
        except kr8s.NotFoundError:
            await asyncio.sleep(5)
            continue
        replicas = deployment.spec.get("replicas", 1)
        status = deployment.status
        pods = [
            pod
            async for pod in AsyncPod.list(
                namespace=namespace,
                label_selector=dict(deployment.spec["selector"]["matchLabels"]),
                api=kr8s_api,
            )
            if isinstance(pod, AsyncPod)
        ]
        ready = [pod for pod in pods if await pod.ready()]
        if (
            status.get("updatedReplicas") == replicas
            and status.get("readyReplicas") == replicas
            and len(ready) == len(pods) == replicas
        ):
            return ready
        last_seen = f"{len(ready)}/{len(pods)} pods Ready, {replicas} replica(s) wanted"
        await asyncio.sleep(5)
    raise AssertionError(
        f"{_TASK_MANAGER_DEPLOYMENT} did not become Ready within {timeout}s: {last_seen}"
    )


def _container_env(pod: AsyncPod, container: str) -> dict[str, dict[str, Any]]:
    for spec in pod.spec["containers"]:
        if spec["name"] == container:
            return {entry["name"]: dict(entry) for entry in spec.get("env", [])}
    raise AssertionError(f"Pod {pod.name} has no {container!r} container")


@pytest.mark.ci
@pytest.mark.api_only(
    reason="Asserts on the service-discovery ClusterIP Service via kr8s and "
    "the Prefect HTTP endpoints; there is no UI flow to exercise."
)
async def test_infrahub_task_manager_service_exposes_prefect_ui(
    deployed_infrahub_enterprise_app: dict,
    styrmin_resources: dict,
    vcluster: dict,
) -> None:
    """The ``task-manager`` service resolves to the Prefect UI on port 4200.

    Covers the full #273 exposure path: the service-discovery ClusterIP
    Service, direct reachability of the Prefect UI/API behind it, the
    per-environment Ingress object, and — end to end — that the Prefect UI is
    actually reachable *through the dedicated ingress controller* (Traefik),
    not just that the Ingress object exists.

    Also covers 017 SC-003: with the driver no longer overriding
    ``prefect-server.server.env``, the task manager is Ready and keeps the
    chart's env defaults alongside the driver's analytics flag.
    """
    namespace = deployed_infrahub_enterprise_app["namespace"]
    environment_id = styrmin_resources["environment_id"]
    kubeconfig_path = vcluster["kubeconfig_path"]
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)

    for pod in await _ready_task_manager_pods(kr8s_api, namespace):
        env = _container_env(pod, _TASK_MANAGER_CONTAINER)
        assert env.get("PREFECT_UI_SERVE_BASE", {}).get("value") == "/", (
            f"Chart default PREFECT_UI_SERVE_BASE=/ missing on {pod.name}: "
            f"{env.get('PREFECT_UI_SERVE_BASE')}"
        )
        # Driver parameter `enable_analytics` defaults to true.
        analytics = env.get("PREFECT_SERVER_ANALYTICS_ENABLED")
        assert analytics is not None, (
            f"PREFECT_SERVER_ANALYTICS_ENABLED missing on {pod.name}: {sorted(env)}"
        )
        assert str(analytics.get("value")).lower() == "true", analytics

    # The service-discovery utility creates the ClusterIP Service
    # asynchronously after the deployment reaches "running", so poll until
    # the `task-manager` Service appears.
    task_manager_svc = None
    services: list[AsyncService] = []
    svc_deadline = time.time() + 120
    while time.time() < svc_deadline:
        services = [
            svc
            async for svc in AsyncService.list(namespace=namespace, api=kr8s_api)
            if isinstance(svc, AsyncService)
        ]
        task_manager_svc = next(
            (svc for svc in services if svc.name == "task-manager"),
            None,
        )
        if task_manager_svc is not None:
            break
        await asyncio.sleep(5)

    assert task_manager_svc, (
        "Could not find the service-discovery 'task-manager' Service. "
        f"Available: {[svc.name for svc in services]}"
    )

    port_spec = task_manager_svc.spec["ports"][0]
    assert port_spec["port"] == 4200
    assert port_spec["targetPort"] == 4200

    async with _portforward(task_manager_svc, remote_port=4200) as local_port:
        # Prefect API health endpoint behind the same service.
        await _wait_for_http(
            f"http://localhost:{local_port}/api/health",
            timeout=120.0,
            interval=5.0,
        )

        # The UI root serves the Prefect single-page app.
        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://localhost:{local_port}/", timeout=10)
        assert response.status_code == 200
        assert "html" in response.headers.get("content-type", "")

    # The prefect-server subchart ingress (enabled in values.j2.yml) routes
    # the service-scoped human-readable FQDN to the Prefect UI through the
    # per-environment ingress, mirroring the infrahub server ingress.
    ingresses: list[AsyncIngress] = [
        ing
        async for ing in AsyncIngress.list(namespace=namespace, api=kr8s_api)
        if isinstance(ing, AsyncIngress)
    ]
    ingress_hosts = {
        rule["host"]
        for ing in ingresses
        for rule in ing.spec.get("rules", [])
        if "host" in rule
    }
    assert _PREFECT_UI_HOST in ingress_hosts, (
        f"Expected Prefect UI ingress host '{_PREFECT_UI_HOST}'. "
        f"Ingress hosts found: {sorted(ingress_hosts)}"
    )

    # Finally, prove the Prefect UI is actually reachable *through the
    # per-environment ingress controller* — not merely that the Ingress object
    # exists. Styrmin post-render-patches every `kind: Ingress` in the release
    # with `kubernetes.io/ingress.class: traefik` (see IngressUtility), so the
    # subchart's Prefect ingress is picked up by the dedicated Traefik. Route
    # an HTTP request through that Traefik with the Host header set to the
    # Prefect UI FQDN, mirroring test_traffic_routes_through_dedicated_ingress.
    #
    # The Traefik controller runs in its own namespace (one per env using
    # dedicated_ingress), so search cluster-wide and filter by the
    # environment_id label the enterprise deployment was created under.
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

    # Port-forward targets Traefik's "web" container port (8000), not the
    # Service port; the shared cluster uses external_url_scheme=http. The
    # Prefect ingress path is `/`, so both the SPA root and the API under
    # `/api` route through the same host.
    async with _portforward(traefik_svc, remote_port=8000) as local_port:
        await _wait_for_http(
            f"http://localhost:{local_port}/api/health",
            timeout=120.0,
            interval=5.0,
            headers={"Host": _PREFECT_UI_HOST},
        )

        async with httpx.AsyncClient() as http_client:
            resp = await http_client.get(
                f"http://localhost:{local_port}/",
                headers={"Host": _PREFECT_UI_HOST},
                timeout=10,
            )
        assert resp.status_code == 200, (
            "Prefect UI not reachable through the ingress controller "
            f"(Host: {_PREFECT_UI_HOST}): HTTP {resp.status_code}"
        )
        assert "html" in resp.headers.get("content-type", "")
