"""Round trip of the add-steps revision (spec 019) on PostgreSQL and SQLite."""

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from styrmin_backend.cli.db import _get_alembic_config
from styrmin_backend.db import utils as db_utils

STEPS_REVISION = "e2f3a4b5c6d7"
PREVIOUS_REVISION = "d1e2f3a4b5c6"
STEP_ENUM_TYPES = {"stepstatus", "stepkind"}
TASK_STEP_COLUMNS = {"instance_id", "started_by_step_id"}


@dataclass(frozen=True)
class Schema:
    tables: set[str]
    task_columns: set[str]
    task_foreign_keys: set[str]
    enum_types: set[str]


@pytest.fixture(params=["postgresql", "sqlite"])
def database_url(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    if request.param == "postgresql":
        url = request.getfixturevalue("postgres_url")
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'steps.db'}"
    # ``migrations/env.py`` resolves the URL through this function on each command.
    monkeypatch.setattr(db_utils, "get_database_url", lambda: url)
    return url


def _inspect(connection: sa.Connection) -> Schema:
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    enum_types: set[str] = set()
    if connection.dialect.name == "postgresql":
        rows = connection.execute(
            sa.text(
                "SELECT typname FROM pg_type WHERE typname IN ('stepstatus', 'stepkind')"
            )
        )
        enum_types = {row.typname for row in rows}
    return Schema(
        tables=tables,
        task_columns={column["name"] for column in inspector.get_columns("task")},
        task_foreign_keys={
            fk["name"] for fk in inspector.get_foreign_keys("task") if fk["name"]
        },
        enum_types=enum_types,
    )


def _read_schema(url: str) -> Schema:
    async def read() -> Schema:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(_inspect)
        finally:
            await engine.dispose()

    return asyncio.run(read())


def _assert_steps_schema_present(schema: Schema, dialect: str) -> None:
    assert "step" in schema.tables
    assert TASK_STEP_COLUMNS <= schema.task_columns
    assert {"task_instance_id_fkey", "task_started_by_step_id_fkey"} <= (
        schema.task_foreign_keys
    )
    if dialect == "postgresql":
        assert schema.enum_types == STEP_ENUM_TYPES


def _assert_steps_schema_absent(schema: Schema) -> None:
    assert "step" not in schema.tables
    assert not TASK_STEP_COLUMNS & schema.task_columns
    assert not schema.enum_types


def test_steps_revision_upgrades_downgrades_and_upgrades_again(
    database_url: str,
) -> None:
    dialect = sa.make_url(database_url).get_backend_name()
    alembic_config = _get_alembic_config()

    command.upgrade(alembic_config, "head")
    _assert_steps_schema_present(_read_schema(database_url), dialect)

    command.downgrade(alembic_config, PREVIOUS_REVISION)
    _assert_steps_schema_absent(_read_schema(database_url))

    command.upgrade(alembic_config, STEPS_REVISION)
    _assert_steps_schema_present(_read_schema(database_url), dialect)
