"""Shared fixtures for GraphQL ↔ DB propagation tests.

Provides the in-memory SQLite ``session``, ASGI ``client``, and
``prefect_manager_mock`` fixtures plus a small ``gql`` helper that posts an
operation file by name, asserts a clean 200 response, and returns the
``data`` payload — the four lines almost every propagation test repeats.

See specs/007-graphql-propagation-tests/contracts/propagation-test-contract.md.
"""

from __future__ import annotations

from typing import Any

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

from ._queries import load_query


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


async def gql(
    client: AsyncClient,
    operation: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST a named operation and return ``data``, asserting clean success.

    Loads ``operation`` from ``operations/<operation>.graphql``, posts it with
    the given variables, asserts HTTP 200 and no GraphQL errors, and returns
    ``payload["data"]``. Tests that need the full payload (e.g. negative-path
    tests asserting on ``errors``) should call ``client.post`` directly.
    """

    response = await client.post(
        "/graphql",
        json={"query": load_query(operation), "variables": variables or {}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    return payload["data"]
