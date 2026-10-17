"""A failing ``async with uow`` block inside a savepoint rolls back only that savepoint (021 review F1),
and ``commit()`` inside a savepoint is refused.

Runs on the real SQLModel session (in-memory SQLite). Outside a savepoint the
whole transaction still rolls back, as before.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Cluster
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
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


async def _add(session: AsyncSession, name: str) -> None:
    session.add(Cluster(name=name, config={}))
    await session.flush()


async def _names(session: AsyncSession) -> set[str]:
    return set((await session.exec(select(Cluster.name))).all())


async def test_failure_inside_a_savepoint_rolls_back_only_that_savepoint(
    session: AsyncSession,
) -> None:
    uow = SqlModelUnitOfWork(session)
    async with uow:
        await _add(session, "before")
        with pytest.raises(RuntimeError):
            async with session.begin_nested():
                await _add(session, "in-savepoint")
                async with uow:
                    raise RuntimeError("simulated failure")
        await _add(session, "after")
        await uow.commit()

    assert await _names(session) == {"before", "after"}


async def test_failure_in_nested_blocks_inside_a_savepoint_keeps_the_callers_work(
    session: AsyncSession,
) -> None:
    """Two ``async with uow`` levels inside the savepoint, as context generation and the reference resolver open."""
    uow = SqlModelUnitOfWork(session)
    async with uow:
        await _add(session, "before")
        try:
            async with session.begin_nested():
                async with uow:
                    async with uow:
                        await _add(session, "in-savepoint")
                        raise RuntimeError("simulated failure")
        except RuntimeError:
            pass
        await _add(session, "after")
        await uow.commit()

    assert await _names(session) == {"before", "after"}


async def test_uncaught_failure_in_nested_blocks_inside_a_savepoint_rolls_back_everything(
    session: AsyncSession,
) -> None:
    uow = SqlModelUnitOfWork(session)
    with pytest.raises(RuntimeError):
        async with uow:
            await _add(session, "before")
            async with session.begin_nested():
                async with uow:
                    async with uow:
                        await _add(session, "in-savepoint")
                        raise RuntimeError("simulated failure")

    assert await _names(session) == set()


async def test_failure_outside_a_savepoint_rolls_back_the_whole_transaction(
    session: AsyncSession,
) -> None:
    uow = SqlModelUnitOfWork(session)
    with pytest.raises(RuntimeError):
        async with uow:
            await _add(session, "before")
            async with uow:
                raise RuntimeError("simulated failure")

    assert await _names(session) == set()


async def test_commit_inside_a_savepoint_is_refused(session: AsyncSession) -> None:
    uow = SqlModelUnitOfWork(session)
    async with uow:
        await _add(session, "before")
        with pytest.raises(RuntimeError, match="inside a savepoint"):
            async with session.begin_nested():
                await _add(session, "in-savepoint")
                await uow.commit()
        await uow.rollback()

    assert await _names(session) == set()
