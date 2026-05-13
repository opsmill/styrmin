"""Atomicity tests for the deactivate / password-rotate paths.

The session-delete helpers (``delete_all_sessions_for_user`` /
``delete_other_sessions_for_user``) intentionally do NOT commit — the
caller wraps the session-delete + the originating write (active flip,
password rotation) in a single transaction so a failure on either side
rolls BOTH back. These tests simulate the failure and assert neither
side persists.

See research.md §D15 and ``services/auth/session.py`` for the contract.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Role, User
from styrmin_backend.services.auth import session as session_module
from styrmin_backend.services.auth.password_change import change_password
from styrmin_backend.services.auth.password import hash_password, verify_password
from styrmin_backend.services.auth.session import create_session, lookup_session
from styrmin_backend.services.auth.users import UpdateUserData, update_user
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork


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


async def _seed_admin_user(
    db_session: AsyncSession, *, username: str = "admin0", active: bool = True
) -> User:
    user = User(
        username=username,
        password_hash=hash_password("original-password"),
        display_name=username,
        active=active,
        role=Role.ADMIN,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_normal_user(
    db_session: AsyncSession, *, username: str = "regular0"
) -> User:
    user = User(
        username=username,
        password_hash=hash_password("original-password"),
        display_name=username,
        active=True,
        role=Role.READ_WRITE,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _user_active(db_session: AsyncSession, user_id: UUID) -> bool:
    """Re-read ``active`` from the database, bypassing any identity-map cache."""
    # Reissue a SELECT against the rolled-back transaction. We avoid
    # ``expire_all()`` because the subsequent attribute access would
    # trigger a lazy-load through the sync API and trip the missing-
    # greenlet error on the async engine.
    stmt = select(User.active).where(User.id == user_id)  # type: ignore[arg-type]
    result = await db_session.exec(stmt)
    value = result.first()
    assert value is not None
    return bool(value)


@pytest.mark.asyncio
async def test_update_user_deactivation_rolls_back_when_session_delete_fails(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the in-flight session-delete blows up, the ``active`` flip must
    roll back too. We monkeypatch the helper at the call-site import in
    ``services.auth.users`` so the deactivation path raises after the
    user row has been flushed but before the commit fires.
    """
    actor = await _seed_admin_user(db_session, username="actor-admin")
    # Need a second admin so the last-admin guard doesn't fire first.
    target = await _seed_admin_user(db_session, username="target-admin")
    # Capture identifiers eagerly. The failed transaction below will
    # expire the ORM objects, so attribute access after rollback would
    # otherwise trigger a sync lazy-load and trip the missing-greenlet
    # error on the async engine.
    actor_id = actor.id
    target_id = target.id
    _row, raw_token = await create_session(db_session, target_id)

    boom_message = "simulated session-delete failure"

    async def _boom(*args, **kwargs):  # noqa: ANN001, ARG001
        raise RuntimeError(boom_message)

    monkeypatch.setattr(
        "styrmin_backend.services.auth.users.delete_all_sessions_for_user",
        _boom,
    )

    with pytest.raises(RuntimeError, match=boom_message):
        async with SqlModelUnitOfWork(db_session) as uow:
            await update_user(
                uow,
                user_id=target_id,
                input=UpdateUserData(active=False),
                actor_user_id=actor_id,
            )

    # Roll back the failed transaction the way the resolver would.
    await db_session.rollback()

    # Both sides must remain intact:
    #  - user.active is still True (the flip rolled back)
    assert await _user_active(db_session, target_id) is True
    #  - the existing session is still usable
    found = await lookup_session(db_session, raw_token)
    assert found is not None, (
        "Deactivation failed midway through; the session row must still "
        "exist because the entire transaction must roll back."
    )


@pytest.mark.asyncio
async def test_change_password_rolls_back_when_session_delete_fails(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symmetric guard for the password-rotate path: if the other-sessions
    delete raises, the new password must NOT be persisted.
    """
    user = await _seed_normal_user(db_session, username="rotator")
    # Capture id before the failed transaction can expire the row.
    user_id = user.id
    calling_row, calling_raw = await create_session(db_session, user_id)
    other_row, other_raw = await create_session(db_session, user_id)
    calling_row_id = calling_row.id
    assert calling_row_id != other_row.id

    boom_message = "simulated other-sessions delete failure"

    async def _boom(*args, **kwargs):  # noqa: ANN001, ARG001
        raise RuntimeError(boom_message)

    monkeypatch.setattr(
        "styrmin_backend.services.auth.password_change.delete_other_sessions_for_user",
        _boom,
    )

    with pytest.raises(RuntimeError, match=boom_message):
        await change_password(
            db_session,
            user=user,
            current_password="original-password",
            new_password="new-password-xyz",
            calling_session_id=calling_row_id,
        )

    # Roll back the failed transaction the way the resolver would.
    await db_session.rollback()

    # Re-read the password hash directly via SELECT to avoid expired-row
    # lazy-loads through the sync API.
    result = await db_session.exec(
        select(User.password_hash).where(User.id == user_id)  # type: ignore[arg-type]
    )
    password_hash = result.first()
    assert password_hash is not None
    assert verify_password(password_hash, "original-password"), (
        "Password rotation failed midway through; the password must remain "
        "the original so the entire transaction rolls back atomically."
    )
    # Both sessions must still resolve.
    assert await lookup_session(db_session, calling_raw) is not None
    assert await lookup_session(db_session, other_raw) is not None


@pytest.mark.asyncio
async def test_session_helpers_do_not_commit_on_their_own(
    db_session: AsyncSession,
) -> None:
    """Belt-and-suspenders for the contract change: invoking the helpers
    against an open transaction must not flush a commit. A subsequent
    rollback must restore the rows.
    """
    user = await _seed_normal_user(db_session, username="committer")
    _row, raw = await create_session(db_session, user.id)

    count = await session_module.delete_all_sessions_for_user(db_session, user.id)
    assert count == 1
    await db_session.rollback()

    db_session.expire_all()
    found = await lookup_session(db_session, raw)
    assert found is not None
