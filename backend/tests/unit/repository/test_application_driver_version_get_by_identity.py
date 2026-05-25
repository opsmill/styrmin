"""Unit tests for ``SQLModelApplicationDriverVersionRepository.get_by_identity``.

Spec 013 — Driver Reload Identity (Provenance Fingerprint).

Covers the widened identity-tuple lookup (T011) and the cascade-delete-orphan
behaviour for child ``Action`` and ``ComponentConfig`` rows added via the
``sa_relationship_kwargs={"cascade": "all, delete-orphan"}`` kwargs in C2.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    Action,
    ApplicationDriver,
    ApplicationDriverVersion,
    ComponentConfig,
    HelmChart,
    HelmRepository,
)
from styrmin_backend.repository.application_driver_version import (
    SQLModelApplicationDriverVersionRepository,
)


async def _seed_prerequisites(
    session: AsyncSession,
) -> tuple[ApplicationDriver, HelmChart]:
    """Seed a HelmRepository, HelmChart, and ApplicationDriver."""
    helm_repo = HelmRepository(id=uuid4(), url="https://charts.example.com")
    session.add(helm_repo)

    helm_chart = HelmChart(
        id=uuid4(),
        name="test-chart",
        version="0.1.0",
        values_template="",
        repository_id=helm_repo.id,
    )
    session.add(helm_chart)

    app_driver = ApplicationDriver(id=uuid4(), name="test-driver")
    session.add(app_driver)

    await session.flush()
    return app_driver, helm_chart


def _make_version(
    *,
    application_driver_id,
    helm_chart_id,
    version: str = "1.0.0",
    source_type: str = "local",
    source_repository: str = "/tmp/local-driver",
    source_branch: str | None = None,
    source_path: str | None = "drivers/app",
    content_hash: str | None = "a" * 64,
    source_commit_sha: str | None = None,
) -> ApplicationDriverVersion:
    return ApplicationDriverVersion(
        id=uuid4(),
        application_driver_id=application_driver_id,
        version=version,
        application_supported_versions=">=1.0.0",
        source_type=source_type,
        source_repository=source_repository,
        source_branch=source_branch,
        source_path=source_path,
        content_hash=content_hash,
        source_commit_sha=source_commit_sha,
        helm_chart_id=helm_chart_id,
    )


@pytest.mark.asyncio
async def test_get_by_identity_exact_match_returns_row(session: AsyncSession):
    """Exact identity-tuple match returns the seeded row."""
    repo = SQLModelApplicationDriverVersionRepository(session)
    app_driver, helm_chart = await _seed_prerequisites(session)

    seeded = await repo.create(
        _make_version(
            application_driver_id=app_driver.id,
            helm_chart_id=helm_chart.id,
            source_type="local",
            source_repository="/tmp/local-driver",
            source_branch=None,
            source_path="drivers/app",
            version="1.0.0",
            content_hash="a" * 64,
            source_commit_sha=None,
        )
    )

    found = await repo.get_by_identity(
        application_driver_id=app_driver.id,
        source_type="local",
        source_repository="/tmp/local-driver",
        source_branch=None,
        source_path="drivers/app",
        version="1.0.0",
        content_hash="a" * 64,
        source_commit_sha=None,
    )
    assert found is not None
    assert found.id == seeded.id


@pytest.mark.asyncio
async def test_get_by_identity_differing_fingerprint_returns_none(
    session: AsyncSession,
):
    """A row with content_hash='A' must not be returned for a lookup of 'B'."""
    repo = SQLModelApplicationDriverVersionRepository(session)
    app_driver, helm_chart = await _seed_prerequisites(session)

    await repo.create(
        _make_version(
            application_driver_id=app_driver.id,
            helm_chart_id=helm_chart.id,
            content_hash="a" * 64,
        )
    )

    found = await repo.get_by_identity(
        application_driver_id=app_driver.id,
        source_type="local",
        source_repository="/tmp/local-driver",
        source_branch=None,
        source_path="drivers/app",
        version="1.0.0",
        content_hash="b" * 64,
        source_commit_sha=None,
    )
    assert found is None


@pytest.mark.asyncio
async def test_get_by_identity_differing_branch_returns_none(session: AsyncSession):
    """Differing source_branch makes it a distinct identity."""
    repo = SQLModelApplicationDriverVersionRepository(session)
    app_driver, helm_chart = await _seed_prerequisites(session)

    await repo.create(
        _make_version(
            application_driver_id=app_driver.id,
            helm_chart_id=helm_chart.id,
            source_branch="main",
        )
    )

    found = await repo.get_by_identity(
        application_driver_id=app_driver.id,
        source_type="local",
        source_repository="/tmp/local-driver",
        source_branch="dev",
        source_path="drivers/app",
        version="1.0.0",
        content_hash="a" * 64,
        source_commit_sha=None,
    )
    assert found is None


@pytest.mark.asyncio
async def test_get_by_identity_differing_source_path_returns_none(
    session: AsyncSession,
):
    """Differing source_path makes it a distinct identity."""
    repo = SQLModelApplicationDriverVersionRepository(session)
    app_driver, helm_chart = await _seed_prerequisites(session)

    await repo.create(
        _make_version(
            application_driver_id=app_driver.id,
            helm_chart_id=helm_chart.id,
            source_path="drivers/app",
        )
    )

    found = await repo.get_by_identity(
        application_driver_id=app_driver.id,
        source_type="local",
        source_repository="/tmp/local-driver",
        source_branch=None,
        source_path="drivers/other",
        version="1.0.0",
        content_hash="a" * 64,
        source_commit_sha=None,
    )
    assert found is None


@pytest.mark.asyncio
async def test_get_by_identity_null_fingerprint_matches_null(session: AsyncSession):
    """A row with NULL content_hash matches a NULL lookup (IS NULL semantics)."""
    repo = SQLModelApplicationDriverVersionRepository(session)
    app_driver, helm_chart = await _seed_prerequisites(session)

    seeded = await repo.create(
        _make_version(
            application_driver_id=app_driver.id,
            helm_chart_id=helm_chart.id,
            content_hash=None,
            source_commit_sha=None,
        )
    )

    found = await repo.get_by_identity(
        application_driver_id=app_driver.id,
        source_type="local",
        source_repository="/tmp/local-driver",
        source_branch=None,
        source_path="drivers/app",
        version="1.0.0",
        content_hash=None,
        source_commit_sha=None,
    )
    assert found is not None
    assert found.id == seeded.id


@pytest.mark.asyncio
async def test_get_by_identity_git_source_found_by_commit_sha(
    session: AsyncSession,
):
    """A git-sourced row is found by its resolved source_commit_sha."""
    repo = SQLModelApplicationDriverVersionRepository(session)
    app_driver, helm_chart = await _seed_prerequisites(session)

    sha = "deadbeef" * 5  # 40-char hex
    seeded = await repo.create(
        _make_version(
            application_driver_id=app_driver.id,
            helm_chart_id=helm_chart.id,
            source_type="git",
            source_repository="https://example.com/driver.git",
            source_branch="main",
            source_path=None,
            content_hash=None,
            source_commit_sha=sha,
        )
    )

    found = await repo.get_by_identity(
        application_driver_id=app_driver.id,
        source_type="git",
        source_repository="https://example.com/driver.git",
        source_branch="main",
        source_path=None,
        version="1.0.0",
        content_hash=None,
        source_commit_sha=sha,
    )
    assert found is not None
    assert found.id == seeded.id


@pytest.mark.asyncio
async def test_delete_cascades_actions_and_component_configs(session: AsyncSession):
    """``repo.delete(version)`` removes child Action and ComponentConfig rows atomically."""
    repo = SQLModelApplicationDriverVersionRepository(session)
    app_driver, helm_chart = await _seed_prerequisites(session)

    version = await repo.create(
        _make_version(
            application_driver_id=app_driver.id,
            helm_chart_id=helm_chart.id,
        )
    )

    # Seed two Actions and two ComponentConfigs as children.
    for name in ("action-a", "action-b"):
        session.add(
            Action(
                id=uuid4(),
                name=name,
                description="",
                location="",
                application_driver_version_id=version.id,
            )
        )
    for name in ("cfg-a", "cfg-b"):
        session.add(
            ComponentConfig(
                id=uuid4(),
                name=name,
                config={},
                application_driver_version_id=version.id,
            )
        )
    await session.flush()

    # Sanity: children exist.
    actions_before = (
        await session.exec(
            select(Action).where(Action.application_driver_version_id == version.id)
        )
    ).all()
    configs_before = (
        await session.exec(
            select(ComponentConfig).where(
                ComponentConfig.application_driver_version_id == version.id
            )
        )
    ).all()
    assert len(actions_before) == 2
    assert len(configs_before) == 2

    # Re-fetch via the repo so relationships are loaded for cascade.
    parent = await repo.get(version.id)
    assert parent is not None
    await repo.delete(parent)
    await session.flush()

    # No IntegrityError; children are gone.
    actions_after = (
        await session.exec(
            select(Action).where(Action.application_driver_version_id == version.id)
        )
    ).all()
    configs_after = (
        await session.exec(
            select(ComponentConfig).where(
                ComponentConfig.application_driver_version_id == version.id
            )
        )
    ).all()
    assert actions_after == []
    assert configs_after == []
