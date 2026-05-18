"""Unit tests for ``RequiresAuthentication`` and ``RequiresRole``. See ADR-017."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from graphql import GraphQLError

from styrmin_backend.api.auth.extensions import RequiresAuthentication
from styrmin_backend.api.auth.permissions import RequiresRole
from styrmin_backend.db.models import Role, User


def _user(role: Role) -> User:
    user = User(
        id=uuid4(),
        username="example",
        password_hash="not-a-hash",
        display_name="example",
        active=True,
        role=role,
    )
    user.groups = []
    return user


def _info(
    *,
    field_name: str,
    parent_type_name: str,
    is_root: bool,
    current_user: User | None,
) -> Any:
    """Build a minimal GraphQLResolveInfo stand-in for the resolve hook."""
    path = SimpleNamespace(prev=None) if is_root else SimpleNamespace(prev=object())
    parent_type = SimpleNamespace(name=parent_type_name)
    return SimpleNamespace(
        field_name=field_name,
        parent_type=parent_type,
        path=path,
        context={"current_user": current_user},
    )


# ---------------------------------------------------------------------------
# RequiresAuthentication
# ---------------------------------------------------------------------------


def test_requires_authentication_passes_for_authenticated_user() -> None:
    ext = RequiresAuthentication()
    info = _info(
        field_name="createCluster",
        parent_type_name="Mutation",
        is_root=True,
        current_user=_user(Role.ADMIN),
    )
    sentinel = object()
    next_fn = MagicMock(return_value=sentinel)
    assert ext.resolve(next_fn, None, info) is sentinel
    next_fn.assert_called_once()


def test_requires_authentication_rejects_unauthenticated_root_field() -> None:
    ext = RequiresAuthentication()
    info = _info(
        field_name="createCluster",
        parent_type_name="Mutation",
        is_root=True,
        current_user=None,
    )
    next_fn = MagicMock()
    with pytest.raises(GraphQLError) as excinfo:
        ext.resolve(next_fn, None, info)
    assert excinfo.value.extensions == {"code": "UNAUTHENTICATED"}
    next_fn.assert_not_called()


def test_requires_authentication_allow_lists_login() -> None:
    ext = RequiresAuthentication()
    info = _info(
        field_name="login",
        parent_type_name="Mutation",
        is_root=True,
        current_user=None,
    )
    next_fn = MagicMock(return_value="ok")
    ext.resolve(next_fn, None, info)
    next_fn.assert_called_once()


def test_requires_authentication_allow_lists_current_user() -> None:
    ext = RequiresAuthentication()
    info = _info(
        field_name="currentUser",
        parent_type_name="Query",
        is_root=True,
        current_user=None,
    )
    next_fn = MagicMock(return_value="ok")
    ext.resolve(next_fn, None, info)
    next_fn.assert_called_once()


def test_requires_authentication_allow_lists_introspection() -> None:
    ext = RequiresAuthentication()
    info = _info(
        field_name="__schema",
        parent_type_name="Query",
        is_root=True,
        current_user=None,
    )
    next_fn = MagicMock(return_value="ok")
    ext.resolve(next_fn, None, info)
    next_fn.assert_called_once()


def test_requires_authentication_does_not_re_check_nested_fields() -> None:
    """Once the root field passed, nested resolvers are not re-checked."""
    ext = RequiresAuthentication()
    info = _info(
        field_name="someNestedField",
        parent_type_name="SomeNestedType",
        is_root=False,
        current_user=None,
    )
    next_fn = MagicMock(return_value="ok")
    ext.resolve(next_fn, None, info)
    next_fn.assert_called_once()


# ---------------------------------------------------------------------------
# RequiresRole
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("caller_role", "required", "expected"),
    [
        (Role.READ_ONLY, Role.READ_ONLY, True),
        (Role.READ_ONLY, Role.READ_WRITE, False),
        (Role.READ_ONLY, Role.ADMIN, False),
        (Role.READ_WRITE, Role.READ_ONLY, True),
        (Role.READ_WRITE, Role.READ_WRITE, True),
        (Role.READ_WRITE, Role.ADMIN, False),
        (Role.ADMIN, Role.READ_ONLY, True),
        (Role.ADMIN, Role.READ_WRITE, True),
        (Role.ADMIN, Role.ADMIN, True),
    ],
)
def test_requires_role_compares_effective_to_required(
    caller_role: Role, required: Role, expected: bool
) -> None:
    permission = RequiresRole(required)
    info = _info(
        field_name="createCluster",
        parent_type_name="Mutation",
        is_root=True,
        current_user=_user(caller_role),
    )
    assert permission.has_permission(None, info) is expected


def test_requires_role_rejects_unauthenticated_with_unauthenticated_code() -> None:
    permission = RequiresRole(Role.ADMIN)
    info = _info(
        field_name="createCluster",
        parent_type_name="Mutation",
        is_root=True,
        current_user=None,
    )
    assert permission.has_permission(None, info) is False
    assert permission.error_extensions == {"code": "UNAUTHENTICATED"}
