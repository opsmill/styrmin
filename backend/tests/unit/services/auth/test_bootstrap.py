"""Unit tests for the default-admin bootstrap routine."""

from __future__ import annotations

import asyncio
import io

import pytest
from loguru import logger
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Role, User
from styrmin_backend.services.auth.bootstrap import bootstrap_default_admin


@pytest.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_session(engine):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def warn_sink():
    sink = io.StringIO()
    logger.remove()
    handler_id = logger.add(sink, level="WARNING", format="{level}|{message}")
    yield sink
    logger.remove(handler_id)


async def _user_count(session: AsyncSession) -> int:
    result = await session.exec(select(User))
    return len(list(result.all()))


async def test_bootstrap_creates_user_when_absent(db_session: AsyncSession) -> None:
    inserted_id = await bootstrap_default_admin(
        db_session,
        username="admin",
        password="correct horse battery staple",
    )
    assert inserted_id is not None
    assert await _user_count(db_session) == 1


async def test_bootstrap_is_idempotent_on_second_call(db_session: AsyncSession) -> None:
    first = await bootstrap_default_admin(
        db_session,
        username="admin",
        password="correct horse battery staple",
    )
    second = await bootstrap_default_admin(
        db_session,
        username="admin",
        password="a different password value",
    )
    assert first is not None
    assert second is None
    assert await _user_count(db_session) == 1

    # And the password is NOT rotated on the second call.
    result = await db_session.exec(select(User).where(User.username == "admin"))
    user = result.one()
    from styrmin_backend.services.auth.password import verify_password

    assert verify_password(user.password_hash, "correct horse battery staple") is True
    assert verify_password(user.password_hash, "a different password value") is False


async def test_bootstrap_generated_password_logged_once(
    db_session: AsyncSession, warn_sink: io.StringIO
) -> None:
    first = await bootstrap_default_admin(db_session, username="admin", password=None)
    second = await bootstrap_default_admin(db_session, username="admin", password=None)
    assert first is not None
    assert second is None

    contents = warn_sink.getvalue()
    warn_lines = [line for line in contents.splitlines() if line.startswith("WARNING|")]
    assert len(warn_lines) == 1
    assert "generated password" in warn_lines[0]


async def test_bootstrap_username_is_casefolded(db_session: AsyncSession) -> None:
    inserted_id = await bootstrap_default_admin(
        db_session,
        username="Admin",
        password="correct horse battery staple",
    )
    assert inserted_id is not None
    result = await db_session.exec(select(User))
    user = result.one()
    assert user.username == "admin"


async def test_bootstrap_user_role_is_admin(db_session: AsyncSession) -> None:
    """The seeded admin must have Role.ADMIN — otherwise nothing in the
    fresh-install path can create another admin via API.
    """
    inserted_id = await bootstrap_default_admin(
        db_session,
        username="admin",
        password="correct horse battery staple",
    )
    assert inserted_id is not None
    result = await db_session.exec(select(User).where(User.username == "admin"))
    user = result.one()
    assert user.role == Role.ADMIN


async def test_bootstrap_concurrent_calls_yield_one_user_and_one_log(
    engine, warn_sink: io.StringIO
) -> None:
    """Two concurrent bootstrap calls resolve to exactly one row and one log line.

    Driven through ``asyncio.gather`` over two independent ``AsyncSession``
    instances on the same engine. SQLite serialises writes via the writer
    lock, so the second statement observes the first statement's row and
    falls through ``ON CONFLICT DO NOTHING``; only one ``RETURNING`` yields
    an id, only one WARN log fires.
    """

    async def _run() -> None:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await bootstrap_default_admin(session, username="admin", password=None)

    await asyncio.gather(_run(), _run())

    async with AsyncSession(engine, expire_on_commit=False) as session:
        assert await _user_count(session) == 1

    contents = warn_sink.getvalue()
    warn_lines = [line for line in contents.splitlines() if line.startswith("WARNING|")]
    assert len(warn_lines) == 1
