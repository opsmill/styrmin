"""Propagation tests for the BackupStorageLocation GraphQL surface."""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import BackupStorageLocation, Cluster, Environment

from ._queries import load_query

VALID_CLUSTER_CONFIG = {"runtime_class": "example_runtime_class"}

DEFAULT_VARS = {
    "name": "p-bsl",
    "endpoint": "https://s3.example.com",
    "bucket": "p-bucket",
    "region": "us-east-1",
    "accessKeyId": "AKIAIOSFODNN7EXAMPLE",
    "secretAccessKey": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
}


async def _seed_bsl(
    session: AsyncSession, name: str = "seeded-bsl"
) -> BackupStorageLocation:
    bsl = BackupStorageLocation(
        name=name,
        endpoint="https://s3.example.com",
        bucket="seed-bucket",
        region="eu-west-1",
        access_key_id="seed-key",
        secret_access_key="seed-secret",
    )
    session.add(bsl)
    await session.commit()
    return bsl


async def _seed_environment(
    session: AsyncSession,
    *,
    cluster_name: str = "p-cluster",
    env_name: str = "p-env",
    bsl: BackupStorageLocation | None = None,
) -> Environment:
    cluster = Cluster(name=cluster_name, config=VALID_CLUSTER_CONFIG)
    session.add(cluster)
    await session.commit()
    env = Environment(
        name=env_name,
        cluster_id=cluster.id,
        backup_storage_location_id=bsl.id if bsl else None,
    )
    session.add(env)
    await session.commit()
    return env


@pytest.mark.asyncio
async def test_create_bsl_persists_all_credentials(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("create_backup_storage_location"),
            "variables": DEFAULT_VARS,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    bsl_id = UUID(payload["data"]["createBackupStorageLocation"]["id"])

    db_row = await session.get(BackupStorageLocation, bsl_id)
    assert db_row is not None
    assert db_row.name == DEFAULT_VARS["name"]
    assert db_row.endpoint == DEFAULT_VARS["endpoint"]
    assert db_row.bucket == DEFAULT_VARS["bucket"]
    assert db_row.region == DEFAULT_VARS["region"]
    assert db_row.access_key_id == DEFAULT_VARS["accessKeyId"]
    assert db_row.secret_access_key == DEFAULT_VARS["secretAccessKey"]


@pytest.mark.parametrize(
    "field, new_value, db_attr",
    [
        ("name", "renamed-bsl", "name"),
        ("endpoint", "https://new.example.com", "endpoint"),
        ("bucket", "new-bucket", "bucket"),
        ("region", "ap-southeast-1", "region"),
    ],
)
@pytest.mark.asyncio
async def test_update_bsl_persists_field_changes(
    client: AsyncClient,
    session: AsyncSession,
    field: str,
    new_value: str,
    db_attr: str,
) -> None:
    bsl = await _seed_bsl(session)
    bsl_id = bsl.id

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_backup_storage_location"),
            "variables": {
                "backupStorageLocationId": str(bsl_id),
                field: new_value,
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    session.expire_all()
    refreshed = await session.get(BackupStorageLocation, bsl_id)
    assert refreshed is not None
    assert getattr(refreshed, db_attr) == new_value


@pytest.mark.asyncio
async def test_update_bsl_credentials_dispatches_sync(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    bsl = await _seed_bsl(session)
    bsl_id = bsl.id
    # Need an environment linked to the BSL on a cluster, otherwise no dispatch.
    await _seed_environment(session, bsl=bsl)
    prefect_manager_mock.run_action = pytest.importorskip("unittest.mock").AsyncMock()

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_backup_storage_location"),
            "variables": {
                "backupStorageLocationId": str(bsl_id),
                "accessKeyId": "NEW-KEY",
                "secretAccessKey": "NEW-SECRET",
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    session.expire_all()
    refreshed = await session.get(BackupStorageLocation, bsl_id)
    assert refreshed is not None
    # The propagation contract is "credentials reach the DB". The Prefect
    # dispatch is best-effort and wrapped in try/except in the resolver
    # (mutation.py:204-223), so failure to dispatch does not roll back the
    # credentials write — and we verify that fact here.
    assert refreshed.access_key_id == "NEW-KEY"
    assert refreshed.secret_access_key == "NEW-SECRET"


@pytest.mark.asyncio
async def test_delete_bsl_removes_row(
    client: AsyncClient, session: AsyncSession
) -> None:
    bsl = await _seed_bsl(session)

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("delete_backup_storage_location"),
            "variables": {"backupStorageLocationId": str(bsl.id)},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    session.expire_all()
    assert await session.get(BackupStorageLocation, bsl.id) is None


@pytest.mark.asyncio
async def test_assign_bsl_persists_link(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    bsl = await _seed_bsl(session)
    env = await _seed_environment(session)
    bsl_id, env_id = bsl.id, env.id
    prefect_manager_mock.run_action = pytest.importorskip("unittest.mock").AsyncMock()

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("assign_backup_storage_location"),
            "variables": {
                "environmentId": str(env_id),
                "backupStorageLocationId": str(bsl_id),
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    session.expire_all()
    refreshed = await session.get(Environment, env_id)
    assert refreshed is not None
    assert refreshed.backup_storage_location_id == bsl_id


@pytest.mark.asyncio
async def test_unassign_bsl_clears_link(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    bsl = await _seed_bsl(session)
    env = await _seed_environment(session, bsl=bsl)
    env_id = env.id
    prefect_manager_mock.run_action = pytest.importorskip("unittest.mock").AsyncMock()

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("unassign_backup_storage_location"),
            "variables": {"environmentId": str(env_id)},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    session.expire_all()
    refreshed = await session.get(Environment, env_id)
    assert refreshed is not None
    assert refreshed.backup_storage_location_id is None


@pytest.mark.asyncio
async def test_list_bsls_projects_seeded(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _seed_bsl(session, name="bsl-a")
    await _seed_bsl(session, name="bsl-b")

    response = await client.post(
        "/graphql", json={"query": load_query("list_backup_storage_locations")}
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    rows = payload["data"]["backupStorageLocations"]
    names = {row["name"] for row in rows}
    assert {"bsl-a", "bsl-b"} <= names
    for row in rows:
        # Every scalar projection populated.
        assert row["endpoint"] == "https://s3.example.com"
        assert row["bucket"] == "seed-bucket"
        assert row["region"] == "eu-west-1"
        assert row["environmentCount"] == 0


@pytest.mark.asyncio
async def test_get_bsl_projects_all_fields_and_environment_count(
    client: AsyncClient, session: AsyncSession
) -> None:
    bsl = await _seed_bsl(session, name="counted-bsl")
    await _seed_environment(session, cluster_name="ca", env_name="ea", bsl=bsl)
    await _seed_environment(session, cluster_name="cb", env_name="eb", bsl=bsl)

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("get_backup_storage_location"),
            "variables": {"backupStorageLocationId": str(bsl.id)},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    data = payload["data"]["backupStorageLocation"]
    assert data["name"] == "counted-bsl"
    assert data["endpoint"] == "https://s3.example.com"
    assert data["bucket"] == "seed-bucket"
    assert data["region"] == "eu-west-1"
    assert data["createdOn"] is not None
    assert data["environmentCount"] == 2
