"""The install ID created on server start (spec 020, FR-014, critique E2)."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import pytest
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.services.telemetry import install
from styrmin_backend.services.telemetry.install import ensure_install_id
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'install.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def warnings() -> Iterator[list[str]]:
    messages: list[str] = []
    handler_id = logger.add(
        messages.append, level="WARNING", format="{level}|{message}"
    )
    yield messages
    logger.remove(handler_id)


def _sqlite_unit_of_work(engine: AsyncEngine):
    @asynccontextmanager
    async def _get_unit_of_work() -> AsyncGenerator[SqlModelUnitOfWork, None]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with SqlModelUnitOfWork(session) as uow:
                yield uow

    return _get_unit_of_work


async def test_ensure_install_id_creates_one_id_and_keeps_it(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, warnings: list[str]
) -> None:
    monkeypatch.setattr(install, "get_unit_of_work", _sqlite_unit_of_work(engine))

    first = await ensure_install_id()
    second = await ensure_install_id()

    assert isinstance(first, UUID)
    assert second == first
    assert warnings == []


async def test_ensure_install_id_logs_one_warning_and_returns_none_on_failure(
    monkeypatch: pytest.MonkeyPatch, warnings: list[str]
) -> None:
    def _broken_unit_of_work() -> None:
        raise RuntimeError("database is not ready")

    monkeypatch.setattr(install, "get_unit_of_work", _broken_unit_of_work)

    assert await ensure_install_id() is None

    assert warnings == [
        "WARNING|Could not create the telemetry install ID: database is not ready. "
        "No action is needed: the server keeps running, and the next start or daily "
        "report creates the ID.\n"
    ]


async def test_ensure_install_id_survives_a_missing_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, warnings: list[str]
) -> None:
    """A database where the Alembic revision was not applied yet (critique E2)."""
    empty = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}")
    monkeypatch.setattr(install, "get_unit_of_work", _sqlite_unit_of_work(empty))

    try:
        assert await ensure_install_id() is None
    finally:
        await empty.dispose()

    assert len(warnings) == 1
    assert "installation" in warnings[0]
