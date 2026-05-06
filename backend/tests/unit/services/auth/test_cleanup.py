"""Unit tests for the daily session-cleanup sweep."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Session as SessionModel
from styrmin_backend.db.models import User
from styrmin_backend.services.auth.cleanup import delete_expired_sessions
from styrmin_backend.services.auth.session import (
    IDLE_LIFETIME,
    create_session,
)


@pytest.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


async def _seed_user(db_session: AsyncSession, username: str = "alice") -> User:
    user = User(
        username=username,
        password_hash="argon2id$placeholder",
        display_name=username.title(),
        active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def test_cleanup_deletes_absolute_expired_rows(
    db_session: AsyncSession,
) -> None:
    user = await _seed_user(db_session)
    row, _ = await create_session(db_session, user.id)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.add(row)
    await db_session.commit()

    deleted = await delete_expired_sessions(db_session)
    assert deleted == 1
    remaining = await db_session.exec(select(SessionModel))
    assert remaining.first() is None


async def test_cleanup_deletes_idle_expired_rows(
    db_session: AsyncSession,
) -> None:
    user = await _seed_user(db_session)
    row, _ = await create_session(db_session, user.id)
    row.last_used_at = datetime.now(UTC) - IDLE_LIFETIME - timedelta(minutes=1)
    db_session.add(row)
    await db_session.commit()

    deleted = await delete_expired_sessions(db_session)
    assert deleted == 1
    remaining = await db_session.exec(select(SessionModel))
    assert remaining.first() is None


async def test_cleanup_leaves_active_rows_untouched(
    db_session: AsyncSession,
) -> None:
    user = await _seed_user(db_session)
    row_active, _ = await create_session(db_session, user.id)
    row_expired, _ = await create_session(db_session, user.id)
    row_expired.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.add(row_expired)
    await db_session.commit()

    deleted = await delete_expired_sessions(db_session)
    assert deleted == 1

    remaining = (await db_session.exec(select(SessionModel))).all()
    assert len(remaining) == 1
    assert remaining[0].id == row_active.id


async def test_cleanup_is_idempotent_on_clean_table(
    db_session: AsyncSession,
) -> None:
    user = await _seed_user(db_session)
    await create_session(db_session, user.id)

    first = await delete_expired_sessions(db_session)
    second = await delete_expired_sessions(db_session)
    assert first == 0
    assert second == 0
    remaining = (await db_session.exec(select(SessionModel))).all()
    assert len(remaining) == 1


async def test_cleanup_repeated_call_after_purge_is_noop(
    db_session: AsyncSession,
) -> None:
    user = await _seed_user(db_session)
    row, _ = await create_session(db_session, user.id)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.add(row)
    await db_session.commit()

    assert await delete_expired_sessions(db_session) == 1
    assert await delete_expired_sessions(db_session) == 0
