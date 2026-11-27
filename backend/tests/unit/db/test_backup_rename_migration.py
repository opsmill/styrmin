"""Round trip of the revision that lets backups be renamed and described (#39)."""

import asyncio
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from styrmin_backend.cli.db import _get_alembic_config
from styrmin_backend.db import utils as db_utils

REVISION = "a2a102e37495"
PREVIOUS_REVISION = "859c9d31dc11"
INDEX = "ix_backup_instance_id_name"

BACKUP = sa.table(
    "backup",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("status", sa.String()),
    sa.column("instance_id", sa.Uuid()),
    sa.column("metadata", sa.JSON()),
)
METADATA = sa.select(BACKUP.c.id, BACKUP.c.metadata)

INSTANCE_A, INSTANCE_B = uuid.uuid4(), uuid.uuid4()
CUSTOM, DEFAULT = uuid.uuid4(), uuid.uuid4()


@pytest.fixture(params=["postgresql", "sqlite"])
def database_url(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    if request.param == "postgresql":
        url = request.getfixturevalue("postgres_url")
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'backup_rename.db'}"
    # ``migrations/env.py`` resolves the URL through this function on each command.
    monkeypatch.setattr(db_utils, "get_database_url", lambda: url)
    return url


def _run(url: str, statements: list[sa.Executable]) -> list[list[sa.Row]]:
    # The rows reference instances this test does not create.
    if sa.make_url(url).get_backend_name() == "postgresql":
        statements = [sa.text("SET session_replication_role = replica"), *statements]

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


def _backup(
    backup_id: uuid.UUID, name: str, instance_id: uuid.UUID, metadata=None
) -> sa.Executable:
    return sa.insert(BACKUP).values(
        id=backup_id,
        name=name,
        status=sa.literal_column("'COMPLETED'"),
        instance_id=instance_id,
        metadata=metadata,
    )


def _metadata(url: str) -> dict[uuid.UUID, dict | None]:
    return dict(_run(url, [METADATA])[-1])


@pytest.fixture
def upgraded(database_url: str):
    alembic_config = _get_alembic_config()
    command.upgrade(alembic_config, PREVIOUS_REVISION)
    _run(
        database_url,
        [
            _backup(CUSTOM, "before-upgrade", INSTANCE_A, {"velero_phase": "Done"}),
            _backup(DEFAULT, f"styrmin-{DEFAULT}", INSTANCE_A),
        ],
    )
    command.upgrade(alembic_config, REVISION)
    return database_url, alembic_config


def test_upgrade_stores_the_velero_name_only_for_custom_names(upgraded) -> None:
    url, _ = upgraded
    metadata = _metadata(url)
    assert metadata[CUSTOM] == {
        "velero_phase": "Done",
        "velero_backup_name": "before-upgrade",
    }
    assert metadata[DEFAULT] is None


def test_two_backups_of_one_instance_cannot_share_a_name(upgraded) -> None:
    url, _ = upgraded
    with pytest.raises(IntegrityError):
        _run(url, [_backup(uuid.uuid4(), "before-upgrade", INSTANCE_A)])


def test_two_backups_of_different_instances_can_share_a_name(upgraded) -> None:
    url, _ = upgraded
    _run(url, [_backup(uuid.uuid4(), "before-upgrade", INSTANCE_B)])


def test_downgrade_restores_global_uniqueness(upgraded) -> None:
    url, alembic_config = upgraded
    command.downgrade(alembic_config, PREVIOUS_REVISION)

    assert _metadata(url) == {CUSTOM: {"velero_phase": "Done"}, DEFAULT: None}
    with pytest.raises(IntegrityError):
        _run(url, [_backup(uuid.uuid4(), "before-upgrade", INSTANCE_B)])


def test_downgrade_refuses_when_names_are_duplicated(upgraded) -> None:
    url, alembic_config = upgraded
    _run(url, [_backup(uuid.uuid4(), "before-upgrade", INSTANCE_B)])

    with pytest.raises(RuntimeError, match="before-upgrade"):
        command.downgrade(alembic_config, PREVIOUS_REVISION)


def test_the_model_declares_the_index_the_revision_creates() -> None:
    index = next(
        index
        for index in SQLModel.metadata.tables["backup"].indexes
        if index.name == INDEX
    )
    assert index.unique
    assert [column.name for column in index.columns] == ["instance_id", "name"]
