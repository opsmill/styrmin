"""E2E tests for the Infrahub-stack backup and restore lifecycle.

Split out of ``test_backup_restore.py`` so the Infrahub server + DB boot
runs in its own CI matrix cell (``shard_infrahub``) and doesn't gate
debug iterations on the lighter simple-app backup tests.

These tests exercise **two** independent backup paths in a single
backup/restore cycle:

* **Database** (``database`` component) — a ``BuiltinTag`` node lives only
  in Neo4j. The community driver uses ``kind: neo4j-community`` (Neo4j is
  paused while Velero copies its ``data`` volume, #263); the enterprise driver
  uses ``kind: neo4j`` (``neo4j-admin database backup``).
* **Disk** (``server`` component, ``kind: disk``) — artifact content and
  file objects live in Infrahub's object store on the server's
  ``infrahub-server-storage-data`` PVC, mounted at ``/opt/infrahub/storage``.
  This is what commit af6fc28 enabled and what we validate here by writing
  object-store content, backing up, and confirming the content survives a
  restore (which deletes and recreates the namespace + its PVCs).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import kr8s.asyncio
import pytest
from infrahub_sdk import Config as InfrahubConfig
from infrahub_sdk import InfrahubClient as InfrahubSDKClient
from kr8s.asyncio.objects import Service as AsyncService
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import ResourceNotFoundError

from tests.e2e.conftest import _portforward, _wait_for_http
from tests.e2e.test_backup_restore import (
    assert_velero_backup_uses_bsl,
    read_velero_backup,
    wait_for_pods_ready,
)

pytestmark = [
    pytest.mark.shard_infrahub,
]

# Default admin token baked into the upstream Infrahub Helm chart values
# (`infrahubServer.admin.INFRAHUB_API_TOKEN`). The chart preseeds the same
# value at `INFRAHUB_INITIAL_ADMIN_TOKEN`, so the running instance accepts
# it as the admin token immediately after the initial setup completes.
# Infrahub 1.6+ requires authentication for writes through the SDK.
_INFRAHUB_ADMIN_TOKEN = "06438eb2-8019-4776-878c-0941b1f1d1ec"

# Distinctive payload uploaded to the Infrahub object store. Object-store
# content is exactly where rendered artifact content and file objects are
# persisted on disk (``CoreArtifact.storage_id`` -> object store), so a
# round-trip through it is a faithful proxy for "the content of one artifact"
# and lives only on the server's disk-backed PVC — never in Neo4j.
_ARTIFACT_CONTENT = (
    "# styrmin disk-backup artifact probe\n"
    "interface Ethernet1\n"
    "  description styrmin-backup-disk-probe\n"
    "  ip address 10.0.0.1/31\n"
)


def _make_infrahub_client(port: int) -> InfrahubSDKClient:
    """Build an authenticated Infrahub SDK client against a forwarded port."""
    config = InfrahubConfig(
        address=f"http://localhost:{port}", api_token=_INFRAHUB_ADMIN_TOKEN
    )
    return InfrahubSDKClient(config=config)


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


@pytest.mark.ci
@pytest.mark.api_only(
    reason="Data setup goes through the Infrahub SDK (direct Infrahub API), "
    "not through a Styrmin-managed UI surface; scenario cannot meaningfully "
    "run through UiScenarioDriver."
)
async def test_infrahub_backup_and_restore_lifecycle(
    load_infrahub: dict,
    velero_ready: None,  # noqa: ARG001 — ensures Velero is up before backup/restore
    deployed_infrahub_app: dict,
    vcluster: dict,
) -> None:
    """Full lifecycle: create data -> backup -> modify -> restore -> verify (Infrahub).

    Validates both the database backup (``BuiltinTag`` in Neo4j) and the disk
    backup (object-store content on the server PVC).
    """
    client: StyrminClient = load_infrahub["client"]
    instance_id = deployed_infrahub_app["instance_id"]
    namespace = deployed_infrahub_app["namespace"]
    kubeconfig_path = vcluster["kubeconfig_path"]

    assert instance_id is not None, "Deployment should have an instance_id"

    tag_name = "styrmin-backup-test"

    # 1. Port-forward and create test data via Infrahub SDK
    async with portforward_infrahub(kubeconfig_path, namespace) as port:
        infrahub_client = _make_infrahub_client(port)

        # Create a BuiltinTag as test data (database / Neo4j)
        tag = await infrahub_client.create(kind="BuiltinTag", name=tag_name)
        await tag.save()

        # Verify the tag exists
        retrieved = await infrahub_client.get(kind="BuiltinTag", name__value=tag_name)
        assert retrieved.name.value == tag_name  # type: ignore[union-attr]

        # Upload artifact content to the object store (disk / server PVC) and
        # capture its identifier. This is the disk-backup probe.
        upload = await infrahub_client.object_store.upload(content=_ARTIFACT_CONTENT)
        storage_id = upload["identifier"]
        assert storage_id, f"Object store upload returned no identifier: {upload!r}"

        # Verify the content is readable before the backup.
        pre_backup_content = await infrahub_client.object_store.get(
            identifier=storage_id
        )
        assert pre_backup_content == _ARTIFACT_CONTENT

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

    # 2c. Neo4j is idle here, so only the hook counts prove the pause ran: the Neo4j
    # pause and resume, and the task-manager-db dump and cleanup, on one pod each.
    velero_backup = await read_velero_backup(kubeconfig_path, backup.name)
    hook_status = velero_backup["status"].get("hookStatus") or {}
    assert hook_status.get("hooksFailed", 0) == 0, hook_status
    assert hook_status.get("hooksAttempted") == 4, hook_status

    # 3. Delete the tag (modify data post-backup)
    async with portforward_infrahub(kubeconfig_path, namespace) as port:
        infrahub_client = _make_infrahub_client(port)

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

    # 6. Verify the tag (DB) and the artifact content (disk) survived the restore
    async with portforward_infrahub(kubeconfig_path, namespace) as port:
        infrahub_client = _make_infrahub_client(port)

        restored_tag = await infrahub_client.get(
            kind="BuiltinTag", name__value=tag_name
        )
        assert restored_tag.name.value == tag_name  # type: ignore[union-attr]

        # Disk backup assertion: the object-store content present at backup
        # time must still be readable after the restore deleted and recreated
        # the namespace + its PVCs. If `server.backup` did not actually
        # capture the `infrahub-server-storage-data` volume, this 404s.
        restored_content = await infrahub_client.object_store.get(identifier=storage_id)
        assert restored_content == _ARTIFACT_CONTENT, (
            "Object-store (artifact) content was not restored from the disk "
            "backup — the server PVC content was lost across the restore."
        )

    # 7. Delete backup and verify deletion
    await client.backups.delete_backup(backup.id)
    with pytest.raises(ResourceNotFoundError):
        await client.backups.get_backup(backup.id)


@pytest.mark.ci
@pytest.mark.api_only(
    reason="Data setup goes through the Infrahub SDK (direct Infrahub API), "
    "not through a Styrmin-managed UI surface; scenario cannot meaningfully "
    "run through UiScenarioDriver."
)
async def test_infrahub_enterprise_backup_and_restore_lifecycle(
    load_infrahub_enterprise: dict,
    velero_ready: None,  # noqa: ARG001 — ensures Velero is up before backup/restore
    deployed_infrahub_enterprise_app: dict,
    vcluster: dict,
) -> None:
    """Full lifecycle: create data -> backup -> modify -> restore -> verify (Infrahub Enterprise).

    Validates both the database backup (``BuiltinTag`` in Neo4j) and the disk
    backup (object-store / artifact content on the server PVC, enabled in
    af6fc28).
    """
    client: StyrminClient = load_infrahub_enterprise["client"]
    instance_id = deployed_infrahub_enterprise_app["instance_id"]
    namespace = deployed_infrahub_enterprise_app["namespace"]
    kubeconfig_path = vcluster["kubeconfig_path"]

    assert instance_id is not None, "Deployment should have an instance_id"

    tag_name = "styrmin-enterprise-backup-test"

    # 1. Port-forward and create test data via Infrahub SDK
    async with portforward_infrahub(kubeconfig_path, namespace) as port:
        infrahub_client = _make_infrahub_client(port)

        # Create a BuiltinTag as test data (database / Neo4j)
        tag = await infrahub_client.create(kind="BuiltinTag", name=tag_name)
        await tag.save()

        # Verify the tag exists
        retrieved = await infrahub_client.get(kind="BuiltinTag", name__value=tag_name)
        assert retrieved.name.value == tag_name  # type: ignore[union-attr]

        # Upload artifact content to the object store (disk / server PVC) and
        # capture its identifier. This is the disk-backup probe.
        upload = await infrahub_client.object_store.upload(content=_ARTIFACT_CONTENT)
        storage_id = upload["identifier"]
        assert storage_id, f"Object store upload returned no identifier: {upload!r}"

        # Verify the content is readable before the backup.
        pre_backup_content = await infrahub_client.object_store.get(
            identifier=storage_id
        )
        assert pre_backup_content == _ARTIFACT_CONTENT

    # 2. Create backup via Styrmin SDK, wait for completion
    created_backup = await client.backups.create_backup(instance_id=instance_id)
    assert created_backup.status == "pending"
    backup = await client.backups.wait_for_backup(created_backup.id, max_wait=300)
    assert backup.status == "completed"

    # 2b. Verify backup targets the assigned BSL
    await assert_velero_backup_uses_bsl(
        kubeconfig_path=kubeconfig_path,
        backup_name=backup.name,
        expected_bsl_name=load_infrahub_enterprise["bsl_name"],
    )

    # 3. Delete the tag (modify data post-backup)
    async with portforward_infrahub(kubeconfig_path, namespace) as port:
        infrahub_client = _make_infrahub_client(port)

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

    # 6. Verify the tag (DB) and the artifact content (disk) survived the restore
    async with portforward_infrahub(kubeconfig_path, namespace) as port:
        infrahub_client = _make_infrahub_client(port)

        restored_tag = await infrahub_client.get(
            kind="BuiltinTag", name__value=tag_name
        )
        assert restored_tag.name.value == tag_name  # type: ignore[union-attr]

        # Disk backup assertion: the object-store content present at backup
        # time must still be readable after the restore deleted and recreated
        # the namespace + its PVCs. If `server.backup` did not actually
        # capture the `infrahub-server-storage-data` volume, this 404s.
        restored_content = await infrahub_client.object_store.get(identifier=storage_id)
        assert restored_content == _ARTIFACT_CONTENT, (
            "Object-store (artifact) content was not restored from the disk "
            "backup — the server PVC content was lost across the restore."
        )

    # 7. Delete backup and verify deletion
    await client.backups.delete_backup(backup.id)
    with pytest.raises(ResourceNotFoundError):
        await client.backups.get_backup(backup.id)
