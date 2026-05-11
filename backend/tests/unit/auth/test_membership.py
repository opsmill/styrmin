"""Unit tests for set-semantics membership replacement.

These tests build a real in-memory SQLite engine because membership
replacement is an SQL operation — the assertion that "no SQL is issued
when nothing changes" is the whole point of the helper. A fake/mock
session would defeat the test.

The statement counter hooks into ``before_execute`` per SQLAlchemy
event API and counts INSERTs/DELETEs touching the ``user_group`` link
table. Per ``research.md`` §D2 / data-model.md "no-op produces zero
INSERT/DELETE".
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Group, Role, User, UserGroup
from styrmin_backend.services.auth.membership import (
    replace_group_members,
    replace_user_groups,
)
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork

# Regexes match against the rendered (no-bind-param) SQL emitted by
# SQLAlchemy's ``before_execute`` event. They are deliberately permissive
# so identifier-quoting differences across dialects don't break them.
_INSERT_USER_GROUP_RE = re.compile(r"INSERT\s+INTO\s+\"?user_group\"?", re.IGNORECASE)
_DELETE_USER_GROUP_RE = re.compile(r"DELETE\s+FROM\s+\"?user_group\"?", re.IGNORECASE)


class _Counter:
    """Counts INSERT/DELETE statements touching ``user_group``."""

    def __init__(self) -> None:
        self.inserts = 0
        self.deletes = 0

    def install(self, engine) -> None:
        @event.listens_for(engine.sync_engine, "before_execute")
        def _before_execute(
            _conn,
            clauseelement,
            _multiparams,
            _params,
            _execution_options,
        ) -> None:  # pragma: no cover - exercised indirectly
            text = str(clauseelement)
            if _INSERT_USER_GROUP_RE.search(text):
                self.inserts += 1
            elif _DELETE_USER_GROUP_RE.search(text):
                self.deletes += 1


@pytest.fixture
async def engine_and_session() -> AsyncGenerator[tuple, None]:
    """In-memory SQLite with the full SQLModel schema created.

    Yields ``(engine, session)`` so individual tests can attach the
    ``before_execute`` listener to the engine before issuing statements.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield engine, session
    await engine.dispose()


async def _make_users_and_groups(
    session: AsyncSession,
    n_users: int,
    n_groups: int,
) -> tuple[list[UUID], list[UUID]]:
    """Insert ``n_users`` users and ``n_groups`` groups; return their ids."""
    users: list[UUID] = []
    for i in range(n_users):
        user = User(
            username=f"user-{i}-{uuid4().hex[:8]}",
            password_hash="hash",
            display_name=f"User {i}",
            active=True,
            role=Role.READ_ONLY,
        )
        session.add(user)
        await session.flush()
        users.append(user.id)
    groups: list[UUID] = []
    for i in range(n_groups):
        group = Group(name=f"group-{i}-{uuid4().hex[:8]}", role=Role.READ_ONLY)
        session.add(group)
        await session.flush()
        groups.append(group.id)
    await session.commit()
    return users, groups


@pytest.mark.asyncio
async def test_replace_user_groups_empty_to_populated(engine_and_session) -> None:
    engine, session = engine_and_session
    users, groups = await _make_users_and_groups(session, 1, 3)

    async with SqlModelUnitOfWork(session) as uow:
        added, removed = await replace_user_groups(
            uow, user_id=users[0], group_ids=groups
        )
        await uow.commit()

    assert (added, removed) == (3, 0)


@pytest.mark.asyncio
async def test_replace_user_groups_populated_to_different(engine_and_session) -> None:
    engine, session = engine_and_session
    users, groups = await _make_users_and_groups(session, 1, 4)
    # Seed initial memberships: groups[0], groups[1]
    for gid in groups[:2]:
        session.add(UserGroup(user_id=users[0], group_id=gid))
    await session.commit()

    async with SqlModelUnitOfWork(session) as uow:
        added, removed = await replace_user_groups(
            uow,
            user_id=users[0],
            # New set: groups[1], groups[2], groups[3] — keep [1], add
            # [2] and [3], drop [0].
            group_ids=[groups[1], groups[2], groups[3]],
        )
        await uow.commit()

    assert (added, removed) == (2, 1)


@pytest.mark.asyncio
async def test_replace_user_groups_populated_to_empty(engine_and_session) -> None:
    engine, session = engine_and_session
    users, groups = await _make_users_and_groups(session, 1, 2)
    for gid in groups:
        session.add(UserGroup(user_id=users[0], group_id=gid))
    await session.commit()

    async with SqlModelUnitOfWork(session) as uow:
        added, removed = await replace_user_groups(uow, user_id=users[0], group_ids=[])
        await uow.commit()

    assert (added, removed) == (0, 2)


@pytest.mark.asyncio
async def test_replace_user_groups_noop_emits_no_statements(
    engine_and_session,
) -> None:
    engine, session = engine_and_session
    users, groups = await _make_users_and_groups(session, 1, 2)
    for gid in groups:
        session.add(UserGroup(user_id=users[0], group_id=gid))
    await session.commit()

    counter = _Counter()
    counter.install(engine)

    async with SqlModelUnitOfWork(session) as uow:
        added, removed = await replace_user_groups(
            uow, user_id=users[0], group_ids=list(groups)
        )
        # No commit needed — there is nothing to flush. We still call
        # it so the test mirrors the happy-path shape.
        await uow.commit()

    assert (added, removed) == (0, 0)
    assert counter.inserts == 0, "no-op replacement must not INSERT"
    assert counter.deletes == 0, "no-op replacement must not DELETE"


@pytest.mark.asyncio
async def test_replace_group_members_empty_to_populated(engine_and_session) -> None:
    engine, session = engine_and_session
    users, groups = await _make_users_and_groups(session, 3, 1)

    async with SqlModelUnitOfWork(session) as uow:
        added, removed = await replace_group_members(
            uow, group_id=groups[0], member_ids=users
        )
        await uow.commit()

    assert (added, removed) == (3, 0)


@pytest.mark.asyncio
async def test_replace_group_members_noop_emits_no_statements(
    engine_and_session,
) -> None:
    engine, session = engine_and_session
    users, groups = await _make_users_and_groups(session, 2, 1)
    for uid in users:
        session.add(UserGroup(user_id=uid, group_id=groups[0]))
    await session.commit()

    counter = _Counter()
    counter.install(engine)

    async with SqlModelUnitOfWork(session) as uow:
        added, removed = await replace_group_members(
            uow, group_id=groups[0], member_ids=list(users)
        )
        await uow.commit()

    assert (added, removed) == (0, 0)
    assert counter.inserts == 0
    assert counter.deletes == 0
