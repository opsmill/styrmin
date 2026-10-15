"""Upgrade of the revision that drops node_selector from stored configs (#472)."""

import asyncio
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from styrmin_backend.cli.db import _get_alembic_config
from styrmin_backend.db import utils as db_utils

REVISION = "c4d1e8a2b7f3"
PREVIOUS_REVISION = "7948e6057857"

CLUSTER = sa.table(
    "cluster",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("config", sa.JSON()),
)
DEPLOYMENT = sa.table(
    "deployment",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("application_version", sa.String()),
    sa.column("internal", sa.Boolean()),
    sa.column("status", sa.String()),
    sa.column("application_driver_version_id", sa.Uuid()),
    sa.column("environment_id", sa.Uuid()),
    sa.column("created_by_user_id", sa.Uuid()),
    sa.column("last_instance_sequence", sa.Integer()),
    sa.column("config", sa.JSON()),
)
INSTANCE = sa.table(
    "applicationinstance",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("application_version", sa.String()),
    sa.column("status", sa.String()),
    sa.column("deployment_id", sa.Uuid()),
    sa.column("application_driver_version_id", sa.Uuid()),
    sa.column("sequence", sa.Integer()),
    sa.column("context", sa.JSON()),
)
ENVIRONMENT_BACKUP = sa.table(
    "environmentbackup",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("environment_id", sa.Uuid()),
    sa.column("deployment_snapshots", sa.JSON()),
)

CLUSTER_ID, PLAIN_CLUSTER_ID = uuid.uuid4(), uuid.uuid4()
DEPLOYMENT_ID, INSTANCE_ID, BACKUP_ID = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


@pytest.fixture(params=["postgresql", "sqlite"])
def database_url(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    if request.param == "postgresql":
        url = request.getfixturevalue("postgres_url")
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'node_selector.db'}"
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


def test_upgrade_removes_node_selector_from_every_stored_config(
    database_url: str,
) -> None:
    dialect = sa.make_url(database_url).get_backend_name()
    alembic_config = _get_alembic_config()
    command.upgrade(alembic_config, PREVIOUS_REVISION)
    # The rows reference parents this test does not create.
    disable_foreign_keys = (
        [sa.text("SET session_replication_role = replica")]
        if dialect == "postgresql"
        else []
    )
    _run(
        database_url,
        [
            *disable_foreign_keys,
            sa.insert(CLUSTER).values(
                id=CLUSTER_ID,
                name="selected",
                config={"ingress_class": "traefik", "node_selector": "pool=apps"},
            ),
            sa.insert(CLUSTER).values(
                id=PLAIN_CLUSTER_ID, name="plain", config={"ingress_class": "nginx"}
            ),
            sa.insert(DEPLOYMENT).values(
                id=DEPLOYMENT_ID,
                name="app",
                application_version="1.0.0",
                internal=False,
                status=sa.literal_column("'PENDING'"),
                application_driver_version_id=uuid.uuid4(),
                environment_id=uuid.uuid4(),
                created_by_user_id=uuid.uuid4(),
                last_instance_sequence=1,
                config={"db_size": "small", "node_selector": "tier=batch"},
            ),
            sa.insert(INSTANCE).values(
                id=INSTANCE_ID,
                name="app-1",
                application_version="1.0.0",
                status=sa.literal_column("'PENDING'"),
                deployment_id=DEPLOYMENT_ID,
                application_driver_version_id=uuid.uuid4(),
                sequence=1,
                context={
                    "cluster": {"config": {"node_selector": "pool=apps"}},
                    "environment": {"name": "env", "config": {}},
                    "deployment": {"config": {"node_selector": "tier=batch"}},
                    "instance": {
                        "namespace": "ns",
                        "config": {"db_size": "small", "node_selector": "tier=batch"},
                    },
                },
            ),
            sa.insert(ENVIRONMENT_BACKUP).values(
                id=BACKUP_ID,
                name="snapshot",
                environment_id=uuid.uuid4(),
                deployment_snapshots=[
                    {"deployment_name": "app", "config": {"node_selector": "x=y"}},
                    {"deployment_name": "other", "config": None},
                ],
            ),
        ],
    )

    command.upgrade(alembic_config, REVISION)

    clusters, deployments, instances, backups = _run(
        database_url,
        [
            sa.select(CLUSTER.c.id, CLUSTER.c.config),
            sa.select(DEPLOYMENT.c.config),
            sa.select(INSTANCE.c.context),
            sa.select(ENVIRONMENT_BACKUP.c.deployment_snapshots),
        ],
    )
    assert dict(clusters) == {
        CLUSTER_ID: {"ingress_class": "traefik"},
        PLAIN_CLUSTER_ID: {"ingress_class": "nginx"},
    }
    assert [row.config for row in deployments] == [{"db_size": "small"}]
    assert [row.context for row in instances] == [
        {
            "cluster": {"config": {}},
            "environment": {"name": "env", "config": {}},
            "deployment": {"config": {}},
            "instance": {"namespace": "ns", "config": {"db_size": "small"}},
        }
    ]
    assert [row.deployment_snapshots for row in backups] == [
        [
            {"deployment_name": "app", "config": {}},
            {"deployment_name": "other", "config": None},
        ]
    ]
