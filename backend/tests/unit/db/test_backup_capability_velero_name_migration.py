"""Upgrade of the revision that names the Velero object in the backup capability (#509)."""

import asyncio
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from styrmin_backend.cli.db import _get_alembic_config
from styrmin_backend.db import utils as db_utils

REVISION = "859c9d31dc11"
PREVIOUS_REVISION = "eac41bb71a65"

CLUSTER = sa.table(
    "cluster",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("config", sa.JSON()),
)
LOCATION = sa.table(
    "backupstoragelocation",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("endpoint", sa.String()),
    sa.column("bucket", sa.String()),
    sa.column("region", sa.String()),
    sa.column("access_key_id", sa.String()),
    sa.column("secret_access_key", sa.String()),
)
ENVIRONMENT = sa.table(
    "environment",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("config", sa.JSON()),
    sa.column("capabilities", sa.JSON()),
    sa.column("cluster_id", sa.Uuid()),
    sa.column("backup_storage_location_id", sa.Uuid()),
)
INGRESS = {"external": {"ingress_class": "traefik", "fqdn_suffix": "apps.example.com"}}

CLUSTER_ID, LOCATION_ID = uuid.uuid4(), uuid.uuid4()
BACKED_UP_ID, PLAIN_ID = uuid.uuid4(), uuid.uuid4()


@pytest.fixture(params=["postgresql", "sqlite"])
def database_url(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    if request.param == "postgresql":
        url = request.getfixturevalue("postgres_url")
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'backup_capability.db'}"
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


def _capabilities(url: str) -> dict[uuid.UUID, dict | None]:
    [rows] = _run(url, [sa.select(ENVIRONMENT.c.id, ENVIRONMENT.c.capabilities)])
    return {row.id: row.capabilities for row in rows}


def test_upgrade_sets_velero_object_name_and_downgrade_restores_location_name(
    database_url: str,
) -> None:
    alembic_config = _get_alembic_config()
    command.upgrade(alembic_config, PREVIOUS_REVISION)
    _run(
        database_url,
        [
            sa.insert(CLUSTER).values(id=CLUSTER_ID, name="default", config={}),
            sa.insert(LOCATION).values(
                id=LOCATION_ID,
                name="primary",
                endpoint="https://s3.example.com",
                bucket="backups",
                region="us-east-1",
                access_key_id="key",
                secret_access_key="secret",
            ),
            sa.insert(ENVIRONMENT).values(
                id=BACKED_UP_ID,
                name="backed-up",
                config={},
                capabilities={
                    "backup": {"velero": {"storage_location": "primary"}},
                    "ingress": INGRESS,
                },
                cluster_id=CLUSTER_ID,
                backup_storage_location_id=LOCATION_ID,
            ),
            sa.insert(ENVIRONMENT).values(
                id=PLAIN_ID,
                name="plain",
                config={},
                capabilities={"ingress": INGRESS},
                cluster_id=CLUSTER_ID,
                backup_storage_location_id=None,
            ),
        ],
    )

    command.upgrade(alembic_config, REVISION)

    assert _capabilities(database_url) == {
        BACKED_UP_ID: {
            "backup": {"velero": {"storage_location": f"styrmin-bsl-{LOCATION_ID}"}},
            "ingress": INGRESS,
        },
        PLAIN_ID: {"ingress": INGRESS},
    }

    command.downgrade(alembic_config, PREVIOUS_REVISION)

    assert _capabilities(database_url)[BACKED_UP_ID] == {
        "backup": {"velero": {"storage_location": "primary"}},
        "ingress": INGRESS,
    }
