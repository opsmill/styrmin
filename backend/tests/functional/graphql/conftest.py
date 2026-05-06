"""Shared fixtures for GraphQL ↔ DB propagation tests.

Provides the in-memory SQLite ``session``, an authenticated-as-admin
``client`` (with bearer token pre-seeded), an ``unauth_client`` for the
explicit unauth path, and ``prefect_manager_mock``. Plus the ``gql``
helper that posts an operation file by name, asserts a clean 200, and
returns the ``data`` payload.

Default-deny is on (ADR-020). Tests that hit any non-allow-listed field
must use ``client`` (authenticated as admin); tests that exercise the
unauth path use ``unauth_client``.

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

from styrmin_backend.db.models import Role, User
from styrmin_backend.db.utils import get_session
from styrmin_backend.server.app import app
from styrmin_backend.services.auth.password import hash_password
from styrmin_backend.services.auth.session import create_session
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.manager import PrefectManager

from ._queries import load_query

ADMIN_PASSWORD = "test-admin-password"


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


@pytest.fixture
async def admin_user(session: AsyncSession) -> User:
    """Seed an admin user with role=ADMIN. The default credentials for
    every functional GraphQL test that needs an authenticated session.
    """
    user = User(
        username="test-admin",
        password_hash=hash_password(ADMIN_PASSWORD),
        display_name="Test Admin",
        active=True,
        role=Role.ADMIN,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest.fixture
async def admin_token(session: AsyncSession, admin_user: User) -> str:
    """Mint a fresh session token for ``admin_user``.

    Returns the raw bearer string; auth-resolution downstream uses the
    sha256(token) lookup on the same row.
    """
    _row, raw_token = await create_session(session, admin_user.id)
    return raw_token


@pytest.fixture(name="unauth_client")
async def unauth_client_fixture(session: AsyncSession):
    """ASGI client that sends *no* authentication headers.

    Use this for tests that explicitly verify the unauthenticated path
    (login negotiation, RequiresAuthentication enforcement,
    ``currentUser`` returning null, introspection without auth).
    """

    async def get_session_override():
        yield session

    app.dependency_overrides[get_session] = get_session_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture(name="client")
async def authenticated_client_fixture(session: AsyncSession, admin_token: str):
    """Default client for functional tests — authenticated as admin via Bearer.

    Default-deny is on, so the unauthenticated client cannot exercise
    most resolvers; making the default authenticated keeps the per-test
    diff small while still routing every request through the production
    auth path.
    """

    async def get_session_override():
        yield session

    app.dependency_overrides[get_session] = get_session_override

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {admin_token}"},
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
