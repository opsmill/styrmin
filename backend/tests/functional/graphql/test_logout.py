"""Functional / propagation tests for ``Mutation.logout``. See issue #189."""

from __future__ import annotations

import hashlib

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Session as SessionModel
from styrmin_backend.db.models import User
from styrmin_backend.services.auth.password import hash_password
from styrmin_backend.services.auth.session import create_session

from ._queries import load_query
from .conftest import gql

PASSWORD = "correct horse battery staple"


async def _seed_user_with_token(
    session: AsyncSession, *, username: str = "alice"
) -> tuple[User, str]:
    user = User(
        username=username,
        password_hash=hash_password(PASSWORD),
        display_name=username,
        active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    _row, raw_token = await create_session(session, user.id)
    return user, raw_token


@pytest.mark.asyncio
async def test_logout_deletes_calling_session_row(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    user, token = await _seed_user_with_token(session)

    digest = hashlib.sha256(token.encode("ascii")).digest()
    pre_rows = (
        await session.exec(
            select(SessionModel).where(SessionModel.token_hash == digest)
        )
    ).all()
    assert len(pre_rows) == 1

    response = await unauth_client.post(
        "/graphql",
        json={"query": load_query("logout")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    assert payload["data"]["logout"] is True

    post_rows = (
        await session.exec(select(SessionModel).where(SessionModel.user_id == user.id))
    ).all()
    assert post_rows == []


@pytest.mark.asyncio
async def test_logout_clears_cookie(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    _user, token = await _seed_user_with_token(session)
    response = await unauth_client.post(
        "/graphql",
        json={"query": load_query("logout")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    # FastAPI's delete_cookie writes Max-Age=0 (and an empty value).
    assert "styrmin_session=" in set_cookie
    assert "Max-Age=0" in set_cookie or "max-age=0" in set_cookie.lower()


@pytest.mark.asyncio
async def test_old_token_after_logout_returns_unauthenticated(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    """ADR-024 instant-revocation: the same token that logged out must not
    let any subsequent caller through the auth path."""
    _user, token = await _seed_user_with_token(session)

    await unauth_client.post(
        "/graphql",
        json={"query": load_query("logout")},
        headers={"Authorization": f"Bearer {token}"},
    )

    follow_up = await unauth_client.post(
        "/graphql",
        json={
            "query": load_query("create_cluster"),
            "variables": {"name": "x"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert follow_up.status_code == 200
    payload = follow_up.json()
    errors = payload.get("errors") or []
    assert errors, payload
    assert errors[0]["extensions"]["code"] == "UNAUTHENTICATED"


@pytest.mark.asyncio
async def test_logout_idempotent_when_unauthenticated(
    unauth_client: AsyncClient,
) -> None:
    """ADR-025 documents logout as allow-listed — pre-auth callers
    receive ``true`` and a cookie clear, not ``UNAUTHENTICATED``."""
    data = await gql(unauth_client, "logout")
    assert data["logout"] is True
