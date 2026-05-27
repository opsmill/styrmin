"""E2E tests for the backup and restore lifecycle."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Service as AsyncService
from styrmin_sdk import StyrminClient

from tests.e2e.conftest import _portforward, _wait_for_http
from tests.e2e.drivers import ResourceNotFound, ScenarioDriver

pytestmark = [
    pytest.mark.shard_backup,
]


@asynccontextmanager
async def portforward_simple_app(
    kubeconfig_path: str,
    namespace: str,
    service_name: str = "simple-app",
) -> AsyncIterator[int]:
    """Port-forward the simple-app service and yield the local port.

    ``service_name`` defaults to the driver's service name; callers that
    deploy with a ``service_name_overrides`` must pass the override so
    that cross-namespace ``ExternalName`` aliases for sibling deployments
    in the shared env don't get matched instead.
    """
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    simple_app_svc = await AsyncService.get(
        service_name, namespace=namespace, api=kr8s_api
    )
    assert simple_app_svc is not None, (
        f"Could not find service {service_name!r} in namespace {namespace!r}"
    )

    async with _portforward(simple_app_svc, remote_port=8000) as local_port:
        await _wait_for_http(
            f"http://localhost:{local_port}/health", timeout=30.0, interval=3.0
        )
        yield local_port


async def wait_for_pods_ready(
    kubeconfig_path: str,
    namespace: str,
    timeout: float = 180.0,
) -> None:
    """Wait until all pods in *namespace* have ready containers."""
    import time

    from kubernetes_asyncio import client as kubeclient, config as k8s_config

    await k8s_config.load_config(config_file=kubeconfig_path)
    api_client = kubeclient.ApiClient()
    core_api = kubeclient.CoreV1Api(api_client)

    deadline = time.time() + timeout
    while time.time() < deadline:
        pods = await core_api.list_namespaced_pod(namespace=namespace)
        if pods.items and all(
            c.ready
            for pod in pods.items
            if pod.status and pod.status.container_statuses
            for c in pod.status.container_statuses
        ):
            await api_client.close()
            return
        await asyncio.sleep(5)
    await api_client.close()
    raise TimeoutError(f"Pods in {namespace} did not become ready within {timeout}s")


async def assert_velero_backup_uses_bsl(
    kubeconfig_path: str,
    backup_name: str,
    expected_bsl_name: str,
) -> None:
    """Verify the Velero Backup CRD on the cluster targets the expected BSL."""
    from kubernetes_asyncio import client as kubeclient
    from kubernetes_asyncio import config as k8s_config
    from kubernetes_asyncio.client import CustomObjectsApi

    await k8s_config.load_config(config_file=kubeconfig_path)
    api_client = kubeclient.ApiClient()
    custom_api = CustomObjectsApi(api_client)
    try:
        velero_backup = await custom_api.get_namespaced_custom_object(
            group="velero.io",
            version="v1",
            namespace="styrmin",
            plural="backups",
            name=backup_name,
        )
        actual = velero_backup["spec"].get("storageLocation")
        expected = f"styrmin-bsl-{expected_bsl_name}"
        assert actual == expected, (
            f"Expected storageLocation '{expected}', got '{actual}'"
        )
    finally:
        await api_client.close()


@pytest.mark.ci
async def test_backup_and_restore_lifecycle(
    scenario_driver: ScenarioDriver,
    scenario_environment_id: str,
    styrmin_resources: dict,
    deployed_simple_app: dict,
    velero_ready: None,  # noqa: ARG001 — ensures Velero is up before backup/restore
    vcluster: dict,
) -> None:
    """Full lifecycle: write data -> backup -> modify -> restore -> verify."""
    client: StyrminClient = styrmin_resources["client"]
    kubeconfig_path = vcluster["kubeconfig_path"]

    instance_id = deployed_simple_app["instance_id"]
    assert instance_id is not None, "Deployment should have an instance_id"
    namespace = deployed_simple_app["namespace"]

    # Verify environment exposes backup capability (BSL was assigned by the fixture)
    environment = await client.environments.get(environment_id=scenario_environment_id)
    assert environment.capabilities is not None, "Environment should have capabilities"
    assert "backup" in environment.capabilities, (
        "Environment should have backup capability"
    )
    assert "velero" in environment.capabilities["backup"], (
        "Environment should have velero backup provider"
    )
    assert (
        environment.capabilities["backup"]["velero"]["storage_location"]
        == styrmin_resources["bsl_name"]
    ), f"Backup storage_location should be '{styrmin_resources['bsl_name']}'"

    # 1. Write test data (increment counter N times)
    async with portforward_simple_app(kubeconfig_path, namespace) as port:
        async with httpx.AsyncClient() as http_client:
            for _ in range(5):
                await http_client.get(f"http://localhost:{port}/count", timeout=10)
            resp = await http_client.get(f"http://localhost:{port}/count", timeout=10)
            pre_backup_count = resp.json()["counter"]  # 6

    # 2. Create backup via scenario_driver, wait for completion
    created_backup = await scenario_driver.create_backup(instance_id=instance_id)
    assert created_backup.status in {"pending", "in_progress", "completed"}
    backup = await scenario_driver.wait_for_backup(
        backup_id=created_backup.id, max_wait=180
    )
    assert backup.status == "completed"

    # 2b. Verify backup targets the assigned BSL
    await assert_velero_backup_uses_bsl(
        kubeconfig_path=kubeconfig_path,
        backup_name=backup.name,
        expected_bsl_name=styrmin_resources["bsl_name"],
    )

    # 3. Write more data (counter goes higher)
    async with portforward_simple_app(kubeconfig_path, namespace) as port:
        async with httpx.AsyncClient() as http_client:
            for _ in range(5):
                await http_client.get(f"http://localhost:{port}/count", timeout=10)

    # 4. Restore from backup via scenario_driver (same namespace)
    created_restore = await scenario_driver.create_restore(
        backup_id=backup.id, target_namespace=namespace
    )
    assert created_restore.status in {"pending", "in_progress", "completed"}
    restore = await scenario_driver.wait_for_restore(
        restore_id=created_restore.id, max_wait=300
    )
    assert restore.status == "completed"

    # 5. Wait for pods to recover, verify data restored
    await wait_for_pods_ready(kubeconfig_path, namespace)
    async with portforward_simple_app(kubeconfig_path, namespace) as port:
        async with httpx.AsyncClient() as http_client:
            resp = await http_client.get(f"http://localhost:{port}/count", timeout=10)
            # Counter should be back near pre-backup value
            assert resp.json()["counter"] == pre_backup_count + 1

    # 6. Delete backup and verify
    await scenario_driver.delete_backup(backup_id=backup.id)
    with pytest.raises(ResourceNotFound):
        await scenario_driver.get_backup(backup_id=backup.id)


# ---------------------------------------------------------------------------
# Restore lifecycle (deployment.status transitions: running -> restoring -> running)
# ---------------------------------------------------------------------------


async def _wait_for_deployment_status(
    client: StyrminClient,
    deployment_id,
    expected: set[str],
    max_wait: float,
    poll: float = 1.0,
) -> str:
    """Poll deployment.status until it lands in *expected* or timeout.

    Returns the observed status; raises if no expected status is reached.
    """
    deadline = asyncio.get_event_loop().time() + max_wait
    last_seen: str = ""
    while asyncio.get_event_loop().time() < deadline:
        deployment = await client.deployments.get(deployment_id)
        last_seen = deployment.status
        if last_seen in expected:
            return last_seen
        await asyncio.sleep(poll)
    raise AssertionError(
        f"Deployment {deployment_id} status={last_seen!r}; expected one of {expected!r}"
    )


@pytest.mark.ci
async def test_restore_lifecycle_transitions(
    deployed_simple_app: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> None:
    """Backup → Restore → assert deployment passes through restoring → running.

    Reproduces the regression where post-velero the deployment landed in
    'failed' despite healthy pods. The lifecycle now flips to RESTORING on
    restore start and back to RUNNING after the restore-finish reapply.
    """
    driver, client = session_scenario_driver
    deployment_id = deployed_simple_app["deployment_id"]
    instance_id = deployed_simple_app["instance_id"]
    namespace = deployed_simple_app["namespace"]

    # Wait for the agent's status reporter to propagate the deployed
    # state to deployment.status. ``deployed_simple_app`` returns once
    # the CRD reaches Ready, but the DB-side status is updated on the
    # next status poll, which can lag a few seconds.
    await _wait_for_deployment_status(
        client, deployment_id, expected={"running"}, max_wait=30
    )

    backup = await driver.create_backup(instance_id=instance_id)
    backup = await driver.wait_for_backup(backup_id=backup.id, max_wait=180)
    assert backup.status == "completed"

    # Kick off the restore. The styrmin restore flow flips the deployment
    # to RESTORING in the same transaction that creates the restore record,
    # so the very next read should observe the transition.
    created_restore = await driver.create_restore(
        backup_id=backup.id, target_namespace=namespace
    )

    observed = await _wait_for_deployment_status(
        client,
        deployment_id,
        expected={"restoring"},
        max_wait=10,
    )
    assert observed == "restoring"

    # Velero + post-restore reapply runs to completion.
    restore = await driver.wait_for_restore(restore_id=created_restore.id, max_wait=600)
    assert restore.status == "completed"

    # The restore workflow's finish hook moves the deployment back to
    # running synchronously after the reapply succeeds.
    final = await _wait_for_deployment_status(
        client,
        deployment_id,
        expected={"running"},
        max_wait=120,
    )
    assert final == "running"


@pytest.mark.ci
async def test_restore_failure_marks_failed_not_indefinite(
    deployed_simple_app: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> None:
    """If velero fails, deployment becomes 'failed' with a clear message —
    not stuck in 'restoring' forever.

    Provokes the failure by passing a non-existent backup id; the styrmin
    server-side guard rejects it before the workflow starts, so the
    deployment stays in 'running' (RESTORING was never set). This is the
    safer end of the failure spectrum: we explicitly verify the user-
    requested invariant that a failed restore never leaves the deployment
    stuck in RESTORING.
    """
    from uuid import uuid4

    _, client = session_scenario_driver
    deployment_id = deployed_simple_app["deployment_id"]

    pre = await client.deployments.get(deployment_id)
    pre_status = pre.status

    with pytest.raises(Exception):
        await client.backups.create_restore(
            backup_id=uuid4(), target_namespace=deployed_simple_app["namespace"]
        )

    # Deployment is not knocked into 'restoring' by an invalid request.
    after = await client.deployments.get(deployment_id)
    assert after.status == pre_status, (
        f"Failed restore must not change deployment status; was {pre_status!r}, "
        f"now {after.status!r}"
    )
