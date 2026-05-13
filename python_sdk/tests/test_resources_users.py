"""Tests for the admin-only ``client.users`` resource (feature 011)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from styrmin_sdk import (
    OperationFailedError,
    ResourceNotFoundError,
    Role,
    StyrminAuthorizationError,
    StyrminClient,
)


def _user_row(
    *,
    user_id: str = "11111111-1111-1111-1111-111111111111",
    username: str = "alice",
    display_name: str = "Alice",
    role: str = "READ_WRITE",
    effective_role: str | None = None,
    active: bool = True,
    groups: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Shape one ``User`` row exactly the way the GraphQL server returns it."""
    return {
        "id": user_id,
        "username": username,
        "displayName": display_name,
        "role": role,
        "effectiveRole": effective_role or role,
        "active": active,
        "groups": groups if groups is not None else [],
        "createdOn": "2026-05-11T00:00:00",
        "updatedOn": "2026-05-11T00:00:00",
    }


async def test_create_round_trip(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """``client.users.create(...)`` returns a User with the expected fields."""
    mock_transport.execute.return_value = {
        "data": {
            "createUser": _user_row(
                username="bob",
                display_name="Bob",
                role="READ_WRITE",
                effective_role="READ_WRITE",
                groups=[
                    {
                        "id": "22222222-2222-2222-2222-222222222222",
                        "name": "engineers",
                        "role": "READ_WRITE",
                    }
                ],
            ),
        }
    }

    user = await client.users.create(
        username="bob",
        password="hunter2hunter2",
        display_name="Bob",
        role=Role.READ_WRITE,
        group_ids=[UUID("22222222-2222-2222-2222-222222222222")],
    )

    assert user.username == "bob"
    assert user.display_name == "Bob"
    assert user.role == Role.READ_WRITE
    assert user.effective_role == Role.READ_WRITE
    assert user.active is True
    assert len(user.groups) == 1
    assert user.groups[0].name == "engineers"

    # Verify the SDK serializes the typed kwargs into the correct GraphQL input
    args, kwargs = mock_transport.execute.call_args
    variables = args[1] if len(args) > 1 else kwargs["variables"]
    assert variables == {
        "input": {
            "username": "bob",
            "password": "hunter2hunter2",
            "displayName": "Bob",
            "role": "READ_WRITE",
            "groupIds": ["22222222-2222-2222-2222-222222222222"],
        }
    }


async def test_update_clears_groups(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """``group_ids=[]`` clears memberships — must pass through as an empty list, not None."""
    mock_transport.execute.return_value = {
        "data": {
            "updateUser": _user_row(
                username="alice",
                display_name="Alice",
                role="READ_WRITE",
                groups=[],
            ),
        }
    }

    user = await client.users.update(
        UUID("11111111-1111-1111-1111-111111111111"),
        group_ids=[],
    )

    assert user.groups == []

    args, kwargs = mock_transport.execute.call_args
    variables = args[1] if len(args) > 1 else kwargs["variables"]
    assert variables["id"] == "11111111-1111-1111-1111-111111111111"
    assert variables["input"] == {"groupIds": []}


async def test_reset_password_returns_true(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {"data": {"resetUserPassword": True}}

    result = await client.users.reset_password(
        UUID("11111111-1111-1111-1111-111111111111"),
        "new-strong-passphrase",
    )

    assert result is True


async def test_delete_raises_user_has_references(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """``deleteUser`` returns ``USER_HAS_REFERENCES`` when FK references exist;
    the SDK maps any non-special code to :class:`OperationFailedError`,
    and the original code is preserved on ``.typename``."""
    mock_transport.execute.return_value = {
        "data": {"deleteUser": None},
        "errors": [
            {
                "message": "Cannot delete user: referenced by 3 deployments.",
                "extensions": {"code": "USER_HAS_REFERENCES"},
            }
        ],
    }

    with pytest.raises(OperationFailedError) as exc_info:
        await client.users.delete(UUID("11111111-1111-1111-1111-111111111111"))

    assert exc_info.value.typename == "USER_HAS_REFERENCES"
    assert "referenced" in str(exc_info.value)


async def test_list_with_filters(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """All three filter arguments are forwarded as GraphQL variables."""
    mock_transport.execute.return_value = {
        "data": {
            "users": [
                _user_row(username="alice", role="ADMIN", effective_role="ADMIN"),
                _user_row(
                    user_id="33333333-3333-3333-3333-333333333333",
                    username="alfred",
                    role="ADMIN",
                    effective_role="ADMIN",
                ),
            ],
        }
    }

    users = await client.users.list(active=True, role=Role.ADMIN, search="al")

    assert len(users) == 2
    assert {u.username for u in users} == {"alice", "alfred"}

    args, kwargs = mock_transport.execute.call_args
    variables = args[1] if len(args) > 1 else kwargs["variables"]
    assert variables == {"active": True, "role": "ADMIN", "search": "al"}


async def test_forbidden_for_non_admin_token(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """A non-admin caller receives ``FORBIDDEN`` from every admin operation.

    The transport here is mocked, so we simulate the server's role-guard
    response and assert that every method on ``client.users`` surfaces it
    as :class:`StyrminAuthorizationError`. The real server-side guard is
    covered by the role-gating tests in
    ``backend/tests/functional/auth/test_admin_user_mutations.py``.
    """
    forbidden_response = {
        "data": None,
        "errors": [
            {
                "message": "Admin role required",
                "extensions": {"code": "FORBIDDEN"},
            }
        ],
    }
    mock_transport.execute.return_value = forbidden_response
    user_id = UUID("11111111-1111-1111-1111-111111111111")

    with pytest.raises(StyrminAuthorizationError):
        await client.users.create(
            username="charlie",
            password="hunter2hunter2",
            display_name="Charlie",
            role=Role.READ_WRITE,
        )
    with pytest.raises(StyrminAuthorizationError):
        await client.users.update(user_id, display_name="New name")
    with pytest.raises(StyrminAuthorizationError):
        await client.users.reset_password(user_id, "new-passphrase")
    with pytest.raises(StyrminAuthorizationError):
        await client.users.delete(user_id)
    with pytest.raises(StyrminAuthorizationError):
        await client.users.list()
    with pytest.raises(StyrminAuthorizationError):
        await client.users.get(user_id)


async def test_get_returns_matching_user(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """``get`` issues ``Query.user(id:)`` and returns the matching row."""
    mock_transport.execute.return_value = {
        "data": {
            "user": _user_row(user_id="22222222-2222-2222-2222-222222222222", username="bob"),
        }
    }

    user = await client.users.get(UUID("22222222-2222-2222-2222-222222222222"))

    assert user.username == "bob"

    # The id is forwarded to the server — the SDK must not fetch the
    # entire user list any more.
    args, kwargs = mock_transport.execute.call_args
    variables = args[1] if len(args) > 1 else kwargs["variables"]
    assert variables == {"id": "22222222-2222-2222-2222-222222222222"}


async def test_get_raises_when_server_returns_not_found(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """``USER_NOT_FOUND`` from the server surfaces as ResourceNotFoundError."""
    mock_transport.execute.return_value = {
        "data": {"user": None},
        "errors": [
            {
                "message": "User not found",
                "extensions": {"code": "USER_NOT_FOUND"},
            }
        ],
    }

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await client.users.get(UUID("99999999-9999-9999-9999-999999999999"))

    assert exc_info.value.typename == "USER_NOT_FOUND"


async def test_get_raises_when_server_returns_null_without_error(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    """Defensive fallback: a null user without an error still raises."""
    mock_transport.execute.return_value = {"data": {"user": None}}

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await client.users.get(UUID("99999999-9999-9999-9999-999999999999"))

    assert exc_info.value.typename == "USER_NOT_FOUND"
