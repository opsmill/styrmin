"""Revision that adds the driver version info columns (spec 020)."""

import asyncio
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

from styrmin_backend.cli.db import _get_alembic_config
from styrmin_backend.db import utils as db_utils

REVISION = "c62923f4dc7e"
PREVIOUS_REVISION = "3b926acd0791"
INFO_COLUMNS = {"icon", "description", "links"}

HELM_REPOSITORY = sa.table(
    "helmrepository", sa.column("id", sa.Uuid()), sa.column("url", sa.String())
)
HELM_CHART = sa.table(
    "helmchart",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("version", sa.String()),
    sa.column("values_template", sa.String()),
    sa.column("repository_id", sa.Uuid()),
)
APPLICATION_DRIVER = sa.table(
    "applicationdriver", sa.column("id", sa.Uuid()), sa.column("name", sa.String())
)
DRIVER_VERSION = sa.table(
    "applicationdriverversion",
    sa.column("id", sa.Uuid()),
    sa.column("application_driver_id", sa.Uuid()),
    sa.column("version", sa.String()),
    sa.column("application_supported_versions", sa.String()),
    sa.column("source_type", sa.String()),
    sa.column("source_repository", sa.String()),
    sa.column("helm_chart_id", sa.Uuid()),
)
DRIVER_VERSION_INFO = sa.table(
    "applicationdriverversion",
    sa.column("id", sa.Uuid()),
    sa.column("icon", sa.String()),
    sa.column("description", sa.String()),
    sa.column("links", sa.JSON()),
)

REPOSITORY_ID = uuid.uuid4()
CHART_ID = uuid.uuid4()
DRIVER_ID = uuid.uuid4()
VERSION_ID = uuid.uuid4()


@pytest.fixture(params=["postgresql", "sqlite"])
def database_url(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    if request.param == "postgresql":
        url = request.getfixturevalue("postgres_url")
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'driver_info.db'}"
    # ``migrations/env.py`` resolves the URL through this function on each command.
    monkeypatch.setattr(db_utils, "get_database_url", lambda: url)
    return url


def _run(url: str, statements: list[sa.Executable]) -> list[list[sa.Row]]:
    async def run() -> list[list[sa.Row]]:
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                results = []
                for statement in statements:
                    result = await connection.execute(statement)
                    results.append(list(result.all()) if result.returns_rows else [])
                return results
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _driver_version_columns(url: str) -> set[str]:
    async def read() -> set[str]:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                columns = await connection.run_sync(
                    lambda sync: sa.inspect(sync).get_columns(
                        "applicationdriverversion"
                    )
                )
                return {column["name"] for column in columns}
        finally:
            await engine.dispose()

    return asyncio.run(read())


def _applied_revisions(url: str) -> set[str]:
    [rows] = _run(url, [sa.text("SELECT version_num FROM alembic_version")])
    return {row.version_num for row in rows}


def test_revision_is_the_single_head_after_the_installation_revision() -> None:
    script = ScriptDirectory.from_config(_get_alembic_config())

    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PREVIOUS_REVISION


def test_upgrade_adds_null_info_columns_and_downgrade_drops_them(
    database_url: str,
) -> None:
    alembic_config = _get_alembic_config()
    command.upgrade(alembic_config, PREVIOUS_REVISION)
    assert _applied_revisions(database_url) == {PREVIOUS_REVISION}
    _run(
        database_url,
        [
            sa.insert(HELM_REPOSITORY).values(
                id=REPOSITORY_ID, url="oci://registry.example.com/charts"
            ),
            sa.insert(HELM_CHART).values(
                id=CHART_ID,
                name="app",
                version="1.0.0",
                values_template="",
                repository_id=REPOSITORY_ID,
            ),
            sa.insert(APPLICATION_DRIVER).values(id=DRIVER_ID, name="app"),
            sa.insert(DRIVER_VERSION).values(
                id=VERSION_ID,
                application_driver_id=DRIVER_ID,
                version="1.0",
                application_supported_versions=">=1.0",
                source_type="local",
                source_repository="/drivers/app",
                helm_chart_id=CHART_ID,
            ),
        ],
    )
    assert not INFO_COLUMNS & _driver_version_columns(database_url)

    command.upgrade(alembic_config, REVISION)

    assert _applied_revisions(database_url) == {REVISION}
    assert INFO_COLUMNS <= _driver_version_columns(database_url)
    [rows] = _run(
        database_url,
        [
            sa.select(
                DRIVER_VERSION_INFO.c.id,
                DRIVER_VERSION_INFO.c.icon,
                DRIVER_VERSION_INFO.c.description,
                DRIVER_VERSION_INFO.c.links,
            )
        ],
    )
    assert [tuple(row) for row in rows] == [(VERSION_ID, None, None, None)]

    command.downgrade(alembic_config, PREVIOUS_REVISION)

    assert _applied_revisions(database_url) == {PREVIOUS_REVISION}
    assert not INFO_COLUMNS & _driver_version_columns(database_url)
