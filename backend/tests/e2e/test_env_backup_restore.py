"""E2E test for the environment backup and restore lifecycle.

Deploys two simple-app instances, writes data to both, creates an
environment-level backup, modifies data, restores, and verifies both
applications return to their pre-backup state.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import ResourceNotFoundError

from tests.e2e.test_backup_restore import portforward_simple_app, wait_for_pods_ready


async def _deploy_and_wait(
    client: StyrminClient,
    environment_id: str,
    name: str,
    timeout: float = 180,
    service_name_overrides: list[dict[str, str]] | None = None,
) -> dict:
    """Deploy a simple-app and poll until running. Returns deployment info."""
    from styrmin_sdk.exceptions import StyrminError

    task = await client.deployments.create(
        driver="simple-app",
        version="0.1.0",
        environment_id=environment_id,
        name=name,
        service_name_overrides=service_name_overrides,
    )
    deployment_id = task.deployment_id
    assert deployment_id is not None, f"Task for {name} should have a deployment_id"

    deadline = time.time() + timeout
    deployment = None
    while time.time() < deadline:
        try:
            deployment = await client.deployments.get(deployment_id)
            if deployment.status in ("deployed", "running"):
                break
        except StyrminError:
            pass
        await asyncio.sleep(10)
    else:
        raise TimeoutError(f"Deployment {name} did not reach ready state within {timeout}s")

    instance_id = None
    if deployment and deployment.application_instance:
        instance_id = str(deployment.application_instance.id)

    return {
        "deployment_id": str(deployment_id),
        "instance_id": instance_id,
        "namespace": f"styrmin-{deployment_id}",
        "name": name,
    }


async def _write_counter(kubeconfig_path: str, namespace: str, increments: int) -> int:
    """Increment the simple-app counter N times and return the current value."""
    async with portforward_simple_app(kubeconfig_path, namespace) as port:
        async with httpx.AsyncClient() as http_client:
            for _ in range(increments):
                await http_client.get(f"http://localhost:{port}/count", timeout=10)
            resp = await http_client.get(f"http://localhost:{port}/count", timeout=10)
            return resp.json()["counter"]


async def _read_counter(kubeconfig_path: str, namespace: str) -> int:
    """Read the simple-app counter (also increments by 1)."""
    async with portforward_simple_app(kubeconfig_path, namespace) as port:
        async with httpx.AsyncClient() as http_client:
            resp = await http_client.get(f"http://localhost:{port}/count", timeout=10)
            return resp.json()["counter"]


@pytest.mark.ci
async def test_environment_backup_and_restore_lifecycle(
    styrmin_resources: dict,
    velero_ready: None,
    simple_app_image: str,  # noqa: ARG001 — ensures image is built
    vcluster: dict,
) -> None:
    """Full lifecycle: deploy two apps → write data → env backup → modify → env restore → verify both."""
    client: StyrminClient = styrmin_resources["client"]
    environment_id = styrmin_resources["environment_id"]
    kubeconfig_path = vcluster["kubeconfig_path"]

    # ── 1. Deploy two simple-app instances ──────────────────────────────
    app1 = await _deploy_and_wait(client, environment_id, "simple-app-env-test-1")
    app2 = await _deploy_and_wait(
        client,
        environment_id,
        "simple-app-env-test-2",
        service_name_overrides=[
            {"driverServiceName": "simple-app", "overrideName": "simple-app-2"},
        ],
    )

    assert app1["instance_id"] is not None, "App 1 should have an instance_id"
    assert app2["instance_id"] is not None, "App 2 should have an instance_id"

    # ── 2. Write test data to BOTH apps ─────────────────────────────────
    pre_backup_count_1 = await _write_counter(kubeconfig_path, app1["namespace"], 5)
    pre_backup_count_2 = await _write_counter(kubeconfig_path, app2["namespace"], 5)

    # ── 3. Create environment backup, wait for completion ───────────────
    env_backup = await client.environment_backups.create(
        environment_id=environment_id,
        name="e2e-env-lifecycle-backup",
    )
    assert env_backup.status == "pending"

    env_backup = await client.environment_backups.wait_for_completion(
        env_backup.id, max_wait=600, interval=15
    )
    assert env_backup.status == "completed", (
        f"Environment backup should complete, got: {env_backup.status}"
    )

    # Verify both deployments were backed up
    detail = await client.environment_backups.get(env_backup.id)
    assert detail.backup_count >= 2, (
        f"Expected at least 2 constituent backups, got {detail.backup_count}"
    )

    # ── 4. Write MORE data to both apps (counter goes higher) ───────────
    await _write_counter(kubeconfig_path, app1["namespace"], 5)
    await _write_counter(kubeconfig_path, app2["namespace"], 5)

    # ── 5. Restore from environment backup ──────────────────────────────
    env_restore = await client.environment_restores.create(
        environment_backup_id=env_backup.id,
    )
    assert env_restore.status == "pending"

    env_restore = await client.environment_restores.wait_for_completion(
        env_restore.id, max_wait=600, interval=15
    )
    assert env_restore.status == "completed", (
        f"Environment restore should complete, got: {env_restore.status}"
    )

    # Verify both deployments were restored
    restore_detail = await client.environment_restores.get(env_restore.id)
    assert restore_detail.restore_count >= 2, (
        f"Expected at least 2 constituent restores, got {restore_detail.restore_count}"
    )

    # ── 6. Wait for pods to recover, verify data restored ───────────────
    await wait_for_pods_ready(kubeconfig_path, app1["namespace"])
    await wait_for_pods_ready(kubeconfig_path, app2["namespace"])

    restored_count_1 = await _read_counter(kubeconfig_path, app1["namespace"])
    assert restored_count_1 == pre_backup_count_1 + 1, (
        f"App 1 counter should revert to {pre_backup_count_1 + 1}, got {restored_count_1}"
    )

    restored_count_2 = await _read_counter(kubeconfig_path, app2["namespace"])
    assert restored_count_2 == pre_backup_count_2 + 1, (
        f"App 2 counter should revert to {pre_backup_count_2 + 1}, got {restored_count_2}"
    )

    # ── 7. Cleanup: delete environment backup, verify cascade ───────────
    await client.environment_backups.delete(env_backup.id)
    with pytest.raises(ResourceNotFoundError):
        await client.environment_backups.get(env_backup.id)
