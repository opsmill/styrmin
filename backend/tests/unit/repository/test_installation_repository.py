"""The install ID is created once and then read back (spec 020, D10)."""

import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Installation
from styrmin_backend.repository.installation import SQLModelInstallationRepository


async def _row_count(session: AsyncSession) -> int:
    result = await session.exec(select(func.count()).select_from(Installation))
    return result.one()


async def _get_or_create_and_commit(session: AsyncSession) -> UUID:
    install_id = await SQLModelInstallationRepository(
        session
    ).get_or_create_install_id()
    await session.commit()
    return install_id


async def _assert_one_stable_install_id(session: AsyncSession) -> None:
    first = await _get_or_create_and_commit(session)
    again = await _get_or_create_and_commit(session)
    engine = session.bind
    assert isinstance(engine, AsyncEngine)
    async with AsyncSession(engine) as other_session:
        from_other_session = await _get_or_create_and_commit(other_session)
        rows = await _row_count(other_session)

    assert isinstance(first, UUID)
    assert again == first
    assert from_other_session == first
    assert rows == 1


async def test_first_call_creates_one_row(session: AsyncSession) -> None:
    install_id = await _get_or_create_and_commit(session)

    assert isinstance(install_id, UUID)
    assert await _row_count(session) == 1


async def test_later_calls_return_the_same_id_on_sqlite(
    session: AsyncSession,
) -> None:
    await _assert_one_stable_install_id(session)


async def test_later_calls_return_the_same_id_on_postgresql(
    postgres_url: str,
) -> None:
    engine = create_async_engine(postgres_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
        async with AsyncSession(engine) as session:
            await _assert_one_stable_install_id(session)
    finally:
        await engine.dispose()


async def test_concurrent_first_calls_agree_on_postgresql(postgres_url: str) -> None:
    engine = create_async_engine(postgres_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
        async with AsyncSession(engine) as first, AsyncSession(engine) as second:
            first_id = await SQLModelInstallationRepository(
                first
            ).get_or_create_install_id()
            second_call = asyncio.create_task(_get_or_create_and_commit(second))
            await asyncio.sleep(0.5)
            waited = not second_call.done()
            await first.commit()
            second_id = await asyncio.wait_for(second_call, timeout=10)
            rows = await _row_count(second)
    finally:
        await engine.dispose()

    # The second insert waits on the first transaction's uncommitted row, then does nothing.
    assert waited
    assert second_id == first_id
    assert rows == 1
