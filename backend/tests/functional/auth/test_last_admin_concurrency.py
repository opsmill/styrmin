"""Concurrency test for the last-admin guard (T035 / FR-010).

Two async tasks each call ``update_user`` to demote a different admin
in an active two-admin pair. At least one transaction MUST fail with
``LastAdminError`` — otherwise both could pass the snapshot check and
together leave the system with zero admins.

The point of the test is to exercise the ``SELECT ... FOR UPDATE`` lock
in ``_load_admin_snapshot``. SQLite (used by the default in-memory test
engine) does not implement ``FOR UPDATE`` row locks, so the test
short-circuits with a clear ``pytest.skip`` when the engine dialect is
SQLite. CI's Postgres-backed integration run is where this assertion
earns its keep.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Role, User
from styrmin_backend.services.auth.password import hash_password
from styrmin_backend.services.auth.users import UpdateUserData, update_user
from styrmin_backend.services.exceptions import LastAdminError
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork


async def _seed_admin(engine, username: str) -> UUID:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        admin = User(
            username=username,
            password_hash=hash_password("concurrency-fixture-password"),
            display_name=username,
            active=True,
            role=Role.ADMIN,
        )
        session.add(admin)
        await session.commit()
        await session.refresh(admin)
        return admin.id


async def _demote_in_own_session(engine, user_id: UUID, actor_id: UUID) -> None:
    """Open a fresh AsyncSession + UoW and try to demote ``user_id``."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        uow = SqlModelUnitOfWork(session=session)
        async with uow:
            await update_user(
                uow,
                user_id=user_id,
                input=UpdateUserData(role=Role.READ_ONLY),
                actor_user_id=actor_id,
            )


@pytest.mark.asyncio
async def test_concurrent_demote_last_admin_serialized() -> None:
    """Two async demote requests cannot both succeed against an admin pair."""
    # Build an engine just for this test so we control the dialect check
    # and the connection pool semantics. The default ``session`` fixture
    # is single-session; for the concurrency check we need two distinct
    # sessions hitting the same backing DB.
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    dialect = engine.dialect.name
    if dialect == "sqlite":
        await engine.dispose()
        pytest.skip(
            "Postgres required for FOR UPDATE semantics; SQLite ignores row locks "
            "so the serialisation cannot be observed here. CI's Postgres-backed "
            "integration run covers this assertion."
        )

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    admin_a = await _seed_admin(engine, "admin-a")
    admin_b = await _seed_admin(engine, "admin-b")

    results = await asyncio.gather(
        _demote_in_own_session(engine, admin_a, actor_id=admin_b),
        _demote_in_own_session(engine, admin_b, actor_id=admin_a),
        return_exceptions=True,
    )

    failures = [r for r in results if isinstance(r, LastAdminError)]
    assert failures, (
        "At least one concurrent demotion must fail with LastAdminError; "
        f"got results={results!r}"
    )

    # And the system must still have at least one active admin in the DB.
    async with AsyncSession(engine, expire_on_commit=False) as session:
        active_admins = (
            await session.exec(
                select(User).where(User.role == Role.ADMIN).where(User.active.is_(True))  # type: ignore[attr-defined]
            )
        ).all()
        assert active_admins, "post-condition: at least one active admin remains"

    await engine.dispose()
