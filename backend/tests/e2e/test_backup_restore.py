"""E2E tests for the backup and restore lifecycle."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
import kr8s.asyncio
import pytest
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import ResourceNotFoundError
from infrahub_sdk import Config as InfrahubConfig
from infrahub_sdk import InfrahubClient as InfrahubSDKClient
from kr8s.asyncio.objects import Service as AsyncService

from tests.e2e.conftest import _portforward, _wait_for_http
from tests.e2e.drivers import ResourceNotFound, ScenarioDriver


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


@asynccontextmanager
async def portforward_infrahub(
    kubeconfig_path: str,
    namespace: str,
) -> AsyncIterator[int]:
    """Port-forward the infrahub server service and yield the local port."""
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    services: list[AsyncService] = [
        svc
        async for svc in AsyncService.list(namespace=namespace, api=kr8s_api)
        if isinstance(svc, AsyncService)
    ]
    infrahub_svc = next(
        (svc for svc in services if "infrahub-server" in svc.name),
        None,
    )
    assert infrahub_svc, (
        f"Could not find infrahub server service. Available: {[s.name for s in services]}"
    )

    async with _portforward(infrahub_svc, remote_port=8000) as local_port:
        await _wait_for_http(
            f"http://localhost:{local_port}/api/schema/summary",
            timeout=120.0,
            interval=5.0,
        )
        yield local_port


@pytest.mark.api_only(
    reason="Data setup goes through the Infrahub SDK (direct Infrahub API), "
    "not through a Styrmin-managed UI surface; scenario cannot meaningfully "
    "run through UiScenarioDriver."
)
async def test_infrahub_backup_and_restore_lifecycle(
    load_infrahub: dict,
    velero_ready: None,
    deployed_infrahub_app: dict,
    vcluster: dict,
) -> None:
    """Full lifecycle: create data -> backup -> modify -> restore -> verify (Infrahub)."""
    client: StyrminClient = load_infrahub["client"]
    instance_id = deployed_infrahub_app["instance_id"]
    namespace = deployed_infrahub_app["namespace"]
    kubeconfig_path = vcluster["kubeconfig_path"]

    assert instance_id is not None, "Deployment should have an instance_id"

    tag_name = "styrmin-backup-test"

    # 1. Port-forward and create test data via Infrahub SDK
    async with portforward_infrahub(kubeconfig_path, namespace) as port:
        config = InfrahubConfig(address=f"http://localhost:{port}")
        infrahub_client = InfrahubSDKClient(config=config)

        # Create a BuiltinTag as test data
        tag = await infrahub_client.create(kind="BuiltinTag", name=tag_name)
        await tag.save()

        # Verify the tag exists
        retrieved = await infrahub_client.get(kind="BuiltinTag", name__value=tag_name)
        assert retrieved.name.value == tag_name  # type: ignore[union-attr]

    # 2. Create backup via Styrmin SDK, wait for completion
    created_backup = await client.backups.create_backup(instance_id=instance_id)
    assert created_backup.status == "pending"
    backup = await client.backups.wait_for_backup(created_backup.id, max_wait=300)
    assert backup.status == "completed"

    # 2b. Verify backup targets the assigned BSL
    await assert_velero_backup_uses_bsl(
        kubeconfig_path=kubeconfig_path,
        backup_name=backup.name,
        expected_bsl_name=load_infrahub["bsl_name"],
    )

    # 3. Delete the tag (modify data post-backup)
    async with portforward_infrahub(kubeconfig_path, namespace) as port:
        config = InfrahubConfig(address=f"http://localhost:{port}")
        infrahub_client = InfrahubSDKClient(config=config)

        tag_to_delete = await infrahub_client.get(
            kind="BuiltinTag", name__value=tag_name
        )
        await tag_to_delete.delete()

        # Verify the tag is gone
        tags = await infrahub_client.all(kind="BuiltinTag")
        assert all(t.name.value != tag_name for t in tags)  # type: ignore[union-attr]

    # 4. Restore from backup
    created_restore = await client.backups.create_restore(
        backup_id=backup.id, target_namespace=namespace
    )
    assert created_restore.status == "pending"
    restore = await client.backups.wait_for_restore(created_restore.id, max_wait=600)
    assert restore.status == "completed"

    # 5. Wait for pods to recover after restore
    await wait_for_pods_ready(kubeconfig_path, namespace, timeout=300.0)

    # 6. Verify the tag has been restored
    async with portforward_infrahub(kubeconfig_path, namespace) as port:
        config = InfrahubConfig(address=f"http://localhost:{port}")
        infrahub_client = InfrahubSDKClient(config=config)

        restored_tag = await infrahub_client.get(
            kind="BuiltinTag", name__value=tag_name
        )
        assert restored_tag.name.value == tag_name  # type: ignore[union-attr]

    # 7. Delete backup and verify deletion
    await client.backups.delete_backup(backup.id)
    with pytest.raises(ResourceNotFoundError):
        await client.backups.get_backup(backup.id)
