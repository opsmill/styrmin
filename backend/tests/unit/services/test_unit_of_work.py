"""Session lifecycle of the standalone and request-scoped units of work (#140)."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db import utils as db_utils
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork, get_unit_of_work


@pytest.fixture
async def engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[AsyncEngine, None]:
    # A file database gets a queue pool, whose checked-out count is the leak signal.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'uow.db'}")
    monkeypatch.setattr(db_utils, "get_async_engine", lambda: engine)
    yield engine
    await engine.dispose()


async def test_standalone_unit_of_work_returns_its_connection(
    engine: AsyncEngine,
) -> None:
    async with get_unit_of_work() as uow:
        await uow.session.connection()
        assert engine.pool.checkedout() == 1  # type: ignore[attr-defined]

    assert engine.pool.checkedout() == 0  # type: ignore[attr-defined]
    assert not uow.session.in_transaction()


async def test_standalone_unit_of_work_returns_its_connection_on_error(
    engine: AsyncEngine,
) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        async with get_unit_of_work() as uow:
            await uow.session.connection()
            raise RuntimeError("boom")

    assert engine.pool.checkedout() == 0  # type: ignore[attr-defined]


async def test_standalone_unit_of_work_binds_repositories(engine: AsyncEngine) -> None:
    async with get_unit_of_work() as uow:
        assert uow.deployments.session is uow.session


async def test_unit_of_work_block_does_not_end_the_session(
    engine: AsyncEngine,
) -> None:
    """``async with uow`` is a transaction block; the request path re-enters it."""
    async with AsyncSession(engine) as session:
        uow = SqlModelUnitOfWork(session=session)
        async with uow:
            await session.connection()
        async with uow:
            assert session.in_transaction()
            assert engine.pool.checkedout() == 1  # type: ignore[attr-defined]
