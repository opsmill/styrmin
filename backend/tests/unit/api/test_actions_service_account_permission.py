"""``IsActionsServiceAccount``, the ``recordStep`` gate and the ``startedByStepId`` gate (spec 019, research D14)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import strawberry
from strawberry.schema.config import StrawberryConfig
from graphql import GraphQLError
from strawberry.permission import PermissionExtension

from styrmin_backend.api.auth.permissions import (
    IsActionsServiceAccount,
    RequiresRole,
    StartedByStepRequiresActionsServiceAccount,
)
from styrmin_backend.api.scalars import SCALAR_MAP
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


def _mutation_extension(name: str) -> PermissionExtension:
    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        config=StrawberryConfig(scalar_map=SCALAR_MAP),
    )
    field = schema._schema.type_map["Mutation"].fields[name]
    definition = field.extensions["strawberry-definition"]
    extensions = [
        ext for ext in definition.extensions if isinstance(ext, PermissionExtension)
    ]
    assert len(extensions) == 1
    return extensions[0]


def _record_step_extension() -> PermissionExtension:
    return _mutation_extension("recordStep")


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


# The startedByStepId gate ------------------------------------------------

STARTING_MUTATIONS = ["stopComponents", "startComponents", "updateDeploymentVersion"]
STEP_ID = uuid4()


@pytest.mark.parametrize("role", [Role.READ_ONLY, Role.READ_WRITE, Role.ADMIN])
def test_started_by_step_is_refused_from_every_person(role: Role) -> None:
    permission = StartedByStepRequiresActionsServiceAccount()

    assert not permission.has_permission(
        None, _info(_user(role)), started_by_step_id=STEP_ID
    )


def test_started_by_step_is_permitted_from_the_actions_account() -> None:
    permission = StartedByStepRequiresActionsServiceAccount()

    assert permission.has_permission(
        None, _info(_actions_account()), started_by_step_id=STEP_ID
    )


@pytest.mark.parametrize("arguments", [{}, {"started_by_step_id": None}])
def test_a_call_without_a_started_by_step_is_permitted(arguments: dict) -> None:
    permission = StartedByStepRequiresActionsServiceAccount()

    assert permission.has_permission(None, _info(_user(Role.READ_WRITE)), **arguments)


def test_started_by_step_refusal_is_forbidden() -> None:
    with pytest.raises(GraphQLError) as excinfo:
        StartedByStepRequiresActionsServiceAccount().on_unauthorized()

    assert excinfo.value.extensions == {"code": "FORBIDDEN"}
    assert excinfo.value.message == (
        "Only the actions service account can set startedByStepId"
    )


@pytest.mark.parametrize("name", STARTING_MUTATIONS)
def test_starting_mutation_requires_read_write_then_the_started_by_step_gate(
    name: str,
) -> None:
    permissions = _mutation_extension(name).permissions

    assert [type(permission) for permission in permissions] == [
        RequiresRole,
        StartedByStepRequiresActionsServiceAccount,
    ]
    assert isinstance(permissions[0], RequiresRole)
    assert permissions[0].required_role == Role.READ_WRITE


@pytest.mark.parametrize("name", STARTING_MUTATIONS)
@pytest.mark.parametrize("role", [Role.READ_WRITE, Role.ADMIN])
async def test_starting_mutation_with_a_step_is_forbidden_for_a_person(
    name: str, role: Role
) -> None:
    resolver = AsyncMock()

    with pytest.raises(GraphQLError) as excinfo:
        await _mutation_extension(name).resolve_async(
            resolver, None, _info(_user(role)), started_by_step_id=STEP_ID
        )

    assert excinfo.value.extensions == {"code": "FORBIDDEN"}
    resolver.assert_not_awaited()


@pytest.mark.parametrize("name", STARTING_MUTATIONS)
@pytest.mark.parametrize(
    ("user", "arguments"),
    [
        (_user(Role.READ_WRITE), {"started_by_step_id": None}),
        (_actions_account(), {"started_by_step_id": STEP_ID}),
    ],
    ids=["person-without-step", "actions-account-with-step"],
)
async def test_starting_mutation_reaches_the_resolver(
    name: str, user: User, arguments: dict
) -> None:
    resolver = AsyncMock(return_value="task")

    result = await _mutation_extension(name).resolve_async(
        resolver, None, _info(user), **arguments
    )

    assert result == "task"
    resolver.assert_awaited_once()
