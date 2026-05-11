"""Shared fixtures for the admin user/group functional test pack.

Mirrors the in-memory SQLite + ASGI client shape from
``backend/tests/functional/graphql/conftest.py`` and adds role-tiered
authenticated clients (``admin_client`` / ``read_write_client`` /
``read_only_client``) so the FR-007 RBAC matrix can be expressed as
straightforward per-client requests.

The fixtures load the canonical operation files from
``backend/tests/functional/graphql/operations/`` via the same
``load_query`` helper used by every other propagation test — operation
strings live in one validated place per project policy.
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

from tests.functional.graphql._queries import load_query

USER_PASSWORD = "correct horse battery staple"


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
        # Stash the engine on the session so individual tests can register
        # SQLAlchemy event listeners on the underlying engine (used by the
        # N+1 / eager-loading test).
        session.info["_engine"] = engine
        yield session
    await engine.dispose()


async def _seed_user_at_role(
    session: AsyncSession, *, username: str, role: Role
) -> tuple[User, str]:
    """Create a user at ``role`` and mint a fresh bearer token for them."""
    user = User(
        username=username,
        password_hash=hash_password(USER_PASSWORD),
        display_name=username,
        active=True,
        role=role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    _row, raw_token = await create_session(session, user.id)
    return user, raw_token


@pytest.fixture
async def admin_user(session: AsyncSession) -> User:
    user, _token = await _seed_user_at_role(session, username="admin", role=Role.ADMIN)
    return user


@pytest.fixture
async def admin_token(session: AsyncSession, admin_user: User) -> str:
    _row, raw_token = await create_session(session, admin_user.id)
    return raw_token


@pytest.fixture
async def read_write_user(session: AsyncSession) -> User:
    user, _token = await _seed_user_at_role(
        session, username="alice-rw", role=Role.READ_WRITE
    )
    return user


@pytest.fixture
async def read_only_user(session: AsyncSession) -> User:
    user, _token = await _seed_user_at_role(
        session, username="alice-ro", role=Role.READ_ONLY
    )
    return user


def _override_session(session: AsyncSession) -> None:
    async def get_session_override():
        yield session

    app.dependency_overrides[get_session] = get_session_override


@pytest.fixture(name="unauth_client")
async def unauth_client_fixture(session: AsyncSession):
    _override_session(session)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture(name="admin_client")
async def admin_client_fixture(session: AsyncSession, admin_token: str):
    _override_session(session)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {admin_token}"},
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture(name="read_write_client")
async def read_write_client_fixture(session: AsyncSession, read_write_user: User):
    _row, token = await create_session(session, read_write_user.id)
    _override_session(session)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture(name="read_only_client")
async def read_only_client_fixture(session: AsyncSession, read_only_user: User):
    _row, token = await create_session(session, read_only_user.id)
    _override_session(session)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def prefect_manager_mock(mocker):
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
    """POST a named operation and return ``data``, asserting clean success."""
    response = await client.post(
        "/graphql",
        json={"query": load_query(operation), "variables": variables or {}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    return payload["data"]


async def gql_raw(
    client: AsyncClient,
    operation: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST a named operation and return the full JSON payload (errors-allowed)."""
    response = await client.post(
        "/graphql",
        json={"query": load_query(operation), "variables": variables or {}},
    )
    assert response.status_code == 200
    return response.json()
