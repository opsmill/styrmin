"""Unit tests for session minting and lookup."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import User
from styrmin_backend.services.auth.session import (
    ABSOLUTE_LIFETIME,
    IDLE_LIFETIME,
    create_session,
    delete_all_sessions_for_user,
    delete_session_by_token,
    lookup_session,
    mint_token,
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


async def _seed_user(db_session: AsyncSession) -> User:
    user = User(
        username="alice",
        password_hash="argon2id$placeholder",
        display_name="Alice",
        active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def test_mint_token_returns_sha256_digest() -> None:
    raw, digest = mint_token()
    assert len(raw) >= 43
    assert digest == hashlib.sha256(raw.encode("ascii")).digest()


def test_mint_token_returns_distinct_tokens() -> None:
    a, _ = mint_token()
    b, _ = mint_token()
    assert a != b


async def test_create_session_persists_and_returns_raw_token(
    db_session: AsyncSession,
) -> None:
    user = await _seed_user(db_session)
    session_row, raw = await create_session(db_session, user.id)
    assert raw
    assert session_row.user_id == user.id
    assert session_row.token_hash == hashlib.sha256(raw.encode("ascii")).digest()


async def test_lookup_session_returns_row_for_valid_token(
    db_session: AsyncSession,
) -> None:
    user = await _seed_user(db_session)
    _row, raw = await create_session(db_session, user.id)
    found = await lookup_session(db_session, raw)
    assert found is not None
    assert found.user_id == user.id


async def test_lookup_session_returns_none_for_unknown_token(
    db_session: AsyncSession,
) -> None:
    found = await lookup_session(db_session, "nonexistent-token")
    assert found is None


async def test_lookup_session_returns_none_when_expired(
    db_session: AsyncSession,
) -> None:
    user = await _seed_user(db_session)
    row, raw = await create_session(db_session, user.id)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.add(row)
    await db_session.commit()
    found = await lookup_session(db_session, raw)
    assert found is None


async def test_lookup_session_returns_none_when_idle_exceeded(
    db_session: AsyncSession,
) -> None:
    user = await _seed_user(db_session)
    row, raw = await create_session(db_session, user.id)
    row.last_used_at = datetime.now(UTC) - IDLE_LIFETIME - timedelta(seconds=1)
    db_session.add(row)
    await db_session.commit()
    found = await lookup_session(db_session, raw)
    assert found is None


async def test_create_session_sets_30_day_expiry(db_session: AsyncSession) -> None:
    user = await _seed_user(db_session)
    row, _ = await create_session(db_session, user.id)
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    delta = expires_at - datetime.now(UTC)
    assert abs(delta - ABSOLUTE_LIFETIME) < timedelta(seconds=5)


async def test_delete_session_by_token_removes_row(
    db_session: AsyncSession,
) -> None:
    user = await _seed_user(db_session)
    _row, raw = await create_session(db_session, user.id)
    deleted = await delete_session_by_token(db_session, raw)
    assert deleted is True
    assert await lookup_session(db_session, raw) is None


async def test_delete_session_by_token_returns_false_for_unknown(
    db_session: AsyncSession,
) -> None:
    deleted = await delete_session_by_token(db_session, "no-such-token")
    assert deleted is False


async def test_delete_all_sessions_for_user_removes_every_row(
    db_session: AsyncSession,
) -> None:
    user = await _seed_user(db_session)
    _row_a, raw_a = await create_session(db_session, user.id)
    _row_b, raw_b = await create_session(db_session, user.id)
    count = await delete_all_sessions_for_user(db_session, user.id)
    assert count == 2
    assert await lookup_session(db_session, raw_a) is None
    assert await lookup_session(db_session, raw_b) is None


async def test_delete_all_sessions_for_user_only_targets_that_user(
    db_session: AsyncSession,
) -> None:
    alice = await _seed_user(db_session)
    bob = User(
        username="bob",
        password_hash="argon2id$placeholder",
        display_name="Bob",
        active=True,
    )
    db_session.add(bob)
    await db_session.commit()
    await db_session.refresh(bob)

    _row_a, raw_alice = await create_session(db_session, alice.id)
    _row_b, raw_bob = await create_session(db_session, bob.id)

    count = await delete_all_sessions_for_user(db_session, alice.id)
    assert count == 1
    assert await lookup_session(db_session, raw_alice) is None
    assert await lookup_session(db_session, raw_bob) is not None
