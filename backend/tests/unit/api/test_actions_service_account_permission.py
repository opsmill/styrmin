"""``IsActionsServiceAccount`` and the ``recordStep`` gate (spec 019, research D14)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import strawberry
from graphql import GraphQLError
from strawberry.permission import PermissionExtension

from styrmin_backend.api.auth.permissions import IsActionsServiceAccount, RequiresRole
from styrmin_backend.api.schema.mutation import Mutation
from styrmin_backend.api.schema.query import Query
from styrmin_backend.db.models import Role, User
from styrmin_backend.services.auth.bootstrap import ACTIONS_SERVICE_ACCOUNT_USERNAME


def _user(role: Role, username: str = "person") -> User:
    user = User(
        id=uuid4(),
        username=username,
        password_hash="not-a-hash",
        display_name=username,
        active=True,
        role=role,
    )
    user.groups = []
    return user


def _actions_account(role: Role = Role.READ_WRITE) -> User:
    return _user(role, ACTIONS_SERVICE_ACCOUNT_USERNAME)


def _info(current_user: User | None) -> Any:
    return SimpleNamespace(context={"current_user": current_user})


def test_actions_account_is_permitted() -> None:
    assert IsActionsServiceAccount().has_permission(None, _info(_actions_account()))


@pytest.mark.parametrize("role", [Role.READ_ONLY, Role.READ_WRITE, Role.ADMIN])
def test_every_person_is_refused(role: Role) -> None:
    assert not IsActionsServiceAccount().has_permission(None, _info(_user(role)))


def test_a_caller_without_a_user_is_refused() -> None:
    assert not IsActionsServiceAccount().has_permission(None, _info(None))
    assert not IsActionsServiceAccount().has_permission(
        None, SimpleNamespace(context=None)
    )


def test_refusal_is_forbidden() -> None:
    permission = IsActionsServiceAccount()

    with pytest.raises(GraphQLError) as excinfo:
        permission.on_unauthorized()

    assert excinfo.value.extensions == {"code": "FORBIDDEN"}


# The recordStep gate ------------------------------------------------------


def _record_step_extension() -> PermissionExtension:
    schema = strawberry.Schema(query=Query, mutation=Mutation)
    field = schema._schema.type_map["Mutation"].fields["recordStep"]
    definition = field.extensions["strawberry-definition"]
    extensions = [
        ext for ext in definition.extensions if isinstance(ext, PermissionExtension)
    ]
    assert len(extensions) == 1
    return extensions[0]


def test_record_step_requires_read_write_then_the_actions_account() -> None:
    permissions = _record_step_extension().permissions

    assert [type(permission) for permission in permissions] == [
        RequiresRole,
        IsActionsServiceAccount,
    ]
    assert isinstance(permissions[0], RequiresRole)
    assert permissions[0].required_role == Role.READ_WRITE


async def test_record_step_reaches_the_resolver_for_the_actions_account() -> None:
    resolver = AsyncMock(return_value="step")

    result = await _record_step_extension().resolve_async(
        resolver, None, _info(_actions_account())
    )

    assert result == "step"
    resolver.assert_awaited_once()


@pytest.mark.parametrize(
    "user",
    [
        _user(Role.ADMIN),
        _user(Role.READ_WRITE),
        _user(Role.READ_ONLY),
        _actions_account(Role.READ_ONLY),
    ],
    ids=["admin", "read-write", "read-only", "actions-account-read-only"],
)
async def test_record_step_is_forbidden_for_everyone_else(user: User) -> None:
    resolver = AsyncMock()

    with pytest.raises(GraphQLError) as excinfo:
        await _record_step_extension().resolve_async(resolver, None, _info(user))

    assert excinfo.value.extensions == {"code": "FORBIDDEN"}
    resolver.assert_not_awaited()
