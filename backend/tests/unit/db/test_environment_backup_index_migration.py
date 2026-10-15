"""Round trip of the revision that indexes the environment backup links (#455)."""

import asyncio
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from styrmin_backend.cli.db import _get_alembic_config
from styrmin_backend.db import utils as db_utils

REVISION = "33b679d3d5dd"
PREVIOUS_REVISION = "9548830f81cd"
# Each table's new index and its column, as ``create_all()`` names it from the model.
INDEXES = {
    "environmentbackup": ("ix_environmentbackup_environment_id", "environment_id"),
    "environmentrestore": (
        "ix_environmentrestore_environment_backup_id",
        "environment_backup_id",
    ),
    "backup": ("ix_backup_environment_backup_id", "environment_backup_id"),
    "restore": ("ix_restore_environment_restore_id", "environment_restore_id"),
}


@pytest.fixture(params=["postgresql", "sqlite"])
def database_url(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    if request.param == "postgresql":
        url = request.getfixturevalue("postgres_url")
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'environment_backup.db'}"
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
    for table, (name, column) in INDEXES.items():
        assert indexes[table][name] == [column]

    command.downgrade(alembic_config, PREVIOUS_REVISION)

    indexes = _indexes(database_url)
    for table, (name, _) in INDEXES.items():
        assert name not in indexes[table]


def test_the_model_declares_the_indexes_the_revision_creates() -> None:
    for table, (name, _) in INDEXES.items():
        model_indexes = {
            index.name for index in SQLModel.metadata.tables[table].indexes
        }
        assert name in model_indexes
