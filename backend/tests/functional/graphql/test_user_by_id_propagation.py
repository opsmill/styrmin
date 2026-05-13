"""Propagation tests for ``Query.user(id:)`` and ``Query.group(id:)``.

These resolvers were added to back the SDK's single-record ``users.get()``
and ``groups.get()`` calls so the client no longer fetches the full admin
list and filters locally (theme F, review-response phase 3).

Each test seeds state through the real DB session, drives the resolver
over the HTTP transport with an admin bearer, and asserts that the row
projected back through GraphQL matches the persisted state. The
``USER_NOT_FOUND`` / ``GROUP_NOT_FOUND`` paths are also exercised so the
SDK's error mapping has end-to-end coverage.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Group, Role, User, UserGroup
from styrmin_backend.services.auth.password import hash_password

from ._queries import load_query

PASSWORD = "correct horse battery staple"


async def _seed_user_with_groups(
    session: AsyncSession,
    *,
    username: str,
    direct_role: Role,
    group_specs: list[tuple[str, Role]],
) -> tuple[User, list[Group]]:
    """Persist a user and N groups, link them, and return the rows."""
    user = User(
        username=username,
        password_hash=hash_password(PASSWORD),
        display_name=username,
        active=True,
        role=direct_role,
    )
    session.add(user)
    groups: list[Group] = []
    for name, role in group_specs:
        group = Group(name=name, role=role)
        session.add(group)
        groups.append(group)
    await session.commit()
    await session.refresh(user)
    for g in groups:
        await session.refresh(g)
        session.add(UserGroup(user_id=user.id, group_id=g.id))
    await session.commit()
    return user, groups


@pytest.mark.asyncio
async def test_user_by_id_projects_db_row(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``Query.user(id:)`` reads the persisted user and resolves its groups."""
    user, groups = await _seed_user_with_groups(
        session,
        username="target",
        direct_role=Role.READ_WRITE,
        group_specs=[("ops", Role.ADMIN)],
    )

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("get_user_by_id"),
            "variables": {"id": str(user.id)},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    data = payload["data"]["user"]
    assert data is not None
    assert UUID(data["id"]) == user.id
    assert data["username"] == "target"
    assert data["role"] == "READ_WRITE"
    # Group ADMIN > direct READ_WRITE → effectiveRole bubbles up.
    assert data["effectiveRole"] == "ADMIN"
    assert data["active"] is True
    assert len(data["groups"]) == 1
    assert data["groups"][0]["name"] == "ops"
    assert UUID(data["groups"][0]["id"]) == groups[0].id


@pytest.mark.asyncio
async def test_user_by_id_unknown_surfaces_user_not_found(
    client: AsyncClient, session: AsyncSession
) -> None:
    """An unknown id surfaces ``USER_NOT_FOUND`` via extensions.code."""
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("get_user_by_id"),
            "variables": {"id": str(uuid4())},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["user"] is None
    errors = payload.get("errors") or []
    assert errors, payload
    assert errors[0]["extensions"]["code"] == "USER_NOT_FOUND"


@pytest.mark.asyncio
async def test_group_by_id_projects_db_row(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``Query.group(id:)`` reads the persisted group."""
    group = Group(name="engineers", role=Role.READ_WRITE)
    session.add(group)
    await session.commit()
    await session.refresh(group)

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("get_group_by_id"),
            "variables": {"id": str(group.id)},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    data = payload["data"]["group"]
    assert data is not None
    assert UUID(data["id"]) == group.id
    assert data["name"] == "engineers"
    assert data["role"] == "READ_WRITE"


@pytest.mark.asyncio
async def test_group_by_id_unknown_surfaces_group_not_found(
    client: AsyncClient, session: AsyncSession
) -> None:
    """An unknown id surfaces ``GROUP_NOT_FOUND`` via extensions.code."""
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("get_group_by_id"),
            "variables": {"id": str(uuid4())},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["group"] is None
    errors = payload.get("errors") or []
    assert errors, payload
    assert errors[0]["extensions"]["code"] == "GROUP_NOT_FOUND"
