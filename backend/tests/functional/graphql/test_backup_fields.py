"""Propagation tests for the retention fields on the ``Backup`` GraphQL type.

``Backup.ttl`` and ``Backup.expiresAt`` are resolver-backed projections of the
``metadata`` JSON column (keys ``ttl`` / ``expires_at``), not stored columns.
Every assertion here therefore reads back through a **second session bound to
the same engine** — a fresh unit of work with its own identity map — so the
values must have survived a real DB round-trip. Asserting against the seeding
session would pass even if the JSON payload never reached the database, which
is exactly the in-place-mutation failure mode this suite has to catch
(spec 016 critique E4 / M2).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Backup, BackupStatus
from styrmin_backend.db.utils import get_session
from styrmin_backend.server.app import app

from .conftest import gql
from .seeds import seed_application_instance

EXPIRES_AT_ISO = "2026-11-01T12:04:06+00:00"


@pytest.fixture(name="fresh_client")
async def fresh_client_fixture(session: AsyncSession, admin_token: str):
    """Authenticated ASGI client whose resolvers run in a *fresh* session.

    The seeding session and this client's session are two distinct units of
    work over the same in-memory engine, so anything the client reads had to
    be flushed and committed to the database first.
    """
    bind = session.get_bind()
    engine = bind if isinstance(bind, AsyncEngine) else AsyncEngine(bind)
    assert isinstance(engine.sync_engine, Engine)

    async with AsyncSession(engine, expire_on_commit=False) as fresh_session:

        async def get_session_override():
            yield fresh_session

        app.dependency_overrides[get_session] = get_session_override
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {admin_token}"},
        ) as client:
            yield client
        app.dependency_overrides.clear()


async def seed_backup(
    session: AsyncSession,
    *,
    metadata: dict | None,
    status: BackupStatus = BackupStatus.COMPLETED,
    name: str = "backup-ttl-seed",
) -> Backup:
    instance = await seed_application_instance(session)
    backup = Backup(
        name=name,
        status=status,
        instance_id=instance.id,
        metadata_=metadata,
    )
    session.add(backup)
    await session.commit()
    return backup


@pytest.mark.asyncio
async def test_backup_projects_ttl_and_expires_at_from_metadata(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """A recorded TTL + expiration project through GraphQL after a DB round-trip."""
    backup = await seed_backup(
        session,
        metadata={
            "ttl": "2160h",
            "ttl_source": "environment",
            "expires_at": EXPIRES_AT_ISO,
        },
    )

    data = await gql(fresh_client, "get_backup_ttl", {"backupId": str(backup.id)})
    row = data["backup"]

    assert row["ttl"] == "2160h"
    assert datetime.fromisoformat(row["expiresAt"]) == datetime(
        2026, 11, 1, 12, 4, 6, tzinfo=UTC
    )


@pytest.mark.asyncio
async def test_backup_without_metadata_reports_both_fields_null(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """A pre-existing row (``metadata`` NULL) degrades to null on both fields."""
    backup = await seed_backup(session, metadata=None, name="backup-no-metadata")

    data = await gql(fresh_client, "get_backup_ttl", {"backupId": str(backup.id)})
    row = data["backup"]

    assert row["ttl"] is None
    assert row["expiresAt"] is None


@pytest.mark.asyncio
async def test_failed_backup_reports_ttl_without_expires_at(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """Failed backups never receive a Velero expiration — TTL still projects."""
    backup = await seed_backup(
        session,
        metadata={"ttl": "720h", "ttl_source": "default"},
        status=BackupStatus.FAILED,
        name="backup-failed",
    )

    data = await gql(fresh_client, "get_backup_ttl", {"backupId": str(backup.id)})
    row = data["backup"]

    assert row["ttl"] == "720h"
    assert row["expiresAt"] is None
