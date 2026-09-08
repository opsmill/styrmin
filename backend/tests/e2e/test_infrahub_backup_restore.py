"""E2E tests for the Infrahub-stack backup and restore lifecycle.

Split out of ``test_backup_restore.py`` so the Infrahub server + DB boot
runs in its own CI matrix cell (``shard_infrahub``) and doesn't gate
debug iterations on the lighter simple-app backup tests.

These tests exercise **two** independent backup paths in a single
backup/restore cycle:

* **Database** (``database`` component, ``kind: neo4j``) — a ``BuiltinTag``
  node lives only in Neo4j.
* **Disk** (``server`` component, ``kind: disk``) — artifact content and
  file objects live in Infrahub's object store on the server's
  ``infrahub-server-storage-data`` PVC, mounted at ``/opt/infrahub/storage``.
  This is what commit af6fc28 enabled and what we validate here by writing
  object-store content, backing up, and confirming the content survives a
  restore (which deletes and recreates the namespace + its PVCs).
* **Postgres** (``task-manager-db`` component, ``kind: postgres``) — Prefect's
  database, captured as a ``pg_dump`` on the ``backup`` volume and replayed by
  a velero post-restore hook. Unlike the other two this component has a live
  writer of its own: ``task-manager`` (Prefect server) is restored alongside
  it and runs its migration chain against the freshly-initdb'd database while
  the hook is restoring into it. The enterprise scenario asserts the schema
  that comes out the other side is the backup's, not an interleaving of the
  two.
"""

from __future__ import annotations

import base64
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

import kr8s.asyncio
import pytest
from infrahub_sdk import Config as InfrahubConfig
from infrahub_sdk import InfrahubClient as InfrahubSDKClient
from kr8s.asyncio.objects import Pod as AsyncPod
from kr8s.asyncio.objects import Service as AsyncService
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import ResourceNotFoundError

from tests.e2e.conftest import _portforward, _wait_for_http
from tests.e2e.test_backup_restore import (
    assert_velero_backup_uses_bsl,
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


# One line per column and per constraint in the `prefect` database's public
# schema. Deliberately schema-only: row counts drift as Prefect records flow
# runs, but the shape has to come back from the dump. A restore that raced
# Prefect's own migrations leaves tables stuck at an older revision (the
# reported symptom was `column "status" of relation "work_pool" does not
# exist` during COPY), which shows up here as signatures that were in the
# backup and are missing afterwards. Read from the catalogue rather than a
# hard-coded column list so it survives Prefect schema changes.
_PG_SCHEMA_SIGNATURE_SQL = """
SELECT format('col %s.%s:%s', table_name, column_name, data_type)
FROM information_schema.columns
WHERE table_schema = 'public'
UNION ALL
SELECT format('con %s:%s', conrelid::regclass::text, conname)
FROM pg_constraint
WHERE connamespace = 'public'::regnamespace
"""


async def _psql(kubeconfig_path: str, namespace: str, sql: str) -> str:
    """Run *sql* in the task-manager-db pod, return stdout stripped.

    The SQL travels base64-encoded for the same reason the worker-death probe
    does it: some clusters negotiate the older ``v4.channel.k8s.io`` exec
    subprotocol, which kr8s cannot feed over stdin.
    """
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    pods = [
        pod
        async for pod in AsyncPod.list(
            namespace=namespace,
            label_selector={"infrahub/service": "task-manager-db"},
            api=kr8s_api,
        )
    ]
    assert pods, f"No task-manager-db pod found in namespace {namespace}"

    encoded = base64.b64encode(sql.encode()).decode()
    result = await pods[0].exec(
        [
            "sh",
            "-c",
            # Same $POSTGRES_PASSWORD_FILE / $POSTGRES_PASSWORD resolution the
            # backup and restore hooks use.
            'PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE" 2>/dev/null'
            ' || printf %s "$POSTGRES_PASSWORD")"'
            ' psql -tAX -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE"'
            f' -c "$(echo {encoded} | base64 -d)"',
        ],
        container="postgresql",
        check=True,
    )
    stdout = result.stdout
    return (stdout.decode() if isinstance(stdout, bytes) else stdout).strip()


async def _pg_schema_signatures(kubeconfig_path: str, namespace: str) -> set[str]:
    """Return the shape of the prefect database as a set of signatures."""
    out = await _psql(kubeconfig_path, namespace, _PG_SCHEMA_SIGNATURE_SQL)
    signatures = {line.strip() for line in out.splitlines() if line.strip()}
    assert signatures, "Could not read the prefect schema"
    return signatures


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
@pytest.mark.skip(reason="backup/restore not supported with community")
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

    # 1b. Seed the postgres probe (task-manager-db / Prefect's database) and
    #     record the schema shape the backup is about to capture.
    pg_marker = f"styrmin-pg-probe-{uuid.uuid4().hex[:8]}"
    await _psql(
        kubeconfig_path,
        namespace,
        "CREATE TABLE IF NOT EXISTS styrmin_restore_probe (marker text PRIMARY KEY); "
        f"INSERT INTO styrmin_restore_probe (marker) VALUES ('{pg_marker}') "
        "ON CONFLICT DO NOTHING;",
    )
    pre_backup_schema = await _pg_schema_signatures(kubeconfig_path, namespace)

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

    # 3b. Drift postgres too, by dropping the probe table outright. That takes
    #     away both the marker row and its schema signatures, so neither
    #     post-restore assertion below can pass vacuously.
    await _psql(kubeconfig_path, namespace, "DROP TABLE styrmin_restore_probe;")
    assert pre_backup_schema - await _pg_schema_signatures(
        kubeconfig_path, namespace
    ), (
        "Post-backup drift left the schema intact — the assertions below would pass vacuously."
    )

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

    # 6b. Postgres backup assertion. The marker row proves the pg_dump was
    #     actually replayed; the schema check proves it was replayed *cleanly*.
    #     Prefect server is restored alongside its database and migrates the
    #     empty database it finds, concurrently with the restore hook — an
    #     interleaving leaves tables at an older migration revision, and those
    #     missing columns show up here even when the restore reports success.
    #     Subset rather than equality: anything Prefect legitimately adds after
    #     the restore is fine, anything the backup had and lost is not.
    probe_table = await _psql(
        kubeconfig_path, namespace, "SELECT to_regclass('public.styrmin_restore_probe')"
    )
    assert probe_table == "styrmin_restore_probe", (
        "The task-manager-db (postgres) dump was not restored: the probe table "
        "is missing."
    )
    restored_marker = await _psql(
        kubeconfig_path, namespace, "SELECT marker FROM styrmin_restore_probe"
    )
    assert restored_marker == pg_marker, (
        "The task-manager-db (postgres) dump was not restored: expected "
        f"marker {pg_marker!r}, got {restored_marker!r}."
    )
    missing = pre_backup_schema - await _pg_schema_signatures(
        kubeconfig_path, namespace
    )
    assert not missing, (
        "The restored prefect schema is missing objects the backup had: "
        f"{sorted(missing)}. This is the signature of pg_restore interleaving "
        "with Prefect's own migrations — see postgres_restore_hooks()."
    )

    # 7. Delete backup and verify deletion
    await client.backups.delete_backup(backup.id)
    with pytest.raises(ResourceNotFoundError):
        await client.backups.get_backup(backup.id)
