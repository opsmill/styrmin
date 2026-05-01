"""Shared fixtures for GraphQL ↔ DB propagation tests.

Re-exports the in-memory SQLite ``session`` and ASGI ``client`` fixtures from the
existing functional test module so propagation tests live in a dedicated
package without re-implementing the DB plumbing. Adds a ``prefect_manager_mock``
fixture that overrides ``get_manager`` via ``fast_depends`` so propagation tests
that exercise mutations dispatching Prefect workflows can run without touching
the real Prefect runtime.

See specs/007-graphql-propagation-tests/contracts/propagation-test-contract.md.
"""

from __future__ import annotations

import pytest
from fast_depends import dependency_provider
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.utils import get_session
from styrmin_backend.server.app import app
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.manager import PrefectManager


@pytest.fixture(name="session")
async def session_fixture():
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


@pytest.fixture(name="client")
async def graphql_fixture(session: AsyncSession):
    async def get_session_override():
        yield session

    app.dependency_overrides[get_session] = get_session_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def prefect_manager_mock(mocker):
    """Replace the Prefect manager dependency with a Mock(spec=PrefectManager).

    Mirrors the established pattern in
    ``backend/tests/unit/services/conftest.py``. Yielded mock can be used to
    assert ``run_action`` calls or to inspect dispatched parameters.
    """

    manager_mock = mocker.Mock(spec=PrefectManager)

    def get_fake_manager(catalogue=None, workflow_executor=None) -> PrefectManager:  # noqa: ARG001
        return manager_mock

    dependency_provider.override(get_manager.__wrapped__, get_fake_manager)
    yield manager_mock
    dependency_provider.clear()
