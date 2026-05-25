"""Service-layer idempotency tests for local-driver reload (spec 013 / US1).

These tests exercise :func:`load_application_driver_from_local_directory`
end-to-end against a real (in-memory SQLite) ``SqlModelUnitOfWork`` so the
``get_by_identity`` lookup, the row-creation path, and the cascade kwargs all
fire together — the fake repository covered the same surface in isolation
but missed the SQL flush ordering, the auto-fingerprint column, and the
component-configs save side-effect.

Coverage:

- ``test_local_load_same_content_is_noop`` — two loads with identical bytes
  produce exactly one row (T021).
- ``test_local_load_new_content_creates_new_row_without_deleting_old`` — an
  edit to the values template surfaces a second row with the same
  ``version`` and a distinct ``content_hash``; the original row is NOT
  deleted (T022, the regression-guard for the cascade-crash that drove
  spec 013).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fast_depends import dependency_provider
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import ApplicationDriverVersion
from styrmin_backend.services.applications import (
    load_application_driver_from_local_directory,
)
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.manager import PrefectManager

# The committed driver fixture used by other unit tests; copying it into
# ``tmp_path`` keeps the test self-contained (mutations don't leak back
# to the source tree).
_FIXTURE_DRIVER = (
    Path(__file__).resolve().parents[1]
    / "services"
    / "driver"
    / "fixtures"
    / "local_driver_directory"
)


@pytest.fixture
async def db_session():
    """In-memory SQLite session with StaticPool (single connection)."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


@pytest.fixture
def prefect_manager_mock(mocker):
    """Override the Prefect manager dependency for the duration of the test.

    Local-sourced loads never hit Prefect, but the ``@inject`` decorator
    still resolves the dependency, so we wire a no-op mock to keep that
    path quiet (matches the convention in ``backend/tests/unit/services/
    conftest.py``).
    """
    manager_mock = mocker.Mock(spec=PrefectManager)

    def _get_fake_manager(catalogue=None, workflow_executor=None):  # noqa: ARG001
        return manager_mock

    dependency_provider.override(get_manager.__wrapped__, _get_fake_manager)
    yield manager_mock
    dependency_provider.clear()


@pytest.fixture
def driver_dir(tmp_path: Path) -> Path:
    """Copy the committed local-driver fixture to ``tmp_path``.

    Tests may mutate files (e.g. append a comment to the values template)
    without contaminating the source tree.
    """
    dest = tmp_path / "driver"
    shutil.copytree(_FIXTURE_DRIVER, dest)
    return dest


async def _row_count(session: AsyncSession) -> int:
    rows = (await session.exec(select(ApplicationDriverVersion))).all()
    return len(rows)


async def _all_rows(session: AsyncSession) -> list[ApplicationDriverVersion]:
    rows = (await session.exec(select(ApplicationDriverVersion))).all()
    return list(rows)


@pytest.mark.asyncio
async def test_local_load_same_content_is_noop(
    db_session: AsyncSession,
    driver_dir: Path,
    prefect_manager_mock,  # noqa: ARG001 — keeps the @inject hop quiet
):
    """Two identical loads of the same on-disk driver yield exactly one row.

    Drives T021. The second load takes the ``get_by_identity`` fast path
    inside ``load_application_driver_from_object`` and returns the existing
    row instead of inserting a duplicate.
    """
    uow = SqlModelUnitOfWork(session=db_session)

    first = await load_application_driver_from_local_directory(
        path=str(driver_dir), uow=uow
    )
    assert first is not None
    assert first.content_hash is not None and len(first.content_hash) == 64
    assert await _row_count(db_session) == 1

    second = await load_application_driver_from_local_directory(
        path=str(driver_dir), uow=uow
    )
    assert await _row_count(db_session) == 1
    # Same row returned (idempotent on identity tuple).
    assert second.id == first.id
    assert second.content_hash == first.content_hash


@pytest.mark.asyncio
async def test_local_load_new_content_creates_new_row_without_deleting_old(
    db_session: AsyncSession,
    driver_dir: Path,
    prefect_manager_mock,  # noqa: ARG001 — keeps the @inject hop quiet
):
    """Edit the values template, reload → 2 rows with distinct fingerprints.

    Drives T022 and is the headline regression guard for spec 013: the
    *previous* behaviour deleted the existing row before creating the new
    one, which crashed because the dependent ``Action`` / ``ComponentConfig``
    rows had no cascade. The new behaviour accumulates rows (one per
    fingerprint) and leaves the historical row untouched so the audit trail
    and any in-flight deployments stay reproducible.
    """
    uow = SqlModelUnitOfWork(session=db_session)

    first = await load_application_driver_from_local_directory(
        path=str(driver_dir), uow=uow
    )
    assert await _row_count(db_session) == 1
    first_hash = first.content_hash
    first_id = first.id
    first_version = first.version
    assert first_hash is not None

    # Mutate the values template on disk. A single trailing-comment append
    # is enough: ``compute_driver_content_hash`` is byte-exact, no
    # whitespace/comment stripping.
    values_template = driver_dir / "values.j2.yml"
    values_template.write_bytes(values_template.read_bytes() + b"\n# touched\n")

    second = await load_application_driver_from_local_directory(
        path=str(driver_dir), uow=uow
    )

    rows = await _all_rows(db_session)
    assert len(rows) == 2, (
        f"expected exactly two rows after a content edit, found {len(rows)}: "
        f"{[(r.id, r.content_hash) for r in rows]}"
    )
    # The original row is still present — no delete branch.
    assert any(r.id == first_id for r in rows)
    # The new row carries a distinct fingerprint but the same ``version``.
    assert second.id != first_id
    assert second.content_hash != first_hash
    assert second.version == first_version
