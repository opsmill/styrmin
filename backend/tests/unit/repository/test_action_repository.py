"""Unit tests for ``SQLModelActionRepository.list_by_driver_version`` (spec 029, T007).

Hook resolution reads the declared actions of a driver version with this
method, to know which hook and mode pairs must have a registered flow.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    Action,
    ApplicationDriver,
    ApplicationDriverVersion,
    HelmChart,
    HelmRepository,
)
from styrmin_backend.repository.action import SQLModelActionRepository


async def _seed_driver_version(
    session: AsyncSession, application_driver: ApplicationDriver, version: str
) -> ApplicationDriverVersion:
    helm_repository = HelmRepository(
        id=uuid4(), url=f"https://charts.example.com/{version}"
    )
    helm_chart = HelmChart(
        id=uuid4(),
        name="test-chart",
        version=version,
        values_template="",
        repository_id=helm_repository.id,
    )
    driver_version = ApplicationDriverVersion(
        id=uuid4(),
        application_driver_id=application_driver.id,
        version=version,
        application_supported_versions=">=1.0.0",
        source_type="local",
        source_repository="/styrmin/drivers/test-driver",
        source_path="/styrmin/drivers/test-driver",
        content_hash=version * 64,
        helm_chart_id=helm_chart.id,
    )
    session.add_all([helm_repository, helm_chart, driver_version])
    await session.flush()
    return driver_version


def _action(
    driver_version: ApplicationDriverVersion, name: str, hook: str, mode: str
) -> Action:
    return Action(
        name=name,
        description=name,
        location=f"actions.py::{name}",
        hook=hook,
        mode=mode,
        application_driver_version_id=driver_version.id,
    )


@pytest.mark.asyncio
async def test_list_by_driver_version_returns_the_actions_of_the_version_by_name(
    session: AsyncSession,
) -> None:
    repository = SQLModelActionRepository(session)
    application_driver = ApplicationDriver(id=uuid4(), name="test-driver")
    session.add(application_driver)
    first = await _seed_driver_version(session, application_driver, "1")
    second = await _seed_driver_version(session, application_driver, "2")
    for action in (
        _action(first, "upgrade", "upgrade", "core"),
        _action(first, "post_setup", "setup", "post"),
        _action(second, "migrate", "upgrade", "core"),
        _action(first, "pre_setup", "setup", "pre"),
    ):
        await repository.create(action)

    actions = await repository.list_by_driver_version(first.id)

    assert [action.name for action in actions] == ["post_setup", "pre_setup", "upgrade"]
    assert [(action.hook, action.mode) for action in actions] == [
        ("setup", "post"),
        ("setup", "pre"),
        ("upgrade", "core"),
    ]
    assert [
        action.name for action in await repository.list_by_driver_version(second.id)
    ] == ["migrate"]


@pytest.mark.asyncio
async def test_list_by_driver_version_returns_nothing_for_a_version_without_actions(
    session: AsyncSession,
) -> None:
    repository = SQLModelActionRepository(session)
    application_driver = ApplicationDriver(id=uuid4(), name="test-driver")
    session.add(application_driver)
    with_actions = await _seed_driver_version(session, application_driver, "1")
    without_actions = await _seed_driver_version(session, application_driver, "2")
    await repository.create(_action(with_actions, "upgrade", "upgrade", "core"))

    assert await repository.list_by_driver_version(without_actions.id) == []
