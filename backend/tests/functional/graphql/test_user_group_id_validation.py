"""Regression tests for malformed UUIDs in user/group reference inputs (#351).

``groupIds`` / ``memberIds`` are declared ``[ID!]`` in the GraphQL schema, so
Strawberry does not validate their syntax. Before the fix the resolvers parsed
each entry with a bare ``UUID(...)`` call, so a malformed value raised an
unhandled ``ValueError`` that the error handler masked as ``INTERNAL_ERROR``.
These tests pin the typed ``VALIDATION_ERROR`` contract for all four mutations,
and keep the existing ``GROUP_NOT_FOUND`` / ``USER_NOT_FOUND`` behaviour for a
syntactically valid but unknown UUID.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Group, Role, User

from ._queries import load_query
from .seeds import seed_user

UNKNOWN_UUID = "00000000-0000-0000-0000-000000000000"
MALFORMED_ID = "not-a-uuid"
PASSWORD = "correct horse battery staple"

VariablesBuilder = Callable[[str, str], dict[str, Any]]


async def _seed_group(session: AsyncSession, *, name: str) -> Group:
    group = Group(name=name, role=Role.READ_ONLY)
    session.add(group)
    await session.commit()
    await session.refresh(group)
    return group


def _first_error(response: Any) -> dict[str, Any]:
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("errors"), f"expected a typed error, got: {payload}"
    return payload["errors"][0]


def _error_code(error: dict[str, Any]) -> str:
    return str((error.get("extensions") or {}).get("code"))


# Each row builds the GraphQL variables for one mutation. ``user_id`` /
# ``group_id`` are the seeded rows the update variants target.
_MALFORMED_CASES: list[tuple[str, VariablesBuilder, str, str]] = [
    (
        "create_user",
        lambda _u, _g: {
            "input": {
                "username": "new-user",
                "password": PASSWORD,
                "displayName": "New User",
                "role": "READ_ONLY",
                "groupIds": [MALFORMED_ID],
            }
        },
        "VALIDATION_ERROR",
        "groupIds",
    ),
    (
        "update_user",
        lambda u, _g: {"id": u, "input": {"groupIds": [MALFORMED_ID]}},
        "VALIDATION_ERROR",
        "groupIds",
    ),
    (
        "create_group",
        lambda _u, _g: {
            "input": {
                "name": "new-group",
                "role": "READ_ONLY",
                "memberIds": [MALFORMED_ID],
            }
        },
        "VALIDATION_ERROR",
        "memberIds",
    ),
    (
        "update_group",
        lambda _u, g: {"id": g, "input": {"memberIds": [MALFORMED_ID]}},
        "VALIDATION_ERROR",
        "memberIds",
    ),
]

_UNKNOWN_CASES: list[tuple[str, VariablesBuilder, str]] = [
    (
        "create_user",
        lambda _u, _g: {
            "input": {
                "username": "new-user",
                "password": PASSWORD,
                "displayName": "New User",
                "role": "READ_ONLY",
                "groupIds": [UNKNOWN_UUID],
            }
        },
        "GROUP_NOT_FOUND",
    ),
    (
        "update_user",
        lambda u, _g: {"id": u, "input": {"groupIds": [UNKNOWN_UUID]}},
        "GROUP_NOT_FOUND",
    ),
    (
        "create_group",
        lambda _u, _g: {
            "input": {
                "name": "new-group",
                "role": "READ_ONLY",
                "memberIds": [UNKNOWN_UUID],
            }
        },
        "USER_NOT_FOUND",
    ),
    (
        "update_group",
        lambda _u, g: {"id": g, "input": {"memberIds": [UNKNOWN_UUID]}},
        "USER_NOT_FOUND",
    ),
]


async def _run(
    client: AsyncClient,
    session: AsyncSession,
    operation: str,
    build_variables: VariablesBuilder,
) -> dict[str, Any]:
    target_user: User = await seed_user(session, username="target-user")
    target_group = await _seed_group(session, name="target-group")

    response = await client.post(
        "/graphql",
        json={
            "query": load_query(operation),
            "variables": build_variables(str(target_user.id), str(target_group.id)),
        },
    )
    return _first_error(response)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "build_variables", "expected_code", "expected_field"),
    _MALFORMED_CASES,
    ids=[case[0] for case in _MALFORMED_CASES],
)
async def test_malformed_reference_id_returns_validation_error(
    client: AsyncClient,
    session: AsyncSession,
    operation: str,
    build_variables: VariablesBuilder,
    expected_code: str,
    expected_field: str,
) -> None:
    """A syntactically invalid ``groupIds`` / ``memberIds`` entry is rejected
    with a typed ``VALIDATION_ERROR`` whose message names the field and value."""
    error = await _run(client, session, operation, build_variables)

    assert _error_code(error) == expected_code
    message = str(error.get("message", ""))
    assert expected_field in message
    assert MALFORMED_ID in message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "build_variables", "expected_code"),
    _UNKNOWN_CASES,
    ids=[case[0] for case in _UNKNOWN_CASES],
)
async def test_unknown_but_valid_reference_id_is_not_found(
    client: AsyncClient,
    session: AsyncSession,
    operation: str,
    build_variables: VariablesBuilder,
    expected_code: str,
) -> None:
    """A syntactically valid but unknown UUID keeps its typed not-found error."""
    error = await _run(client, session, operation, build_variables)
    assert _error_code(error) == expected_code
