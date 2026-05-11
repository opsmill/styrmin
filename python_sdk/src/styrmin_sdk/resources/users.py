"""User resource: admin-only user lifecycle operations.

See specs/011-admin-user-group-mgmt/contracts/sdk.md. Every method here
maps to one named GraphQL operation under ``styrmin_sdk/graphql/``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from styrmin_sdk._queries import load_query
from styrmin_sdk.exceptions import ResourceNotFoundError
from styrmin_sdk.graphql._generated.create_user import (
    CreateUser,
    CreateUserCreateUser,
)
from styrmin_sdk.graphql._generated.delete_user import DeleteUser
from styrmin_sdk.graphql._generated.get_user import GetUser, GetUserUsers
from styrmin_sdk.graphql._generated.list_users import ListUsers, ListUsersUsers
from styrmin_sdk.graphql._generated.reset_user_password import ResetUserPassword
from styrmin_sdk.graphql._generated.update_user import (
    UpdateUser,
    UpdateUserUpdateUser,
)
from styrmin_sdk.resources._base import BaseResource

if TYPE_CHECKING:
    from styrmin_sdk.graphql._generated.enums import Role


class UserResource(BaseResource):
    """Admin-only user management.

    Every method requires the caller's effective role to be ``ADMIN``;
    non-admin callers receive ``FORBIDDEN`` (raised as
    :class:`styrmin_sdk.exceptions.StyrminAuthorizationError`).
    """

    async def create(
        self,
        *,
        username: str,
        password: str,
        display_name: str,
        role: Role,
        group_ids: list[UUID] | None = None,
    ) -> CreateUserCreateUser:
        """Create a new user. Admin only.

        Error ``extensions.code`` mapped via ``_check_graphql_errors`` to the
        SDK exception hierarchy; the underlying server codes include
        ``DUPLICATE_USERNAME``, ``GROUP_NOT_FOUND``, ``VALIDATION``, and
        ``FORBIDDEN``.
        """
        input_payload: dict[str, Any] = {
            "username": username,
            "password": password,
            "displayName": display_name,
            "role": role.value,
        }
        if group_ids is not None:
            input_payload["groupIds"] = [str(gid) for gid in group_ids]

        result = await self._transport.execute(
            load_query("create_user"),
            {"input": input_payload},
        )
        self._check_graphql_errors(result)
        return self._parse(CreateUser, result["data"], "create_user", CreateUserCreateUser)

    async def update(
        self,
        user_id: str | UUID,
        *,
        display_name: str | None = None,
        role: Role | None = None,
        active: bool | None = None,
        group_ids: list[UUID] | None = None,
    ) -> UpdateUserUpdateUser:
        """Partial update with set-semantics on ``group_ids``.

        ``group_ids`` semantics: ``None`` leaves memberships unchanged,
        ``[]`` clears them, and any other list replaces the full set.

        Server-side ``extensions.code`` values surfaced via the SDK error
        hierarchy include ``USER_NOT_FOUND``, ``GROUP_NOT_FOUND``,
        ``LAST_ADMIN``, ``VALIDATION``, and ``FORBIDDEN``.
        """
        input_payload: dict[str, Any] = {}
        if display_name is not None:
            input_payload["displayName"] = display_name
        if role is not None:
            input_payload["role"] = role.value
        if active is not None:
            input_payload["active"] = active
        if group_ids is not None:
            input_payload["groupIds"] = [str(gid) for gid in group_ids]

        result = await self._transport.execute(
            load_query("update_user"),
            {"id": str(user_id), "input": input_payload},
        )
        self._check_graphql_errors(result)
        return self._parse(UpdateUser, result["data"], "update_user", UpdateUserUpdateUser)

    async def reset_password(self, user_id: str | UUID, new_password: str) -> bool:
        """Reset another user's password. Invalidates all of that user's sessions.

        Server-side ``extensions.code`` values: ``USER_NOT_FOUND``,
        ``VALIDATION``, ``FORBIDDEN``.
        """
        result = await self._transport.execute(
            load_query("reset_user_password"),
            {"userId": str(user_id), "newPassword": new_password},
        )
        self._check_graphql_errors(result)
        validated = ResetUserPassword.model_validate(result["data"])
        return validated.reset_user_password

    async def delete(self, user_id: str | UUID) -> bool:
        """Hard-delete a user. Rejected when FK references exist or zero-admins would result.

        Server-side ``extensions.code`` values: ``USER_NOT_FOUND``,
        ``USER_HAS_REFERENCES``, ``LAST_ADMIN``, ``FORBIDDEN``.
        """
        result = await self._transport.execute(
            load_query("delete_user"),
            {"id": str(user_id)},
        )
        self._check_graphql_errors(result)
        validated = DeleteUser.model_validate(result["data"])
        return validated.delete_user

    async def list(
        self,
        *,
        active: bool | None = None,
        role: Role | None = None,
        search: str | None = None,
    ) -> list[ListUsersUsers]:
        """List users with optional filters. Bare list, no pagination."""
        variables: dict[str, Any] = {}
        if active is not None:
            variables["active"] = active
        if role is not None:
            variables["role"] = role.value
        if search is not None:
            variables["search"] = search

        result = await self._transport.execute(load_query("list_users"), variables)
        self._check_graphql_errors(result)
        data = ListUsers.model_validate(result["data"])
        return data.users or []

    async def get(self, user_id: str | UUID) -> GetUserUsers:
        """Fetch a single user by id.

        The backend Query type does not expose a single-user field, so
        the SDK fetches the admin-only ``users`` list and selects the
        matching row. Raises :class:`ResourceNotFoundError` (code
        ``USER_NOT_FOUND``) if no user matches.
        """
        result = await self._transport.execute(load_query("get_user"))
        self._check_graphql_errors(result)
        data = GetUser.model_validate(result["data"])
        target = str(user_id)
        for user in data.users:
            if str(user.id) == target:
                return user
        raise ResourceNotFoundError(f"User {target} not found", "USER_NOT_FOUND")
