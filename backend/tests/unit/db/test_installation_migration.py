"""Round trip of the add-installation revision (spec 020) on PostgreSQL and SQLite."""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from styrmin_backend.cli.db import _get_alembic_config
from styrmin_backend.db import utils as db_utils

INSTALLATION_REVISION = "3b926acd0791"
PREVIOUS_REVISION = "c2ff6dba5ffd"
INSTALLATION_COLUMNS = {"id", "install_id", "created_on"}


@pytest.fixture(params=["postgresql", "sqlite"])
def database_url(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    if request.param == "postgresql":
        url = request.getfixturevalue("postgres_url")
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'installation.db'}"
    # ``migrations/env.py`` resolves the URL through this function on each command.
    monkeypatch.setattr(db_utils, "get_database_url", lambda: url)
    return url


def _installation_columns(url: str) -> set[str] | None:
    """Column names of ``installation``, or None when the table does not exist."""

    def inspect(connection: sa.Connection) -> set[str] | None:
        inspector = sa.inspect(connection)
        if "installation" not in inspector.get_table_names():
            return None
        return {column["name"] for column in inspector.get_columns("installation")}

    async def read() -> set[str] | None:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(inspect)
        finally:
            await engine.dispose()

    return asyncio.run(read())


def _insert_rows(url: str, *ids: int) -> None:
    async def insert() -> None:
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                for row_id in ids:
                    await connection.execute(
                        sa.text(
                            "INSERT INTO installation (id, install_id) VALUES (:id, :install_id)"
                        ),
                        {"id": row_id, "install_id": str(uuid4())},
                    )
        finally:
            await engine.dispose()

    asyncio.run(insert())


def test_installation_revision_upgrades_and_downgrades(database_url: str) -> None:
    alembic_config = _get_alembic_config()

    command.upgrade(alembic_config, INSTALLATION_REVISION)
    assert _installation_columns(database_url) == INSTALLATION_COLUMNS

    _insert_rows(database_url, 1)
    with pytest.raises(sa.exc.IntegrityError, match="ck_installation_single_row"):
        _insert_rows(database_url, 2)

    command.downgrade(alembic_config, PREVIOUS_REVISION)
    assert _installation_columns(database_url) is None
