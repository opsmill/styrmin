"""Upgrade of the revision that drops the empty cluster dedicated_ingress (#409)."""

import asyncio
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from styrmin_backend.cli.db import _get_alembic_config
from styrmin_backend.db import utils as db_utils

REVISION = "f3a4b5c6d7e8"
PREVIOUS_REVISION = "e2f3a4b5c6d7"

CLUSTER = sa.table(
    "cluster",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("config", sa.JSON()),
    sa.column("capabilities", sa.JSON()),
)
ENVIRONMENT = sa.table(
    "environment",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("config", sa.JSON()),
    sa.column("cluster_id", sa.Uuid()),
)
INGRESS_CAPABILITY = {
    "ingress": {
        "external": {"ingress_class": "traefik", "fqdn_suffix": "apps.example.com"}
    }
}

DEFAULT_ID = uuid.uuid4()
CLASSLESS_ID = uuid.uuid4()
CONFIGURED_ID = uuid.uuid4()
ENVIRONMENT_ID = uuid.uuid4()


@pytest.fixture(params=["postgresql", "sqlite"])
def database_url(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    if request.param == "postgresql":
        url = request.getfixturevalue("postgres_url")
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'ingress.db'}"
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


def test_upgrade_removes_empty_dedicated_ingress_from_clusters_only(
    database_url: str,
) -> None:
    alembic_config = _get_alembic_config()
    command.upgrade(alembic_config, PREVIOUS_REVISION)
    _run(
        database_url,
        [
            sa.insert(CLUSTER).values(
                id=DEFAULT_ID,
                name="default",
                config={
                    "ingress_class": "traefik",
                    "dedicated_ingress": {},
                    "fqdn_suffix": "apps.example.com",
                },
                capabilities=INGRESS_CAPABILITY,
            ),
            sa.insert(CLUSTER).values(
                id=CLASSLESS_ID,
                name="classless",
                config={"dedicated_ingress": {}, "fqdn_suffix": "apps.example.com"},
                capabilities=INGRESS_CAPABILITY,
            ),
            sa.insert(CLUSTER).values(
                id=CONFIGURED_ID,
                name="configured",
                config={"dedicated_ingress": {"service": {"type": "ClusterIP"}}},
                capabilities=None,
            ),
            sa.insert(ENVIRONMENT).values(
                id=ENVIRONMENT_ID,
                name="env",
                config={"dedicated_ingress": {}},
                cluster_id=DEFAULT_ID,
            ),
        ],
    )

    command.upgrade(alembic_config, REVISION)

    clusters, environments = _run(
        database_url,
        [
            sa.select(CLUSTER.c.id, CLUSTER.c.config, CLUSTER.c.capabilities),
            sa.select(ENVIRONMENT.c.config),
        ],
    )
    by_id = {row.id: row for row in clusters}
    assert by_id[DEFAULT_ID].config == {
        "ingress_class": "traefik",
        "fqdn_suffix": "apps.example.com",
    }
    assert by_id[DEFAULT_ID].capabilities == INGRESS_CAPABILITY
    assert by_id[CLASSLESS_ID].config == {"fqdn_suffix": "apps.example.com"}
    assert by_id[CLASSLESS_ID].capabilities is None
    assert by_id[CONFIGURED_ID].config == {
        "dedicated_ingress": {"service": {"type": "ClusterIP"}}
    }
    assert [row.config for row in environments] == [{"dedicated_ingress": {}}]
