"""Service-layer tests for git-driver reload identity (spec 013 / US2).

These tests exercise :func:`load_application_driver_from_git_repository`
end-to-end against a real (in-memory SQLite) ``SqlModelUnitOfWork``,
substituting only the git provider with a fake that yields a pre-built
driver directory and reports a configurable HEAD commit SHA. That keeps
the test offline (no network clone, no dulwich, no temp git repo) while
still exercising every layer below the provider: loader, application
service, ``get_by_identity`` lookup, row creation, and the cascade
kwargs introduced in C8.

Coverage:

- ``test_git_load_records_resolved_commit_sha`` — a single git load
  records the provider-reported SHA on the row and leaves ``content_hash``
  null (T027).
- ``test_git_load_same_commit_is_noop`` — two loads with the same
  resolved SHA yield exactly one row (T028).
- ``test_git_load_new_commit_creates_new_row`` — two loads where the
  provider reports two distinct SHAs yield two rows with the same
  ``version`` and different ``source_commit_sha`` values (T029).
"""

from __future__ import annotations

import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import pytest
from fast_depends import dependency_provider
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import ApplicationDriverVersion
from styrmin_backend.services.applications import (
    load_application_driver_from_git_repository,
)
from styrmin_backend.services.driver.loaders import DriverLoader
from styrmin_backend.services.driver.models.structure.source import GitSource
from styrmin_backend.services.driver.provider import DriverProvider
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.manager import PrefectManager

_FIXTURE_DRIVER = (
    Path(__file__).resolve().parent / "fixtures" / "local_driver_directory"
)


class _FakeGitProvider(DriverProvider):
    """A ``GitDriverProvider`` stand-in for unit tests.

    Mirrors the real provider's surface — ``get_source()``, ``provide()``
    yielding a directory, ``get_resolved_commit_sha()`` returning the
    last-resolved SHA — so the loader's duck-typed accessor lookup
    treats it the same as the real implementation. The SHA can be
    reconfigured between calls to ``provide()`` so a single fixture
    can stand in for "two clones of the same branch at different
    commits".
    """

    def __init__(self, *, driver_dir: Path, commit_sha: str) -> None:
        self.source = GitSource(
            repository="https://example.com/fake.git",
            branch="main",
            token="",
        )
        self._driver_dir = driver_dir
        self._commit_sha = commit_sha

    def get_source(self) -> GitSource:
        return self.source

    def get_resolved_commit_sha(self) -> str | None:
        return self._commit_sha

    def set_commit_sha(self, sha: str) -> None:
        self._commit_sha = sha

    @contextmanager
    def provide(self) -> Generator[Path, None, None]:
        yield self._driver_dir


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

    Git-sourced loads register tokens and user-action workflows via the
    Prefect manager; we stub it with an async-friendly mock so the
    service path runs without a real Prefect instance.
    """
    manager_mock = mocker.AsyncMock(spec=PrefectManager)

    def _get_fake_manager(catalogue=None, workflow_executor=None):  # noqa: ARG001
        return manager_mock

    dependency_provider.override(get_manager.__wrapped__, _get_fake_manager)
    yield manager_mock
    dependency_provider.clear()


@pytest.fixture
def driver_dir(tmp_path: Path) -> Path:
    """Copy the committed local-driver fixture to ``tmp_path``.

    The fixture is structurally a valid driver tree — the same one used
    by the local-load tests — which is all the loader needs to deserialise
    a ``DriverSpec``. The fact that it lives on the local filesystem
    rather than inside a real git clone is irrelevant to the assertions
    here, because the *provider* is what owns "where did these bytes
    come from" and we've replaced it with the fake.
    """
    dest = tmp_path / "driver"
    shutil.copytree(_FIXTURE_DRIVER, dest)
    return dest


@pytest.fixture
def patch_git_loader(monkeypatch, driver_dir: Path):
    """Replace :func:`get_git_driver_loader` so calls return a ``DriverLoader``
    wired to our fake provider.

    Yielding the underlying ``_FakeGitProvider`` lets a test reconfigure
    the reported commit SHA between successive load calls (used by the
    "new commit creates a new row" scenario).
    """
    fake_provider = _FakeGitProvider(driver_dir=driver_dir, commit_sha="a" * 40)

    def _fake_get_git_driver_loader(repository: str, branch: str, token: str):  # noqa: ARG001
        return DriverLoader(provider=fake_provider)

    # The function is imported into ``services.applications`` at module
    # load time, so patch *that* reference rather than the source module.
    monkeypatch.setattr(
        "styrmin_backend.services.applications.get_git_driver_loader",
        _fake_get_git_driver_loader,
    )
    return fake_provider


async def _all_rows(session: AsyncSession) -> list[ApplicationDriverVersion]:
    rows = (await session.exec(select(ApplicationDriverVersion))).all()
    return list(rows)


@pytest.mark.asyncio
async def test_git_load_records_resolved_commit_sha(
    db_session: AsyncSession,
    patch_git_loader: _FakeGitProvider,
    prefect_manager_mock,  # noqa: ARG001 — keeps the @inject hop quiet
):
    """A git load persists the provider-reported SHA on the row.

    Drives T027. Asserts: exactly one row, ``source_commit_sha`` equals
    the provider's resolved SHA, ``content_hash`` is None (git rows
    own the commit-SHA fingerprint dimension; the per-byte hash is
    redundant and intentionally not stored).
    """
    expected_sha = "a" * 40
    patch_git_loader.set_commit_sha(expected_sha)

    uow = SqlModelUnitOfWork(session=db_session)
    row = (
        await load_application_driver_from_git_repository(
            repository_url="https://example.com/fake.git",
            branch="main",
            uow=uow,
        )
    ).version

    assert row is not None
    assert row.source_type == "git"
    assert row.source_commit_sha == expected_sha
    assert row.content_hash is None

    rows = await _all_rows(db_session)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_git_load_same_commit_is_noop(
    db_session: AsyncSession,
    patch_git_loader: _FakeGitProvider,
    prefect_manager_mock,  # noqa: ARG001 — keeps the @inject hop quiet
):
    """Two loads at the same resolved SHA yield exactly one row.

    Drives T028. The second call must take the ``get_by_identity`` fast
    path and return the existing row instead of inserting a duplicate.
    """
    sha = "b" * 40
    patch_git_loader.set_commit_sha(sha)

    uow = SqlModelUnitOfWork(session=db_session)

    first = (
        await load_application_driver_from_git_repository(
            repository_url="https://example.com/fake.git",
            branch="main",
            uow=uow,
        )
    ).version
    second = (
        await load_application_driver_from_git_repository(
            repository_url="https://example.com/fake.git",
            branch="main",
            uow=uow,
        )
    ).version

    rows = await _all_rows(db_session)
    assert len(rows) == 1, (
        f"expected exactly one row after two same-SHA loads, found {len(rows)}: "
        f"{[(r.id, r.source_commit_sha) for r in rows]}"
    )
    assert second.id == first.id
    assert second.source_commit_sha == sha


@pytest.mark.asyncio
async def test_git_load_new_commit_creates_new_row(
    db_session: AsyncSession,
    patch_git_loader: _FakeGitProvider,
    prefect_manager_mock,  # noqa: ARG001 — keeps the @inject hop quiet
):
    """Reload after a new commit creates a second row.

    Drives T029. Provider returns SHA1 then SHA2 on two successive
    loads of the same ``repo@branch``; we expect two rows sharing the
    same ``version`` but carrying distinct ``source_commit_sha`` values,
    with the original row untouched.
    """
    sha1 = "c" * 40
    sha2 = "d" * 40

    patch_git_loader.set_commit_sha(sha1)
    uow = SqlModelUnitOfWork(session=db_session)
    first = (
        await load_application_driver_from_git_repository(
            repository_url="https://example.com/fake.git",
            branch="main",
            uow=uow,
        )
    ).version

    patch_git_loader.set_commit_sha(sha2)
    second = (
        await load_application_driver_from_git_repository(
            repository_url="https://example.com/fake.git",
            branch="main",
            uow=uow,
        )
    ).version

    rows = await _all_rows(db_session)
    assert len(rows) == 2, (
        f"expected exactly two rows after two distinct-SHA loads, found "
        f"{len(rows)}: {[(r.id, r.source_commit_sha) for r in rows]}"
    )
    # Original row preserved.
    assert any(r.id == first.id for r in rows)
    # New row is distinct, same version, different SHA.
    assert second.id != first.id
    assert second.version == first.version
    assert {r.source_commit_sha for r in rows} == {sha1, sha2}


@pytest.mark.asyncio
async def test_register_user_action_keyed_on_fingerprint_across_reloads(
    db_session: AsyncSession,
    patch_git_loader: _FakeGitProvider,
    prefect_manager_mock,
):
    """Spec 013 review FIX 2 — Prefect registration key includes fingerprint.

    Two loads of the same ``application@version`` but with distinct commit
    SHAs must produce distinct Prefect workflow registration keys, so that
    older deployments pinned to the older driver-version row keep
    resolving to their original workflow rather than getting overwritten
    by the newer load.

    The fingerprint is the first 7 characters of the row's
    ``source_commit_sha`` (git source) or ``content_hash`` (local source).
    The PrefectManager mock records each ``register_user_action`` call;
    we assert the ``fingerprint`` argument differs across the two loads.
    """
    sha1 = "a" * 40
    sha2 = "b" * 40

    patch_git_loader.set_commit_sha(sha1)
    uow = SqlModelUnitOfWork(session=db_session)
    await load_application_driver_from_git_repository(
        repository_url="https://example.com/fake.git",
        branch="main",
        uow=uow,
    )

    patch_git_loader.set_commit_sha(sha2)
    await load_application_driver_from_git_repository(
        repository_url="https://example.com/fake.git",
        branch="main",
        uow=uow,
    )

    # The fixture driver declares two actions, so each load triggers
    # two ``register_user_action`` calls. Across two loads we expect
    # four calls in total: two with fingerprint sha1[:7] and two with
    # fingerprint sha2[:7].
    register_calls = prefect_manager_mock.register_user_action.await_args_list
    assert len(register_calls) == 4, (
        f"expected 4 register_user_action calls across two loads, "
        f"got {len(register_calls)}"
    )

    fingerprints = [call.kwargs["fingerprint"] for call in register_calls]
    assert all(f is not None for f in fingerprints), (
        f"all registrations must carry a fingerprint, got {fingerprints}"
    )
    # First two registrations are from the sha1 load, last two from sha2.
    assert fingerprints[0] == sha1[:7]
    assert fingerprints[1] == sha1[:7]
    assert fingerprints[2] == sha2[:7]
    assert fingerprints[3] == sha2[:7]
    # The two loads use different keys, so they do NOT collide.
    assert {fingerprints[0], fingerprints[2]} == {sha1[:7], sha2[:7]}
