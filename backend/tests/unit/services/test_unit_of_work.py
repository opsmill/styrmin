"""Tests for UnitOfWork session lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork
from tests.unit.services.fakes import (
    FakeActionRepository,
    FakeApplicationInstanceRepository,
    FakeApplicationRepository,
    FakeClusterRepository,
    FakeEnvironmentRepository,
    FakeHelmChartRepository,
    FakeHelmRepositoryRepository,
    FakeTaskRepository,
    FakeUnitOfWork,
)


def _make_fake_uow() -> FakeUnitOfWork:
    return FakeUnitOfWork(
        clusters=FakeClusterRepository(),
        environments=FakeEnvironmentRepository(),
        helm_repositories=FakeHelmRepositoryRepository(),
        helm_charts=FakeHelmChartRepository(),
        application_driver_versions=FakeApplicationRepository(),
        instances=FakeApplicationInstanceRepository(),
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
    )


class TestSqlModelUnitOfWorkSessionClose:
    async def test_session_closed_on_normal_exit(self) -> None:
        session = MagicMock()
        session.close = AsyncMock()
        session.rollback = AsyncMock()

        uow = SqlModelUnitOfWork(session=session)
        async with uow:
            pass

        session.close.assert_awaited_once()

    async def test_session_closed_on_exception(self) -> None:
        session = MagicMock()
        session.close = AsyncMock()
        session.rollback = AsyncMock()

        uow = SqlModelUnitOfWork(session=session)
        with pytest.raises(RuntimeError):
            async with uow:
                raise RuntimeError("simulated failure")

        session.rollback.assert_awaited_once()
        session.close.assert_awaited_once()


class TestFakeUnitOfWorkSessionClose:
    async def test_session_closed_on_exit(self) -> None:
        uow = _make_fake_uow()
        assert uow.session.closed is False

        async with uow:
            pass

        assert uow.session.closed is True

    async def test_session_closed_on_exception(self) -> None:
        uow = _make_fake_uow()

        with pytest.raises(ValueError):
            async with uow:
                raise ValueError("test error")

        assert uow.session.closed is True
