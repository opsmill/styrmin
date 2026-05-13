"""Inactive-user session resolution.

A session belonging to a deactivated user must resolve to
``current_user = None`` so ``RequiresAuthentication`` rejects the
request with ``UNAUTHENTICATED``. The session-delete in ``update_user``
is the primary defence; this read-side filter closes the window between
the row being deactivated and its sessions being reaped.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from fastapi import Request
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.api.dependency import _resolve_current_user
from styrmin_backend.db.models import Role, User
from styrmin_backend.services.auth.password import hash_password
from styrmin_backend.services.auth.session import create_session


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as ses:
        yield ses
    await engine.dispose()


def _bearer_request(token: str) -> Request:
    """Build a minimal ASGI scope so ``_extract_token`` finds the Bearer header."""
    scope = {
        "type": "http",
        "headers": [(b"authorization", f"Bearer {token}".encode("ascii"))],
    }
    return Request(scope)


async def _seed_user(db_session: AsyncSession, *, active: bool) -> User:
    user = User(
        username="resolved",
        password_hash=hash_password("placeholder-password"),
        display_name="Resolved",
        active=active,
        role=Role.READ_ONLY,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_resolve_current_user_returns_user_when_active(
    db_session: AsyncSession,
) -> None:
    user = await _seed_user(db_session, active=True)
    _row, raw_token = await create_session(db_session, user.id)

    request = _bearer_request(raw_token)
    resolved_user, resolved_session = await _resolve_current_user(request, db_session)

    assert resolved_user is not None
    assert resolved_user.id == user.id
    assert resolved_session is not None


@pytest.mark.asyncio
async def test_resolve_current_user_returns_none_when_user_is_inactive(
    db_session: AsyncSession,
) -> None:
    """A stale session whose user was deactivated mid-window MUST resolve
    to ``(None, None)`` so the request is rejected as unauthenticated.
    Otherwise ``RequiresRole`` would read ``effective_role`` off the
    deactivated row and let the principal keep acting on stale data.
    """
    user = await _seed_user(db_session, active=True)
    _row, raw_token = await create_session(db_session, user.id)

    # Simulate deactivation without explicit session cleanup — the row
    # might still exist if a write committed but the session-delete in
    # the same transaction hadn't yet propagated, or if a race left an
    # orphan session in flight.
    user.active = False
    db_session.add(user)
    await db_session.commit()

    request = _bearer_request(raw_token)
    resolved_user, resolved_session = await _resolve_current_user(request, db_session)

    assert resolved_user is None, (
        "An inactive user must NOT be returned as the current_user; the "
        "request would otherwise pass the auth gate and operate on a "
        "deactivated principal until the orphan session is reaped."
    )
    assert resolved_session is None
