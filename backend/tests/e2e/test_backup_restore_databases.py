"""E2E tests for MariaDB and MongoDB backup and restore lifecycle.

These tests deploy the ``db-test`` driver which includes a FastAPI app
with MariaDB and MongoDB counter endpoints, then exercise the full
backup → modify → restore → verify cycle for both database engines.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
import kr8s.asyncio
import pytest
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import ResourceNotFoundError
from kr8s.asyncio.objects import Service as AsyncService

from tests.e2e.conftest import _wait_for_http
from tests.e2e.test_backup_restore import wait_for_pods_ready


@asynccontextmanager
async def portforward_db_test(
    kubeconfig_path: str,
    namespace: str,
) -> AsyncIterator[int]:
    """Port-forward the db-test service and yield the local port."""
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    services: list[AsyncService] = [
        svc
        async for svc in AsyncService.list(namespace=namespace, api=kr8s_api)
        if isinstance(svc, AsyncService)
    ]
    db_test_svc = next(
        (
            svc
            for svc in services
            if "db-test" in svc.name
            and "mariadb" not in svc.name
            and "mongodb" not in svc.name
        ),
        None,
    )
    assert db_test_svc, (
        f"Could not find db-test service. Available: {[s.name for s in services]}"
    )

    async with db_test_svc.portforward(
        remote_port=8000, local_port="auto"
    ) as local_port:
        await _wait_for_http(
            f"http://localhost:{local_port}/health", timeout=60.0, interval=3.0
        )
        yield local_port


@pytest.mark.ci
async def test_mariadb_mongodb_backup_and_restore_lifecycle(
    load_db_test: dict,
    velero_ready: None,
    deployed_db_test: dict,
    kind_cluster: dict,
) -> None:
    """Full lifecycle: write data -> backup -> modify -> restore -> verify for MariaDB + MongoDB."""
    client: StyrminClient = load_db_test["client"]
    instance_id = deployed_db_test["instance_id"]
    namespace = deployed_db_test["namespace"]
    kubeconfig_path = kind_cluster["kubeconfig_path"]

    assert instance_id is not None, "Deployment should have an instance_id"

    # 1. Write test data (increment counters N times in both databases)
    async with portforward_db_test(kubeconfig_path, namespace) as port:
        async with httpx.AsyncClient() as http_client:
            for _ in range(5):
                await http_client.get(
                    f"http://localhost:{port}/mariadb/count", timeout=10
                )
                await http_client.get(
                    f"http://localhost:{port}/mongodb/count", timeout=10
                )
            # Read pre-backup values
            mariadb_resp = await http_client.get(
                f"http://localhost:{port}/mariadb/count", timeout=10
            )
            pre_backup_mariadb = mariadb_resp.json()["counter"]  # 6

            mongodb_resp = await http_client.get(
                f"http://localhost:{port}/mongodb/count", timeout=10
            )
            pre_backup_mongodb = mongodb_resp.json()["counter"]  # 6

    # 2. Create backup via SDK, wait for completion
    backup = await client.backups.create_backup(instance_id=instance_id)
    assert backup.status == "pending"
    backup = await client.backups.wait_for_backup(backup.id, max_wait=300)
    assert backup.status == "completed"

    # 3. Write more data (counters go higher)
    async with portforward_db_test(kubeconfig_path, namespace) as port:
        async with httpx.AsyncClient() as http_client:
            for _ in range(5):
                await http_client.get(
                    f"http://localhost:{port}/mariadb/count", timeout=10
                )
                await http_client.get(
                    f"http://localhost:{port}/mongodb/count", timeout=10
                )

    # 4. Restore from backup via SDK (same namespace, existingResourcePolicy=update)
    restore = await client.backups.create_restore(
        backup_id=backup.id, target_namespace=namespace
    )
    assert restore.status == "pending"
    restore = await client.backups.wait_for_restore(restore.id, max_wait=300)
    assert restore.status == "completed"

    # 5. Wait for pods to recover, verify data restored
    await wait_for_pods_ready(kubeconfig_path, namespace)
    async with portforward_db_test(kubeconfig_path, namespace) as port:
        async with httpx.AsyncClient() as http_client:
            mariadb_resp = await http_client.get(
                f"http://localhost:{port}/mariadb/count", timeout=10
            )
            # Counter should be back near pre-backup value
            assert mariadb_resp.json()["counter"] == pre_backup_mariadb + 1

            mongodb_resp = await http_client.get(
                f"http://localhost:{port}/mongodb/count", timeout=10
            )
            assert mongodb_resp.json()["counter"] == pre_backup_mongodb + 1

    # 6. Delete backup and verify
    await client.backups.delete_backup(backup.id)
    with pytest.raises(ResourceNotFoundError):
        await client.backups.get_backup(backup.id)
