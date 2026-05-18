"""Propagation tests for the new User/Group fields. See ADR-025.

Verifies that ``User.role``, ``User.effectiveRole``, ``User.groups``,
and ``Group`` round-trip correctly from the DB through the GraphQL
schema for an admin caller (the field-level admin gate is exercised in
``test_authz_enforcement.py``).
"""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Group, Role, User, UserGroup
from styrmin_backend.services.auth.password import hash_password
from styrmin_backend.services.auth.session import create_session

from ._queries import load_query

PASSWORD = "correct horse battery staple"


async def _seed_admin_with_groups(
    session: AsyncSession,
    *,
    username: str,
    direct_role: Role,
    group_specs: list[tuple[str, Role]],
) -> tuple[User, list[Group], str]:
    """Seed a user, attached groups, and a session token. Returns the trio."""
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
        link = UserGroup(user_id=user.id, group_id=g.id)
        session.add(link)
    await session.commit()
    _row, raw_token = await create_session(session, user.id)
    return user, groups, raw_token


@pytest.mark.asyncio
async def test_user_role_propagates_for_admin_caller(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    user, _groups, token = await _seed_admin_with_groups(
        session,
        username="admin-only",
        direct_role=Role.ADMIN,
        group_specs=[],
    )

    response = await unauth_client.post(
        "/graphql",
        json={"query": load_query("admin_current_user")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    data = payload["data"]["currentUser"]
    assert UUID(data["id"]) == user.id
    assert data["username"] == "admin-only"
    assert data["role"] == "ADMIN"
    assert data["effectiveRole"] == "ADMIN"
    assert data["active"] is True
    assert data["groups"] == []


@pytest.mark.asyncio
async def test_effective_role_picks_highest_group_role(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    """ADR-025: groups grant capabilities, never revoke them.

    A direct READ_ONLY user joined to ADMIN + READ_WRITE groups
    surfaces ``effectiveRole = ADMIN`` while ``role = READ_ONLY``.
    """
    _user, _groups, token = await _seed_admin_with_groups(
        session,
        username="elevated",
        direct_role=Role.ADMIN,  # admin, so the gated fields resolve
        group_specs=[("ops", Role.READ_WRITE), ("admins", Role.ADMIN)],
    )

    response = await unauth_client.post(
        "/graphql",
        json={"query": load_query("admin_current_user")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    data = payload["data"]["currentUser"]
    assert data["role"] == "ADMIN"
    assert data["effectiveRole"] == "ADMIN"
    by_name = {g["name"]: g for g in data["groups"]}
    assert set(by_name) == {"ops", "admins"}
    assert by_name["ops"]["role"] == "READ_WRITE"
    assert by_name["admins"]["role"] == "ADMIN"
