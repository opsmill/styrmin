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
Neo4j/Prefect/server) in the shard just for these four assertions. The
community and enterprise drivers share the identical ``task-manager`` →
``prefect-server`` subchart, so the enterprise deployment exercises the same
service-discovery + FQDN + ingress machinery this test asserts on. See
``dev/guides/e2e-deployment-sharing.md`` ("Reuse before you boot").
"""

from __future__ import annotations

import asyncio
import time

import httpx
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Ingress as AsyncIngress
from kr8s.asyncio.objects import Service as AsyncService

from tests.e2e.conftest import _portforward, _wait_for_http

# human_readable_fqdn of the task-manager service:
# {service-name}-{environment}.{cluster fqdn_suffix} (see conftest
# styrmin_resources: fqdn_suffix="styrmin.com", environment
# "test-environment"). The enterprise deployment renames only the `infrahub`
# service to `infrahub-enterprise`; the `task-manager` service keeps its
# declared name, so the host is identical to the community driver's.
_PREFECT_UI_HOST = "task-manager-test-environment.styrmin.com"

pytestmark = [
    pytest.mark.shard_infrahub,
]


@pytest.mark.ci
@pytest.mark.api_only(
    reason="Asserts on the service-discovery ClusterIP Service via kr8s and "
    "the Prefect HTTP endpoints; there is no UI flow to exercise."
)
async def test_infrahub_task_manager_service_exposes_prefect_ui(
    deployed_infrahub_enterprise_app: dict,
    vcluster: dict,
) -> None:
    """The ``task-manager`` service resolves to the Prefect UI on port 4200."""
    namespace = deployed_infrahub_enterprise_app["namespace"]
    kubeconfig_path = vcluster["kubeconfig_path"]

    # The service-discovery utility creates the ClusterIP Service
    # asynchronously after the deployment reaches "running", so poll until
    # the `task-manager` Service appears.
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
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
