"""Tests for the admin-only ``client.groups`` resource (feature 011)."""

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


def _group_row(
    *,
    group_id: str = "22222222-2222-2222-2222-222222222222",
    name: str = "engineers",
    role: str = "READ_WRITE",
) -> dict[str, Any]:
    """Shape one ``Group`` row exactly the way the GraphQL server returns it."""
    return {
        "id": group_id,
        "name": name,
        "role": role,
    }


async def test_create_group_round_trip(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """``client.groups.create(...)`` returns a Group with the expected fields."""
    mock_transport.execute.return_value = {
        "data": {
            "createGroup": _group_row(
                name="admins",
                role="ADMIN",
            ),
        }
    }

    group = await client.groups.create(
        name="admins",
        role=Role.ADMIN,
        member_ids=[UUID("11111111-1111-1111-1111-111111111111")],
    )

    assert group.name == "admins"
    assert group.role == Role.ADMIN

    # Verify the SDK serializes the typed kwargs into the correct GraphQL input
    args, kwargs = mock_transport.execute.call_args
    variables = args[1] if len(args) > 1 else kwargs["variables"]
    assert variables == {
        "input": {
            "name": "admins",
            "role": "ADMIN",
            "memberIds": ["11111111-1111-1111-1111-111111111111"],
        }
    }


async def test_update_clears_members(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """``member_ids=[]`` clears memberships — must pass through as an empty list, not None."""
    mock_transport.execute.return_value = {
        "data": {
            "updateGroup": _group_row(
                name="engineers",
                role="READ_WRITE",
            ),
        }
    }

    group = await client.groups.update(
        UUID("22222222-2222-2222-2222-222222222222"),
        member_ids=[],
    )

    assert group.name == "engineers"

    args, kwargs = mock_transport.execute.call_args
    variables = args[1] if len(args) > 1 else kwargs["variables"]
    assert variables["id"] == "22222222-2222-2222-2222-222222222222"
    assert variables["input"] == {"memberIds": []}


async def test_delete_returns_true(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {"data": {"deleteGroup": True}}

    result = await client.groups.delete(UUID("22222222-2222-2222-2222-222222222222"))

    assert result is True


async def test_delete_raises_last_admin(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """``deleteGroup`` returns ``LAST_ADMIN`` when removal would leave zero admins;
    the SDK maps any non-special code to :class:`OperationFailedError`, and the
    original code is preserved on ``.typename``."""
    mock_transport.execute.return_value = {
        "data": {"deleteGroup": None},
        "errors": [
            {
                "message": "Cannot delete group: would leave zero admins.",
                "extensions": {"code": "LAST_ADMIN"},
            }
        ],
    }

    with pytest.raises(OperationFailedError) as exc_info:
        await client.groups.delete(UUID("22222222-2222-2222-2222-222222222222"))

    assert exc_info.value.typename == "LAST_ADMIN"
    assert "zero admins" in str(exc_info.value)


async def test_list_with_search(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """The ``search`` filter is forwarded as a GraphQL variable."""
    mock_transport.execute.return_value = {
        "data": {
            "groups": [
                _group_row(name="engineers", role="READ_WRITE"),
                _group_row(
                    group_id="33333333-3333-3333-3333-333333333333",
                    name="engineering-leads",
                    role="ADMIN",
                ),
            ],
        }
    }

    groups = await client.groups.list(search="eng")

    assert len(groups) == 2
    assert {g.name for g in groups} == {"engineers", "engineering-leads"}

    args, kwargs = mock_transport.execute.call_args
    variables = args[1] if len(args) > 1 else kwargs["variables"]
    assert variables == {"search": "eng"}


async def test_forbidden_for_non_admin_token(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """A non-admin caller receives ``FORBIDDEN`` from every admin operation.

    The transport here is mocked, so we simulate the server's role-guard
    response and assert that every method on ``client.groups`` surfaces it
    as :class:`StyrminAuthorizationError`. The real server-side guard is
    covered by the role-gating tests in
    ``backend/tests/functional/auth/test_admin_group_mutations.py``.
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
    group_id = UUID("22222222-2222-2222-2222-222222222222")

    with pytest.raises(StyrminAuthorizationError):
        await client.groups.create(name="newgroup", role=Role.READ_WRITE)
    with pytest.raises(StyrminAuthorizationError):
        await client.groups.update(group_id, name="renamed")
    with pytest.raises(StyrminAuthorizationError):
        await client.groups.delete(group_id)
    with pytest.raises(StyrminAuthorizationError):
        await client.groups.list()
    with pytest.raises(StyrminAuthorizationError):
        await client.groups.get(group_id)


async def test_get_returns_matching_group(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """``get`` filters the admin-only ``groups`` list client-side."""
    mock_transport.execute.return_value = {
        "data": {
            "groups": [
                _group_row(group_id="22222222-2222-2222-2222-222222222222", name="engineers"),
                _group_row(group_id="33333333-3333-3333-3333-333333333333", name="ops"),
            ]
        }
    }

    group = await client.groups.get(UUID("33333333-3333-3333-3333-333333333333"))

    assert group.name == "ops"


async def test_get_raises_when_missing(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {
            "groups": [
                _group_row(group_id="22222222-2222-2222-2222-222222222222", name="engineers"),
            ]
        }
    }

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await client.groups.get(UUID("99999999-9999-9999-9999-999999999999"))

    assert exc_info.value.typename == "GROUP_NOT_FOUND"
