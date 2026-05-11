"""N+1 protection test for ``Query.users`` (T037 / research.md §D16).

Seeds ten users with varied group memberships, captures every SELECT
emitted through SQLAlchemy's ``before_execute`` event during the
``users`` query, and asserts that exactly **two** SELECT statements
target the user/group tables — one for the user list, one for the
``selectinload(User.groups)`` sweep across the link + group tables.

Anything more than two means we regressed into a per-user lazy-load
loop (the classic N+1 footgun) and the test will fail with a useful
listing of every captured statement so the diagnosis is one glance
long.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Group, Role, User, UserGroup
from styrmin_backend.services.auth.password import hash_password

from tests.functional.graphql._queries import load_query


@pytest.mark.asyncio
async def test_list_users_eager_loads_groups(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    # Seed 10 users plus a handful of groups with varied memberships.
    groups: list[Group] = []
    for i in range(3):
        g = Group(name=f"grp-{i}", role=Role.READ_ONLY)
        session.add(g)
        groups.append(g)
    await session.commit()
    for g in groups:
        await session.refresh(g)

    users: list[User] = []
    for i in range(10):
        u = User(
            username=f"u-{i:02d}",
            password_hash=hash_password("seed-password-here-12"),
            display_name=f"User {i}",
            active=True,
            role=Role.READ_ONLY,
        )
        session.add(u)
        users.append(u)
    await session.commit()
    for u in users:
        await session.refresh(u)

    # Sprinkle memberships: every other user gets one group; every third
    # gets two; one gets all three.
    for i, u in enumerate(users):
        if i % 2 == 0:
            session.add(UserGroup(user_id=u.id, group_id=groups[0].id))
        if i % 3 == 0:
            session.add(UserGroup(user_id=u.id, group_id=groups[1].id))
        if i == 5:
            session.add(UserGroup(user_id=u.id, group_id=groups[2].id))
    await session.commit()

    engine = session.info["_engine"]
    sync_engine = engine.sync_engine

    captured: list[str] = []

    @event.listens_for(sync_engine, "before_execute")
    def _capture(_conn, clauseelement, _multiparams, _params, _execution_options):  # noqa: ARG001
        # Materialise the SQL text; SQLAlchemy compiles it lazily.
        try:
            statement = str(clauseelement)
        except Exception:  # pragma: no cover - defensive
            return
        captured.append(statement)

    try:
        # Exercise the resolver through the real HTTP path so we count
        # the resolver's actual production query pattern, not a service
        # call shortcut.
        response = await admin_client.post(
            "/graphql",
            json={
                "query": load_query("list_users"),
                "variables": {},
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert "errors" not in payload, payload
        assert len(payload["data"]["users"]) >= 10
    finally:
        event.remove(sync_engine, "before_execute", _capture)

    # The HTTP request fires two distinct query paths:
    #   1. Auth-middleware: ``_resolve_current_user`` loads the calling
    #      admin (`WHERE "user".id = :id_1`) and selectinload-sweeps
    #      their groups.
    #   2. Listing resolver: ``list_users`` runs the ordered SELECT
    #      against ``user`` and selectinload-sweeps every listed user's
    #      groups.
    # The N+1 footgun is the *listing* path lazy-loading per-user. We
    # filter to the listing-specific statements and assert exactly two
    # queries (users + groups), independent of the auth-middleware's
    # constant 2-query overhead.
    selects = [s for s in captured if s.lstrip().upper().startswith("SELECT")]
    listing_user_selects = [
        s for s in selects if 'FROM "user"' in s and 'ORDER BY "user".username' in s
    ]
    eager_group_selects = [
        s
        for s in selects
        if 'FROM "user" AS user_1' in s
        and "JOIN user_group" in s
        and 'JOIN "group"' in s
    ]
    assert len(listing_user_selects) == 1, (
        f"Expected exactly 1 listing SELECT against `user`, got "
        f"{len(listing_user_selects)}:\n" + "\n---\n".join(listing_user_selects)
    )
    # Two eager-load sweeps fire: one for the calling user's groups
    # (current_user resolution) and one for the listing's groups. The
    # N+1 contract is that the second one happens *once*, not 10× —
    # which is what the bounded total (2) proves.
    assert len(eager_group_selects) == 2, (
        f"Expected exactly 2 group eager-load sweeps (current_user + "
        f"listing), got {len(eager_group_selects)} — N+1 regression?\n"
        + "\n---\n".join(eager_group_selects)
    )
