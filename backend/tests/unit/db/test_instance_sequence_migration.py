"""Round trip of the revision that numbers each deployment's instances (#386)."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from styrmin_backend.cli.db import _get_alembic_config
from styrmin_backend.db import utils as db_utils

REVISION = "7af6824e820d"
PREVIOUS_REVISION = "c62923f4dc7e"
UNIQUE_SEQUENCE = "uq_applicationinstance_deployment_sequence"

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
)
INSTANCE = sa.table(
    "applicationinstance",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("application_version", sa.String()),
    sa.column("status", sa.String()),
    sa.column("deployment_id", sa.Uuid()),
    sa.column("application_driver_version_id", sa.Uuid()),
    sa.column("created_on", sa.DateTime(timezone=True)),
)
SEQUENCES = sa.select(
    sa.column("id", sa.Uuid()), sa.column("sequence", sa.Integer())
).select_from(sa.table("applicationinstance"))
COUNTERS = sa.select(
    sa.column("id", sa.Uuid()), sa.column("last_instance_sequence", sa.Integer())
).select_from(sa.table("deployment"))

T0 = datetime(2026, 10, 1, tzinfo=UTC)
WITH_FOUR, WITH_ONE, WITHOUT = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
# Two instances share a creation time; their ids order them.
TIE_LOW, TIE_HIGH = sorted([uuid.uuid4(), uuid.uuid4()])
FIRST, SECOND, ONLY = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


@pytest.fixture(params=["postgresql", "sqlite"])
def database_url(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    if request.param == "postgresql":
        url = request.getfixturevalue("postgres_url")
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'sequence.db'}"
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


def _inspect(url: str) -> tuple[set[str], set[str], dict[str, bool]]:
    def read(connection: sa.Connection) -> tuple[set[str], set[str], dict[str, bool]]:
        inspector = sa.inspect(connection)
        instance_columns = {
            column["name"]: column["nullable"]
            for column in inspector.get_columns("applicationinstance")
        }
        return (
            {column["name"] for column in inspector.get_columns("deployment")},
            {
                constraint["name"]
                for constraint in inspector.get_unique_constraints(
                    "applicationinstance"
                )
                if constraint["name"]
            },
            instance_columns,
        )

    async def run() -> tuple[set[str], set[str], dict[str, bool]]:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(read)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _deployment(deployment_id: uuid.UUID) -> sa.Executable:
    return sa.insert(DEPLOYMENT).values(
        id=deployment_id,
        name=f"deployment-{deployment_id.hex[:8]}",
        application_version="1.0.0",
        internal=False,
        status=sa.literal_column("'PENDING'"),
        application_driver_version_id=uuid.uuid4(),
        environment_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
    )


def _instance(
    instance_id: uuid.UUID, deployment_id: uuid.UUID, created_on: datetime
) -> sa.Executable:
    return sa.insert(INSTANCE).values(
        id=instance_id,
        name=f"instance-{instance_id.hex[:8]}",
        application_version="1.0.0",
        status=sa.literal_column("'PENDING'"),
        deployment_id=deployment_id,
        application_driver_version_id=uuid.uuid4(),
        created_on=created_on,
    )


def test_upgrade_numbers_existing_instances_and_downgrade_removes_the_columns(
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
            _deployment(WITH_FOUR),
            _deployment(WITH_ONE),
            _deployment(WITHOUT),
            _instance(SECOND, WITH_FOUR, T0 + timedelta(seconds=1)),
            _instance(TIE_HIGH, WITH_FOUR, T0 + timedelta(seconds=2)),
            _instance(FIRST, WITH_FOUR, T0),
            _instance(TIE_LOW, WITH_FOUR, T0 + timedelta(seconds=2)),
            _instance(ONLY, WITH_ONE, T0),
        ],
    )

    command.upgrade(alembic_config, REVISION)

    sequences, counters = _run(database_url, [SEQUENCES, COUNTERS])
    assert dict(sequences) == {FIRST: 1, SECOND: 2, TIE_LOW: 3, TIE_HIGH: 4, ONLY: 1}
    assert dict(counters) == {WITH_FOUR: 4, WITH_ONE: 1, WITHOUT: 0}
    deployment_columns, unique_constraints, instance_columns = _inspect(database_url)
    assert "last_instance_sequence" in deployment_columns
    assert UNIQUE_SEQUENCE in unique_constraints
    assert instance_columns["sequence"] is False

    command.downgrade(alembic_config, PREVIOUS_REVISION)

    deployment_columns, unique_constraints, instance_columns = _inspect(database_url)
    assert "last_instance_sequence" not in deployment_columns
    assert UNIQUE_SEQUENCE not in unique_constraints
    assert "sequence" not in instance_columns
