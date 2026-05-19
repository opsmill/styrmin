"""SDK tests for the auth resource and token plumbing."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from styrmin_sdk import (
    StyrminAuthenticationError,
    StyrminAuthorizationError,
    StyrminClient,
)


async def test_login_plumbs_token_into_transport(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {
            "login": {
                "token": "raw-session-token-xyz",
                "user": {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "username": "alice",
                    "displayName": "Alice",
                },
            },
        },
    }

    result = await client.auth.login(username="alice", password="correct horse battery")

    assert result.token == "raw-session-token-xyz"
    assert result.user.username == "alice"
    mock_transport.set_authorization.assert_called_once_with("raw-session-token-xyz")


async def test_styrmin_token_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STYRMIN_TOKEN", "env-token-abc")
    instance = StyrminClient(server_address="http://test")
    try:
        assert instance._transport._client.headers["Authorization"] == "Bearer env-token-abc"
    finally:
        await instance.close()


async def test_explicit_token_kwarg_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STYRMIN_TOKEN", "env-token-abc")
    instance = StyrminClient(server_address="http://test", token="kwarg-token-xyz")
    try:
        assert instance._transport._client.headers["Authorization"] == "Bearer kwarg-token-xyz"
    finally:
        await instance.close()


async def test_no_authorization_header_when_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STYRMIN_TOKEN", raising=False)
    instance = StyrminClient(server_address="http://test")
    try:
        assert "Authorization" not in instance._transport._client.headers
    finally:
        await instance.close()


async def test_unauthenticated_raises_authentication_error(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {"currentUser": None},
        "errors": [{"message": "Not authenticated", "extensions": {"code": "UNAUTHENTICATED"}}],
    }
    with pytest.raises(StyrminAuthenticationError):
        await client.auth.current_user()


async def test_invalid_credentials_raises_authentication_error(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    mock_transport.execute.return_value = {
        "data": {"login": None},
        "errors": [{"message": "Invalid credentials", "extensions": {"code": "INVALID_CREDENTIALS"}}],
    }
    with pytest.raises(StyrminAuthenticationError):
        await client.auth.login(username="alice", password="wrong-password-here")


async def test_current_user_returns_none_when_unauthenticated(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {"data": {"currentUser": None}}
    result = await client.auth.current_user()
    assert result is None


async def test_forbidden_raises_authorization_error(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """A FORBIDDEN response (insufficient role) maps to a typed exception
    distinct from authentication errors. See ADR-012.
    """
    mock_transport.execute.return_value = {
        "data": {"currentUser": None},
        "errors": [
            {
                "message": "Insufficient permissions",
                "extensions": {"code": "FORBIDDEN"},
            }
        ],
    }
    with pytest.raises(StyrminAuthorizationError):
        await client.auth.current_user()


async def test_logout_returns_true_and_clears_token(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {"data": {"logout": True}}
    result = await client.auth.logout()
    assert result is True
    mock_transport.set_authorization.assert_called_once_with(None)


async def test_change_password_returns_true_and_keeps_token(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """The calling session is preserved server-side; the SDK keeps its
    bearer header so the next call still authenticates."""
    mock_transport.execute.return_value = {"data": {"changePassword": True}}
    result = await client.auth.change_password(
        current_password="old-password-12345",
        new_password="new-password-67890",
    )
    assert result is True
    mock_transport.set_authorization.assert_not_called()


async def test_change_password_invalid_credentials_raises_authentication_error(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    mock_transport.execute.return_value = {
        "data": {"changePassword": None},
        "errors": [
            {
                "message": "Invalid credentials",
                "extensions": {"code": "INVALID_CREDENTIALS"},
            }
        ],
    }
    with pytest.raises(StyrminAuthenticationError):
        await client.auth.change_password(
            current_password="wrong-password-here",
            new_password="new-password-67890",
        )


async def test_current_user_returns_user_when_authenticated(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {
            "currentUser": {
                "id": "11111111-1111-1111-1111-111111111111",
                "username": "alice",
                "displayName": "Alice",
                "role": "READ_WRITE",
                "effectiveRole": "READ_WRITE",
            },
        },
    }
    result = await client.auth.current_user()
    assert result is not None
    assert result.username == "alice"
