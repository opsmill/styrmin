"""E2E test: DNS resolution between services (T041).

Deploy simple-app twice with service name overrides 'intent' and 'executor'.
Call executor's /probe?target=intent endpoint and verify DNS resolution and
HTTP connectivity between the two instances. Renaming 'executor' must create
its new Service and replace its alias in the 'intent' namespace (#237, #491).
Deleting 'intent' must delete its alias in the 'executor' namespace (#503).
That test runs last, because the other tests use 'intent'.
"""

import asyncio
import time

import httpx
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Pod as AsyncPod
from kr8s.asyncio.objects import Service as AsyncService

from styrmin_sdk import StyrminClient

from tests.e2e.conftest import _portforward, _wait_for_http
from tests.e2e.drivers import ScenarioDriver
from tests.e2e.helpers.ingress import wait_for_deployment_status

pytestmark = [
    pytest.mark.shard_general,
]


@pytest.fixture(scope="module")
async def discovery_deployments(
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    scenario_environment_id: str,
    simple_app_image: str,  # noqa: ARG001 — ensures image is built
) -> dict[str, str]:
    """Running ``intent`` and ``executor`` simple-apps, shared by both tests.

    Created through the session driver, so the UI variant still drives the
    deploy form; the api-only rename test reuses ``executor``.
    """
    driver, _ = session_scenario_driver
    ids: dict[str, str] = {}
    for name in ("intent", "executor"):
        deployment = await driver.create_deployment(
            driver="simple-app",
            version="0.1.0",
            environment_id=scenario_environment_id,
            service_name_overrides=[
                {"driverServiceName": "simple-app", "overrideName": name}
            ],
        )
        ids[name] = deployment.id
    for deployment_id in ids.values():
        await driver.wait_for_deployment_running(
            deployment_id=deployment_id, timeout=300.0
        )
    return ids


@pytest.mark.ci
async def test_service_discovery_between_apps(
    discovery_deployments: dict[str, str],
    vcluster: dict,
) -> None:
    """Two simple-app instances can discover each other via DNS."""
    kubeconfig_path = vcluster["kubeconfig_path"]

    # Target the executor pod, not its Service: the rename test renames that
    # Service, so the two tests must not depend on each other's order.
    executor_namespace = f"styrmin-{discovery_deployments['executor']}"
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    executor_pod = None
    pod_deadline = time.time() + 120
    while time.time() < pod_deadline:
        async for pod in AsyncPod.list(
            namespace=executor_namespace,
            label_selector="app.kubernetes.io/name=simple-app",
            api=kr8s_api,
        ):
            if (
                isinstance(pod, AsyncPod)
                and not pod.metadata.get("deletionTimestamp")
                and await pod.ready()
            ):
                executor_pod = pod
                break
        if executor_pod is not None:
            break
        await asyncio.sleep(5)

    assert executor_pod, f"No ready simple-app pod in {executor_namespace}"

    async with _portforward(executor_pod, remote_port=8000) as local_port:
        await _wait_for_http(
            f"http://localhost:{local_port}/health",
            timeout=30.0,
            interval=3.0,
        )

        # Probe the intent service via short DNS name from the executor pod.
        # Retry because the ExternalName alias DNS may take a few seconds to
        # propagate after the service resource is created.
        async with httpx.AsyncClient() as http_client:
            probe_deadline = time.time() + 60
            while True:
                response = await http_client.get(
                    f"http://localhost:{local_port}/probe",
                    params={"target": "http://intent:8000/health"},
                    timeout=10,
                )
                assert response.status_code == 200
                data = response.json()
                if data["status"] == 200:
                    break
                if time.time() >= probe_deadline:
                    assert data["status"] == 200, (
                        f"Expected HTTP 200, got {data['status']}: {data['body']}"
                    )
                await asyncio.sleep(3)


@pytest.mark.api_only(
    reason="Rename flow drives SDK calls + kubectl/kr8s only; the "
    "[ui-chromium] variant would just re-run the same SDK call.",
)
@pytest.mark.ci
async def test_service_rename_creates_new_kubernetes_service(
    scenario_driver: ScenarioDriver,
    discovery_deployments: dict[str, str],
    vcluster: dict,
) -> None:
    """#237: renaming a deployed service must create the new Service object.

    #491: the alias in the peer namespace follows the rename, and the alias
    with the old name is deleted.
    """
    kubeconfig_path = vcluster["kubeconfig_path"]
    deployment_id = discovery_deployments["executor"]
    namespace = f"styrmin-{deployment_id}"
    peer_namespace = f"styrmin-{discovery_deployments['intent']}"
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)

    # Pre-rename: Service "executor" exists, and its alias in the peer namespace.
    before = await _find_service(kr8s_api, namespace, "executor")
    assert before is not None, "Pre-rename Service should exist"
    aliases = await _wait_for_alias_names(
        kr8s_api, peer_namespace, deployment_id, {"executor"}
    )
    assert aliases == {"executor"}, f"Pre-rename aliases: {sorted(aliases)}"

    # Trigger the rename via the same path that #237 broke.
    await scenario_driver.update_deployment(
        deployment_id=deployment_id,
        config={
            "service_name_overrides": [
                {"driverServiceName": "simple-app", "overrideName": "after-rename"}
            ]
        },
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=300.0
    )

    # Post-rename: Service "after-rename" exists. Without the #237 fix this
    # is the assertion that fails — the K8s Service for the new name is
    # never created.
    after_deadline = time.time() + 120
    after = None
    while time.time() < after_deadline:
        after = await _find_service(kr8s_api, namespace, "after-rename")
        if after is not None:
            break
        await asyncio.sleep(5)
    assert after is not None, (
        "Post-rename Service 'after-rename' was never created. "
        "This is #237 regressing — the new instance's context did not "
        "include the renamed service."
    )

    aliases = await _wait_for_alias_names(
        kr8s_api, peer_namespace, deployment_id, {"after-rename"}
    )
    assert aliases == {"after-rename"}, (
        f"Aliases of the renamed service in {peer_namespace}: {sorted(aliases)}. "
        "The alias with the old name 'executor' must be deleted (#491)."
    )


@pytest.mark.api_only(
    reason="Deletes through the SDK and checks Services with kr8s; the "
    "[ui-chromium] variant would re-run the same SDK call.",
)
@pytest.mark.ci
async def test_deleted_deployment_leaves_no_alias(
    styrmin_resources: dict,
    discovery_deployments: dict[str, str],
    vcluster: dict,
) -> None:
    """#503: deleting a deployment deletes its aliases in its peers' namespaces."""
    client: StyrminClient = styrmin_resources["client"]
    intent_id = discovery_deployments["intent"]
    intent_namespace = f"styrmin-{intent_id}"
    executor_namespace = f"styrmin-{discovery_deployments['executor']}"
    kr8s_api = await kr8s.asyncio.api(kubeconfig=vcluster["kubeconfig_path"])

    # The alias must exist first, or the test would pass without the fix.
    aliases = await _wait_for_alias_names(
        kr8s_api, executor_namespace, intent_id, {"intent"}
    )
    assert aliases == {"intent"}, (
        f"Aliases of intent in {executor_namespace} before the deletion: "
        f"{sorted(aliases)}"
    )

    await client.deployments.delete(intent_id)
    await wait_for_deployment_status(client, intent_id, "deleted", timeout=300.0)

    remaining = [
        f"{svc.name} (externalName={svc.spec.get('externalName')})"
        async for svc in AsyncService.list(namespace=executor_namespace, api=kr8s_api)
        if isinstance(svc, AsyncService)
        and (
            svc.labels.get("styrmin.io/deployment-id") == intent_id
            or (svc.spec.get("externalName") or "").split(".")[1:2]
            == [intent_namespace]
        )
    ]
    assert not remaining, (
        f"Services of {executor_namespace} that still point to the deleted "
        f"deployment {intent_id}: {remaining}. Deleting a deployment must "
        "delete its service aliases (#503)."
    )


async def _wait_for_alias_names(
    kr8s_api: kr8s.asyncio.Api,
    namespace: str,
    deployment_id: str,
    expected: set[str],
    timeout: float = 60.0,
) -> set[str]:
    """Names of the aliases in *namespace* of the services of *deployment_id*.

    Polls until they are *expected* or *timeout* runs out, and returns the last names.
    """
    deadline = time.time() + timeout
    while True:
        names = {
            svc.name
            async for svc in AsyncService.list(
                namespace=namespace,
                label_selector={
                    "styrmin.io/service-alias": "true",
                    "styrmin.io/deployment-id": deployment_id,
                },
                api=kr8s_api,
            )
            if isinstance(svc, AsyncService)
        }
        if names == expected or time.time() >= deadline:
            return names
        await asyncio.sleep(5)


async def _find_service(
    kr8s_api: kr8s.asyncio.Api, namespace: str, name_substring: str
) -> AsyncService | None:
    services: list[AsyncService] = [
        svc
        async for svc in AsyncService.list(namespace=namespace, api=kr8s_api)
        if isinstance(svc, AsyncService)
    ]
    return next(
        (
            svc
            for svc in services
            if name_substring in svc.name and "postgresql" not in svc.name
        ),
        None,
    )
