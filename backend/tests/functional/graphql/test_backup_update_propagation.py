"""Propagation tests for ``updateBackup`` and ``Backup.description`` (#39)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Backup, BackupStatus, Role, User
from styrmin_backend.services.auth.password import hash_password
from styrmin_backend.services.auth.session import create_session

from ._queries import load_query
from .conftest import gql
from .seeds import seed_application_instance


async def _seed_backup(
    session: AsyncSession,
    *,
    instance_id: UUID | None = None,
    name: str = "nightly",
    description: str | None = None,
) -> Backup:
    if instance_id is None:
        instance_id = (await seed_application_instance(session)).id
    backup = Backup(
        name=name,
        description=description,
        status=BackupStatus.COMPLETED,
        instance_id=instance_id,
    )
    session.add(backup)
    await session.commit()
    await session.refresh(backup)
    return backup


async def _post_update(
    client: AsyncClient, variables: dict[str, Any], token: str | None = None
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    response = await client.post(
        "/graphql",
        json={"query": load_query("update_backup"), "variables": variables},
        headers=headers,
    )
    assert response.status_code == 200
    return response.json()


def _error_code(payload: dict[str, Any]) -> str:
    errors = payload.get("errors") or []
    assert errors, payload
    return errors[0]["extensions"]["code"]


@pytest.mark.asyncio
async def test_update_backup_persists_name_and_description(
    client: AsyncClient, session: AsyncSession
) -> None:
    backup_id = (await _seed_backup(session)).id

    data = await gql(
        client,
        "update_backup",
        {
            "backupId": str(backup_id),
            "name": "  before-upgrade ",
            "description": "Taken before the 2.0 upgrade",
        },
    )
    assert data["updateBackup"]["name"] == "before-upgrade"

    session.expire_all()
    row = await session.get(Backup, backup_id)
    assert row is not None
    assert row.name == "before-upgrade"
    assert row.description == "Taken before the 2.0 upgrade"


@pytest.mark.asyncio
async def test_update_backup_empty_description_clears_it(
    client: AsyncClient, session: AsyncSession
) -> None:
    backup_id = (await _seed_backup(session, description="old note")).id

    await gql(client, "update_backup", {"backupId": str(backup_id), "description": ""})

    session.expire_all()
    row = await session.get(Backup, backup_id)
    assert row is not None
    assert row.description is None
    assert row.name == "nightly"


@pytest.mark.asyncio
async def test_backup_description_is_projected(
    client: AsyncClient, session: AsyncSession
) -> None:
    backup = await _seed_backup(session, description="seeded note")

    data = await gql(client, "get_backup_description", {"backupId": str(backup.id)})
    assert data["backup"]["description"] == "seeded note"


@pytest.mark.asyncio
async def test_update_backup_duplicate_name_returns_already_exists(
    client: AsyncClient, session: AsyncSession
) -> None:
    taken = await _seed_backup(session, name="before-upgrade")
    taken_id = taken.id
    backup = await _seed_backup(session, instance_id=taken.instance_id)

    payload = await _post_update(
        client, {"backupId": str(backup.id), "name": "before-upgrade"}
    )
    assert _error_code(payload) == "ALREADY_EXISTS"
    assert payload["errors"][0]["extensions"]["existing_backup_id"] == str(taken_id)


@pytest.mark.parametrize(
    "variables",
    [{"name": "   "}, {"name": "a" * 256}, {"description": "a" * 2001}],
    ids=["blank-name", "long-name", "long-description"],
)
@pytest.mark.asyncio
async def test_update_backup_invalid_input_returns_validation_error(
    client: AsyncClient, session: AsyncSession, variables: dict[str, str]
) -> None:
    backup = await _seed_backup(session)

    payload = await _post_update(client, {"backupId": str(backup.id), **variables})
    assert _error_code(payload) == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_update_backup_unknown_id_returns_not_found(
    client: AsyncClient,
) -> None:
    payload = await _post_update(client, {"backupId": str(uuid4()), "name": "x"})
    assert _error_code(payload) == "NOT_FOUND"


@pytest.mark.asyncio
async def test_update_backup_rejects_read_only_role(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    backup_id = (await _seed_backup(session)).id
    user = User(
        username="reader",
        password_hash=hash_password("reader-password"),
        display_name="Reader",
        active=True,
        role=Role.READ_ONLY,
    )
    session.add(user)
    await session.commit()
    _row, token = await create_session(session, user.id)

    payload = await _post_update(
        unauth_client, {"backupId": str(backup_id), "name": "renamed"}, token=token
    )
    assert _error_code(payload) == "FORBIDDEN"

    session.expire_all()
    row = await session.get(Backup, backup_id)
    assert row is not None
    assert row.name == "nightly"


async def _post_create(
    client: AsyncClient, variables: dict[str, Any]
) -> dict[str, Any]:
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("create_backup_with_description"),
            "variables": variables,
        },
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_create_backup_persists_description(
    client: AsyncClient, session: AsyncSession
) -> None:
    instance_id = (await seed_application_instance(session)).id

    data = await gql(
        client,
        "create_backup_with_description",
        {
            "instanceId": str(instance_id),
            "name": " before-upgrade ",
            "description": "Taken before the 2.0 upgrade",
        },
    )
    created = data["createBackup"]
    assert created["name"] == "before-upgrade"
    assert created["description"] == "Taken before the 2.0 upgrade"

    session.expire_all()
    row = await session.get(Backup, UUID(created["id"]))
    assert row is not None
    assert row.name == "before-upgrade"
    assert row.description == "Taken before the 2.0 upgrade"


@pytest.mark.asyncio
async def test_create_backup_duplicate_name_returns_already_exists(
    client: AsyncClient, session: AsyncSession
) -> None:
    taken = await _seed_backup(session, name="before-upgrade")
    taken_id = taken.id

    payload = await _post_create(
        client, {"instanceId": str(taken.instance_id), "name": "before-upgrade"}
    )
    assert _error_code(payload) == "ALREADY_EXISTS"
    assert payload["errors"][0]["extensions"]["existing_backup_id"] == str(taken_id)
