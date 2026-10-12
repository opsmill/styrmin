"""Round trip of the revision that indexes the backup history lookups (#427)."""

import asyncio
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from styrmin_backend.cli.db import _get_alembic_config
from styrmin_backend.db import utils as db_utils

REVISION = "9548830f81cd"
PREVIOUS_REVISION = "7af6824e820d"
# Each table's new index, as ``create_all()`` names it from the model.
INDEXES = {"backup": "ix_backup_instance_id", "restore": "ix_restore_backup_id"}


@pytest.fixture(params=["postgresql", "sqlite"])
def database_url(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    if request.param == "postgresql":
        url = request.getfixturevalue("postgres_url")
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'backup_history.db'}"
    # ``migrations/env.py`` resolves the URL through this function on each command.
    monkeypatch.setattr(db_utils, "get_database_url", lambda: url)
    return url


def _indexes(url: str) -> dict[str, dict[str, list[str | None]]]:
    def read(connection: sa.Connection) -> dict[str, dict[str, list[str | None]]]:
        inspector = sa.inspect(connection)
        return {
            table: {
                str(index["name"]): index["column_names"]
                for index in inspector.get_indexes(table)
            }
            for table in INDEXES
        }

    async def run() -> dict[str, dict[str, list[str | None]]]:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(read)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_upgrade_creates_the_model_indexes_and_downgrade_drops_them(
    database_url: str,
) -> None:
    alembic_config = _get_alembic_config()
    command.upgrade(alembic_config, REVISION)

    indexes = _indexes(database_url)
    assert indexes["backup"][INDEXES["backup"]] == ["instance_id"]
    assert indexes["restore"][INDEXES["restore"]] == ["backup_id"]

    command.downgrade(alembic_config, PREVIOUS_REVISION)

    indexes = _indexes(database_url)
    assert INDEXES["backup"] not in indexes["backup"]
    assert INDEXES["restore"] not in indexes["restore"]


def test_the_model_declares_the_indexes_the_revision_creates() -> None:
    for table, name in INDEXES.items():
        model_indexes = {
            index.name for index in SQLModel.metadata.tables[table].indexes
        }
        assert name in model_indexes
