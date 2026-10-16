"""Propagation tests for the BackupStorageLocation GraphQL surface."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import BackupStorageLocation, Environment
from styrmin_backend.workflows.models import PrefectAction

from ._queries import load_query
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
async def test_update_bsl_rename_to_existing_name_is_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Renaming a BSL to a name another BSL already owns must fail with a
    typed ``ALREADY_EXISTS`` error and leave the target row unchanged.

    Regression: the update path skipped the name-uniqueness check the
    create path performs, so the unique index failed at commit and the
    client received ``INTERNAL_ERROR`` instead of ``ALREADY_EXISTS``.
    """
    taken = await seed_backup_storage_location(session, name="taken-name")
    target = await seed_backup_storage_location(session, name="target-name")
    target_id = target.id

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_backup_storage_location"),
            "variables": {
                "backupStorageLocationId": str(target_id),
                "name": taken.name,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("errors"), f"expected a typed error, got: {payload}"
    extensions = payload["errors"][0].get("extensions") or {}
    assert extensions.get("code") == "ALREADY_EXISTS", (
        f"expected ALREADY_EXISTS, got {extensions!r}"
    )

    session.expire_all()
    refreshed = await session.get(BackupStorageLocation, target_id)
    assert refreshed is not None
    assert refreshed.name == "target-name"


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
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
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


@pytest.fixture
def workflow_manager(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """The manager the BSL mutations get from ``get_manager()``, which they call directly."""
    manager = MagicMock()
    manager.run_action = AsyncMock()
    manager.save_bsl_credentials = AsyncMock()
    manager.delete_bsl_credentials = AsyncMock()
    monkeypatch.setattr(
        "styrmin_backend.api.schema.mutation.get_manager", lambda: manager
    )
    return manager


def _dispatched(workflow_manager: MagicMock, action: PrefectAction) -> list[dict]:
    return [
        call.kwargs["parameters"]
        for call in workflow_manager.run_action.await_args_list
        if call.kwargs["action"] == action
    ]


async def _rename(client: AsyncClient, bsl_id: UUID, name: str) -> None:
    await gql(
        client,
        "update_backup_storage_location",
        {"backupStorageLocationId": str(bsl_id), "name": name},
    )


@pytest.mark.asyncio
async def test_assign_bsl_creates_cluster_objects_by_location_id(
    client: AsyncClient, session: AsyncSession, workflow_manager: MagicMock
) -> None:
    bsl = await seed_backup_storage_location(session)
    env = await seed_environment(session)
    bsl_id, env_id = bsl.id, env.id

    await gql(
        client,
        "assign_backup_storage_location",
        {"environmentId": str(env_id), "backupStorageLocationId": str(bsl_id)},
    )

    [created] = _dispatched(workflow_manager, PrefectAction.SYNC_BSL_CREATE)
    assert created["bsl_id"] == str(bsl_id)
    assert "bsl_name" not in created


@pytest.mark.usefixtures("workflow_manager")
@pytest.mark.asyncio
async def test_backup_capability_names_velero_object_and_survives_rename(
    client: AsyncClient, session: AsyncSession
) -> None:
    """#509: the capability is the Velero object's name, so a rename leaves it unchanged."""
    bsl = await seed_backup_storage_location(session, name="before-rename")
    env = await seed_environment(session)
    bsl_id, env_id = bsl.id, env.id
    expected = {"velero": {"storage_location": f"styrmin-bsl-{bsl_id}"}}

    await gql(
        client,
        "assign_backup_storage_location",
        {"environmentId": str(env_id), "backupStorageLocationId": str(bsl_id)},
    )
    session.expire_all()
    assigned = await session.get(Environment, env_id)
    assert assigned is not None and assigned.capabilities is not None
    assert assigned.capabilities["backup"] == expected

    await _rename(client, bsl_id, "after-rename")
    session.expire_all()
    renamed = await session.get(Environment, env_id)
    assert renamed is not None and renamed.capabilities is not None
    assert renamed.capabilities["backup"] == expected


@pytest.mark.asyncio
async def test_assign_bsl_saves_keys_outside_the_flow_parameters(
    client: AsyncClient, session: AsyncSession, workflow_manager: MagicMock
) -> None:
    """#497: Prefect stores flow-run parameters, so the keys go to a Secret block."""
    bsl = await seed_backup_storage_location(session)
    env = await seed_environment(session)
    bsl_id, env_id = bsl.id, env.id
    keys = (bsl.access_key_id, bsl.secret_access_key)

    await gql(
        client,
        "assign_backup_storage_location",
        {"environmentId": str(env_id), "backupStorageLocationId": str(bsl_id)},
    )

    workflow_manager.save_bsl_credentials.assert_awaited_once_with(bsl_id, *keys)
    [created] = _dispatched(workflow_manager, PrefectAction.SYNC_BSL_CREATE)
    assert created == {
        "bsl_id": str(bsl_id),
        "namespace": "styrmin",
        "bucket": bsl.bucket,
        "region": bsl.region,
        "endpoint": bsl.endpoint,
    }


@pytest.mark.asyncio
async def test_unassign_renamed_bsl_removes_cluster_objects_by_location_id(
    client: AsyncClient, session: AsyncSession, workflow_manager: MagicMock
) -> None:
    """#488: a removal after a rename must still target the location's objects."""
    bsl = await seed_backup_storage_location(session, name="before-rename")
    env = await seed_environment(session, bsl=bsl)
    bsl_id, env_id = bsl.id, env.id

    await _rename(client, bsl_id, "after-rename")
    await gql(
        client, "unassign_backup_storage_location", {"environmentId": str(env_id)}
    )

    assert _dispatched(workflow_manager, PrefectAction.SYNC_BSL_DELETE) == [
        {"bsl_id": str(bsl_id), "namespace": "styrmin"}
    ]


@pytest.mark.asyncio
async def test_reassign_renamed_bsl_removes_old_cluster_objects_by_location_id(
    client: AsyncClient, session: AsyncSession, workflow_manager: MagicMock
) -> None:
    old_bsl = await seed_backup_storage_location(session, name="before-rename")
    new_bsl = await seed_backup_storage_location(session)
    env = await seed_environment(session, bsl=old_bsl)
    old_bsl_id, new_bsl_id, env_id = old_bsl.id, new_bsl.id, env.id

    await _rename(client, old_bsl_id, "after-rename")
    await gql(
        client,
        "assign_backup_storage_location",
        {"environmentId": str(env_id), "backupStorageLocationId": str(new_bsl_id)},
    )

    assert _dispatched(workflow_manager, PrefectAction.SYNC_BSL_DELETE) == [
        {"bsl_id": str(old_bsl_id), "namespace": "styrmin"}
    ]


@pytest.mark.asyncio
async def test_credentials_update_of_renamed_bsl_targets_location_id(
    client: AsyncClient, session: AsyncSession, workflow_manager: MagicMock
) -> None:
    bsl = await seed_backup_storage_location(session, name="before-rename")
    await seed_environment(session, bsl=bsl)
    bsl_id = bsl.id

    await gql(
        client,
        "update_backup_storage_location",
        {
            "backupStorageLocationId": str(bsl_id),
            "name": "after-rename",
            "accessKeyId": "NEW-KEY",
            "secretAccessKey": "NEW-SECRET",
        },
    )

    [updated] = _dispatched(workflow_manager, PrefectAction.SYNC_BSL_UPDATE_CREDENTIALS)
    assert updated["bsl_id"] == str(bsl_id)
    assert "bsl_name" not in updated


@pytest.mark.asyncio
async def test_credentials_update_starts_one_run_whatever_the_cluster_count(
    client: AsyncClient, session: AsyncSession, workflow_manager: MagicMock
) -> None:
    """#498: no run names a cluster, so one run per cluster would not reach each cluster."""
    bsl = await seed_backup_storage_location(session)
    # seed_environment seeds a new cluster for each environment.
    await seed_environment(session, bsl=bsl)
    await seed_environment(session, bsl=bsl)
    bsl_id = bsl.id

    await gql(
        client,
        "update_backup_storage_location",
        {
            "backupStorageLocationId": str(bsl_id),
            "accessKeyId": "NEW-KEY",
            "secretAccessKey": "NEW-SECRET",
        },
    )

    assert _dispatched(workflow_manager, PrefectAction.SYNC_BSL_UPDATE_CREDENTIALS) == [
        {"bsl_id": str(bsl_id), "namespace": "styrmin"}
    ]


@pytest.mark.asyncio
async def test_credentials_update_saves_new_keys_outside_the_flow_parameters(
    client: AsyncClient, session: AsyncSession, workflow_manager: MagicMock
) -> None:
    """#497: the flow loads the new keys from the location's Secret block."""
    bsl = await seed_backup_storage_location(session)
    await seed_environment(session, bsl=bsl)
    bsl_id = bsl.id

    await gql(
        client,
        "update_backup_storage_location",
        {
            "backupStorageLocationId": str(bsl_id),
            "accessKeyId": "NEW-KEY",
            "secretAccessKey": "NEW-SECRET",
        },
    )

    workflow_manager.save_bsl_credentials.assert_awaited_once_with(
        bsl_id, "NEW-KEY", "NEW-SECRET"
    )
    assert _dispatched(workflow_manager, PrefectAction.SYNC_BSL_UPDATE_CREDENTIALS) == [
        {"bsl_id": str(bsl_id), "namespace": "styrmin"}
    ]


@pytest.mark.asyncio
async def test_delete_bsl_deletes_its_saved_keys(
    client: AsyncClient, session: AsyncSession, workflow_manager: MagicMock
) -> None:
    bsl = await seed_backup_storage_location(session)
    bsl_id = bsl.id

    await gql(
        client,
        "delete_backup_storage_location",
        {"backupStorageLocationId": str(bsl_id)},
    )

    workflow_manager.delete_bsl_credentials.assert_awaited_once_with(bsl_id)
    assert await session.get(BackupStorageLocation, bsl_id) is None


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
