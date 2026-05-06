"""Functional / propagation tests for login + currentUser (issue #185)."""

from __future__ import annotations

import hashlib
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Session as SessionModel
from styrmin_backend.db.models import User
from styrmin_backend.services.auth.password import hash_password

from ._queries import load_query
from .conftest import gql

PASSWORD = "correct horse battery staple"


async def _seed_user(
    session: AsyncSession,
    *,
    username: str = "alice",
    active: bool = True,
) -> User:
    user = User(
        username=username,
        password_hash=hash_password(PASSWORD),
        display_name="Alice Example",
        active=active,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _post_login(
    client: AsyncClient, *, username: str, password: str
) -> tuple[int, dict, dict]:
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("login"),
            "variables": {"username": username, "password": password},
        },
    )
    return response.status_code, response.json(), dict(response.headers)


@pytest.mark.asyncio
async def test_login_happy_path_returns_token_and_sets_cookie(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    user = await _seed_user(session)

    status_code, payload, headers = await _post_login(
        unauth_client, username="alice", password=PASSWORD
    )

    assert status_code == 200
    assert "errors" not in payload, payload
    data = payload["data"]["login"]
    assert data["token"]
    assert data["user"]["username"] == "alice"
    assert UUID(data["user"]["id"]) == user.id

    set_cookie = headers.get("set-cookie", "")
    assert "styrmin_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=lax" in set_cookie.lower() or "samesite=lax" in set_cookie.lower()
    assert "Path=/" in set_cookie

    digest = hashlib.sha256(data["token"].encode("ascii")).digest()
    rows = (
        await session.exec(
            select(SessionModel).where(SessionModel.token_hash == digest)
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].user_id == user.id


@pytest.mark.asyncio
async def test_login_wrong_password_returns_invalid_credentials(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    await _seed_user(session)
    status_code, payload, _ = await _post_login(
        unauth_client, username="alice", password="wrong-password-here"
    )
    assert status_code == 200
    errors = payload.get("errors") or []
    assert errors
    assert errors[0]["extensions"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_login_nonexistent_user_returns_invalid_credentials(
    unauth_client: AsyncClient,
    session: AsyncSession,  # noqa: ARG001
) -> None:
    status_code, payload, _ = await _post_login(
        unauth_client, username="ghost", password=PASSWORD
    )
    assert status_code == 200
    errors = payload.get("errors") or []
    assert errors
    assert errors[0]["extensions"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_login_deactivated_user_returns_invalid_credentials(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    await _seed_user(session, active=False)
    status_code, payload, _ = await _post_login(
        unauth_client, username="alice", password=PASSWORD
    )
    assert status_code == 200
    errors = payload.get("errors") or []
    assert errors
    assert errors[0]["extensions"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_login_invalid_credentials_messages_match(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    await _seed_user(session, username="alice", active=True)
    await _seed_user(session, username="bob", active=False)
    _, wrong_pw, _ = await _post_login(
        unauth_client, username="alice", password="wrong-password-here"
    )
    _, no_user, _ = await _post_login(
        unauth_client, username="ghost", password=PASSWORD
    )
    _, deactivated, _ = await _post_login(
        unauth_client, username="bob", password=PASSWORD
    )
    msg_a = wrong_pw["errors"][0]["message"]
    msg_b = no_user["errors"][0]["message"]
    msg_c = deactivated["errors"][0]["message"]
    assert msg_a == msg_b == msg_c


@pytest.mark.asyncio
async def test_current_user_unauthenticated_returns_null(
    unauth_client: AsyncClient,
    session: AsyncSession,  # noqa: ARG001
) -> None:
    data = await gql(unauth_client, "current_user")
    assert data["currentUser"] is None


@pytest.mark.asyncio
async def test_current_user_via_bearer_returns_user(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    await _seed_user(session)
    _, login_payload, _ = await _post_login(
        unauth_client, username="alice", password=PASSWORD
    )
    token = login_payload["data"]["login"]["token"]

    response = await unauth_client.post(
        "/graphql",
        json={"query": load_query("current_user")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    assert payload["data"]["currentUser"]["username"] == "alice"


@pytest.mark.asyncio
async def test_current_user_via_cookie_returns_user(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    await _seed_user(session)
    _, login_payload, _ = await _post_login(
        unauth_client, username="alice", password=PASSWORD
    )
    token = login_payload["data"]["login"]["token"]

    response = await unauth_client.post(
        "/graphql",
        json={"query": load_query("current_user")},
        headers={"Cookie": f"styrmin_session={token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    assert payload["data"]["currentUser"]["username"] == "alice"
