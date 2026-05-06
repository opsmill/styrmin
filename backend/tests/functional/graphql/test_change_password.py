"""Functional / propagation tests for ``Mutation.changePassword``. See issue #189."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import User
from styrmin_backend.services.auth.password import hash_password, verify_password
from styrmin_backend.services.auth.session import create_session

from ._queries import load_query

CURRENT_PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "another correct horse battery"


async def _seed_user(session: AsyncSession, *, username: str = "alice") -> User:
    user = User(
        username=username,
        password_hash=hash_password(CURRENT_PASSWORD),
        display_name=username,
        active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _login(client: AsyncClient, *, username: str, password: str) -> str:
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("login"),
            "variables": {"username": username, "password": password},
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload
    return payload["data"]["login"]["token"]


async def _change_password(
    client: AsyncClient, token: str, *, current: str, new: str
) -> dict:
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("change_password"),
            "variables": {"currentPassword": current, "newPassword": new},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    return response.json()


@pytest.mark.asyncio
async def test_change_password_happy_path_rotates_hash(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    user = await _seed_user(session)
    token = await _login(
        unauth_client, username=user.username, password=CURRENT_PASSWORD
    )

    payload = await _change_password(
        unauth_client, token, current=CURRENT_PASSWORD, new=NEW_PASSWORD
    )
    assert "errors" not in payload, payload
    assert payload["data"]["changePassword"] is True

    # Hash has changed and verifies against the new password.
    refreshed = (
        await session.exec(select(User).where(User.username == user.username))
    ).one()
    assert verify_password(refreshed.password_hash, NEW_PASSWORD) is True
    assert verify_password(refreshed.password_hash, CURRENT_PASSWORD) is False

    # New password lets the user log in afterwards.
    new_token = await _login(
        unauth_client, username=user.username, password=NEW_PASSWORD
    )
    assert new_token


@pytest.mark.asyncio
async def test_change_password_wrong_current_password_returns_invalid_credentials(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    user = await _seed_user(session)
    token = await _login(
        unauth_client, username=user.username, password=CURRENT_PASSWORD
    )

    payload = await _change_password(
        unauth_client,
        token,
        current="wrong-password-here",
        new=NEW_PASSWORD,
    )
    errors = payload.get("errors") or []
    assert errors, payload
    assert errors[0]["extensions"]["code"] == "INVALID_CREDENTIALS"

    refreshed = (
        await session.exec(select(User).where(User.username == user.username))
    ).one()
    assert verify_password(refreshed.password_hash, CURRENT_PASSWORD) is True


@pytest.mark.asyncio
async def test_change_password_invalidates_other_sessions_keeps_caller(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    """Two sessions for the same user — change password on one, the other
    must be invalidated and the caller must remain valid. See ADR-019."""
    user = await _seed_user(session)
    # First session: the one we'll *call* changePassword from.
    _row_a, token_a = await create_session(session, user.id)
    # Second session: the one that should be invalidated.
    _row_b, token_b = await create_session(session, user.id)

    payload = await _change_password(
        unauth_client, token_a, current=CURRENT_PASSWORD, new=NEW_PASSWORD
    )
    assert "errors" not in payload, payload
    assert payload["data"]["changePassword"] is True

    # Other token: rejected.
    other = await unauth_client.post(
        "/graphql",
        json={"query": load_query("current_user")},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    other_payload = other.json()
    assert other_payload["data"]["currentUser"] is None

    # Calling token: still works.
    caller = await unauth_client.post(
        "/graphql",
        json={"query": load_query("current_user")},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    caller_payload = caller.json()
    assert "errors" not in caller_payload, caller_payload
    assert caller_payload["data"]["currentUser"]["username"] == user.username


@pytest.mark.asyncio
async def test_change_password_unauthenticated_returns_unauthenticated(
    unauth_client: AsyncClient,
) -> None:
    """RequiresAuthentication runs first — no token, no rotate."""
    response = await unauth_client.post(
        "/graphql",
        json={
            "query": load_query("change_password"),
            "variables": {
                "currentPassword": CURRENT_PASSWORD,
                "newPassword": NEW_PASSWORD,
            },
        },
    )
    payload = response.json()
    errors = payload.get("errors") or []
    assert errors, payload
    assert errors[0]["extensions"]["code"] == "UNAUTHENTICATED"
