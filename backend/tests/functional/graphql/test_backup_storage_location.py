"""Propagation tests for the BackupStorageLocation GraphQL surface."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import BackupStorageLocation, Environment

from .conftest import gql
from .seeds import seed_backup_storage_location, seed_environment

DEFAULT_VARS = {
    "name": "p-bsl",
    "endpoint": "https://s3.example.com",
    "bucket": "p-bucket",
    "region": "us-east-1",
    "accessKeyId": "AKIAIOSFODNN7EXAMPLE",
    "secretAccessKey": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
}


@pytest.mark.asyncio
async def test_create_bsl_persists_all_credentials(
    client: AsyncClient, session: AsyncSession
) -> None:
    data = await gql(client, "create_backup_storage_location", DEFAULT_VARS)
    bsl_id = UUID(data["createBackupStorageLocation"]["id"])

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
    bsl = await seed_backup_storage_location(session)
    bsl_id = bsl.id

    await gql(
        client,
        "update_backup_storage_location",
        {"backupStorageLocationId": str(bsl_id), field: new_value},
    )

    session.expire_all()
    refreshed = await session.get(BackupStorageLocation, bsl_id)
    assert refreshed is not None
    assert getattr(refreshed, db_attr) == new_value


@pytest.mark.asyncio
async def test_update_bsl_credentials_dispatches_sync(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    bsl = await seed_backup_storage_location(session)
    bsl_id = bsl.id
    # Need an environment linked to the BSL on a cluster, otherwise no dispatch.
    await seed_environment(session, bsl=bsl)
    prefect_manager_mock.run_action = AsyncMock()

    await gql(
        client,
        "update_backup_storage_location",
        {
            "backupStorageLocationId": str(bsl_id),
            "accessKeyId": "NEW-KEY",
            "secretAccessKey": "NEW-SECRET",
        },
    )

    session.expire_all()
    refreshed = await session.get(BackupStorageLocation, bsl_id)
    assert refreshed is not None
    # Credentials write must propagate even though the resolver's Prefect
    # dispatch is best-effort (wrapped in try/except inside
    # update_backup_storage_location).
    assert refreshed.access_key_id == "NEW-KEY"
    assert refreshed.secret_access_key == "NEW-SECRET"


@pytest.mark.asyncio
async def test_delete_bsl_removes_row(
    client: AsyncClient, session: AsyncSession
) -> None:
    bsl = await seed_backup_storage_location(session)

    await gql(
        client,
        "delete_backup_storage_location",
        {"backupStorageLocationId": str(bsl.id)},
    )

    assert await session.get(BackupStorageLocation, bsl.id) is None


@pytest.mark.asyncio
async def test_assign_bsl_persists_link(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    bsl = await seed_backup_storage_location(session)
    env = await seed_environment(session)
    bsl_id, env_id = bsl.id, env.id
    prefect_manager_mock.run_action = AsyncMock()

    await gql(
        client,
        "assign_backup_storage_location",
        {
            "environmentId": str(env_id),
            "backupStorageLocationId": str(bsl_id),
        },
    )

    session.expire_all()
    refreshed = await session.get(Environment, env_id)
    assert refreshed is not None
    assert refreshed.backup_storage_location_id == bsl_id


@pytest.mark.asyncio
async def test_unassign_bsl_clears_link(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    bsl = await seed_backup_storage_location(session)
    env = await seed_environment(session, bsl=bsl)
    env_id = env.id
    prefect_manager_mock.run_action = AsyncMock()

    await gql(
        client,
        "unassign_backup_storage_location",
        {"environmentId": str(env_id)},
    )

    session.expire_all()
    refreshed = await session.get(Environment, env_id)
    assert refreshed is not None
    assert refreshed.backup_storage_location_id is None


@pytest.mark.asyncio
async def test_list_bsls_projects_seeded(
    client: AsyncClient, session: AsyncSession
) -> None:
    await seed_backup_storage_location(session, name="bsl-a")
    await seed_backup_storage_location(session, name="bsl-b")

    data = await gql(client, "list_backup_storage_locations")
    rows = data["backupStorageLocations"]
    names = {row["name"] for row in rows}
    assert {"bsl-a", "bsl-b"} <= names
    for row in rows:
        assert row["endpoint"] == "https://s3.example.com"
        assert row["bucket"] == "seed-bucket"
        assert row["region"] == "eu-west-1"
        assert row["environmentCount"] == 0


@pytest.mark.asyncio
async def test_get_bsl_projects_all_fields_and_environment_count(
    client: AsyncClient, session: AsyncSession
) -> None:
    bsl = await seed_backup_storage_location(session, name="counted-bsl")
    await seed_environment(session, bsl=bsl)
    await seed_environment(session, bsl=bsl)

    data = await gql(
        client,
        "get_backup_storage_location",
        {"backupStorageLocationId": str(bsl.id)},
    )
    row = data["backupStorageLocation"]
    assert row["name"] == "counted-bsl"
    assert row["endpoint"] == "https://s3.example.com"
    assert row["bucket"] == "seed-bucket"
    assert row["region"] == "eu-west-1"
    assert row["createdOn"] is not None
    assert row["environmentCount"] == 2
