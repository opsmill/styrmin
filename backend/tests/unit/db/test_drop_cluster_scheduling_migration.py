"""Upgrade of the revision that drops scheduling from stored cluster configs (#482)."""

import asyncio
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from styrmin_backend.cli.db import _get_alembic_config
from styrmin_backend.db import utils as db_utils

REVISION = "eac41bb71a65"
PREVIOUS_REVISION = "c4d1e8a2b7f3"

CLUSTER = sa.table(
    "cluster",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
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

TOLERATION = {"tolerations": [{"key": "dedicated", "operator": "Exists"}]}
CLUSTER_ID, PLAIN_CLUSTER_ID = uuid.uuid4(), uuid.uuid4()
INSTANCE_ID, CONTEXTLESS_INSTANCE_ID = uuid.uuid4(), uuid.uuid4()


@pytest.fixture(params=["postgresql", "sqlite"])
def database_url(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    if request.param == "postgresql":
        url = request.getfixturevalue("postgres_url")
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'cluster_scheduling.db'}"
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


def _instance(instance_id: uuid.UUID, context: dict | None) -> sa.Executable:
    return sa.insert(INSTANCE).values(
        id=instance_id,
        name=f"app-{instance_id.hex[:6]}",
        application_version="1.0.0",
        status=sa.literal_column("'PENDING'"),
        deployment_id=uuid.uuid4(),
        application_driver_version_id=uuid.uuid4(),
        sequence=1,
        context=context,
    )


def test_upgrade_removes_scheduling_from_cluster_configs_only(
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
                name="tolerating",
                config={"ingress_class": "traefik", "scheduling": TOLERATION},
            ),
            sa.insert(CLUSTER).values(
                id=PLAIN_CLUSTER_ID, name="plain", config={"ingress_class": "nginx"}
            ),
            _instance(
                INSTANCE_ID,
                {
                    "cluster": {"config": {"scheduling": TOLERATION}},
                    "environment": {
                        "name": "env",
                        "config": {"scheduling": TOLERATION},
                    },
                    "deployment": {"config": {"scheduling": TOLERATION}},
                    "instance": {
                        "namespace": "ns",
                        "config": {"scheduling": TOLERATION},
                    },
                },
            ),
            _instance(CONTEXTLESS_INSTANCE_ID, None),
        ],
    )

    command.upgrade(alembic_config, REVISION)

    clusters, instances = _run(
        database_url,
        [
            sa.select(CLUSTER.c.id, CLUSTER.c.config),
            sa.select(INSTANCE.c.id, INSTANCE.c.context),
        ],
    )
    assert dict(clusters) == {
        CLUSTER_ID: {"ingress_class": "traefik"},
        PLAIN_CLUSTER_ID: {"ingress_class": "nginx"},
    }
    assert dict(instances) == {
        INSTANCE_ID: {
            "cluster": {"config": {}},
            "environment": {"name": "env", "config": {"scheduling": TOLERATION}},
            "deployment": {"config": {"scheduling": TOLERATION}},
            "instance": {"namespace": "ns", "config": {"scheduling": TOLERATION}},
        },
        CONTEXTLESS_INSTANCE_ID: None,
    }
