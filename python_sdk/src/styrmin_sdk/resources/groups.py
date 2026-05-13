"""Group resource: admin-only group lifecycle operations.

See specs/011-admin-user-group-mgmt/contracts/sdk.md. Every method here
maps to one named GraphQL operation under ``styrmin_sdk/graphql/``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from styrmin_sdk._queries import load_query
from styrmin_sdk.exceptions import ResourceNotFoundError
from styrmin_sdk.graphql._generated.create_group import (
    CreateGroup,
    CreateGroupCreateGroup,
)
from styrmin_sdk.graphql._generated.delete_group import DeleteGroup
from styrmin_sdk.graphql._generated.get_group import GetGroup, GetGroupGroup
from styrmin_sdk.graphql._generated.list_groups import ListGroups, ListGroupsGroups
from styrmin_sdk.graphql._generated.update_group import (
    UpdateGroup,
    UpdateGroupUpdateGroup,
)
from styrmin_sdk.resources._base import BaseResource

if TYPE_CHECKING:
    from styrmin_sdk.graphql._generated.enums import Role


class GroupResource(BaseResource):
    """Admin-only group management.

    Every method requires the caller's effective role to be ``ADMIN``;
    non-admin callers receive ``FORBIDDEN`` (raised as
    :class:`styrmin_sdk.exceptions.StyrminAuthorizationError`).
    """

    async def create(
        self,
        *,
        name: str,
        role: Role,
        member_ids: list[UUID] | None = None,
    ) -> CreateGroupCreateGroup:
        """Create a new group. Admin only.

        Error ``extensions.code`` mapped via ``_check_graphql_errors`` to the
        SDK exception hierarchy; the underlying server codes include
        ``DUPLICATE_GROUP_NAME``, ``USER_NOT_FOUND``, ``VALIDATION``, and
        ``FORBIDDEN``.
        """
        input_payload: dict[str, Any] = {
            "name": name,
            "role": role.value,
        }
        if member_ids is not None:
            input_payload["memberIds"] = [str(mid) for mid in member_ids]

        result = await self._transport.execute(
            load_query("create_group"),
            {"input": input_payload},
        )
        self._check_graphql_errors(result)
        return self._parse(CreateGroup, result["data"], "create_group", CreateGroupCreateGroup)

    async def update(
        self,
        group_id: str | UUID,
        *,
        name: str | None = None,
        role: Role | None = None,
        member_ids: list[UUID] | None = None,
    ) -> UpdateGroupUpdateGroup:
        """Partial update with set-semantics on ``member_ids``.

        ``member_ids`` semantics: ``None`` leaves memberships unchanged,
        ``[]`` clears them, and any other list replaces the full set.

        Server-side ``extensions.code`` values surfaced via the SDK error
        hierarchy include ``GROUP_NOT_FOUND``, ``USER_NOT_FOUND``,
        ``DUPLICATE_GROUP_NAME``, ``LAST_ADMIN``, ``VALIDATION``, and
        ``FORBIDDEN``.
        """
        input_payload: dict[str, Any] = {}
        if name is not None:
            input_payload["name"] = name
        if role is not None:
            input_payload["role"] = role.value
        if member_ids is not None:
            input_payload["memberIds"] = [str(mid) for mid in member_ids]

        result = await self._transport.execute(
            load_query("update_group"),
            {"id": str(group_id), "input": input_payload},
        )
        self._check_graphql_errors(result)
        return self._parse(UpdateGroup, result["data"], "update_group", UpdateGroupUpdateGroup)

    async def delete(self, group_id: str | UUID) -> bool:
        """Hard-delete a group. Rejected when removal would leave zero admins.

        Server-side ``extensions.code`` values: ``GROUP_NOT_FOUND``,
        ``LAST_ADMIN``, ``FORBIDDEN``.
        """
        result = await self._transport.execute(
            load_query("delete_group"),
            {"id": str(group_id)},
        )
        self._check_graphql_errors(result)
        validated = DeleteGroup.model_validate(result["data"])
        return validated.delete_group

    async def list(self, *, search: str | None = None) -> list[ListGroupsGroups]:
        """List groups with optional name search. Bare list, no pagination."""
        variables: dict[str, Any] = {}
        if search is not None:
            variables["search"] = search

        result = await self._transport.execute(load_query("list_groups"), variables)
        self._check_graphql_errors(result)
        data = ListGroups.model_validate(result["data"])
        return data.groups or []

    async def get(self, group_id: str | UUID) -> GetGroupGroup:
        """Fetch a single group by id.

        Calls the server-side ``Query.group(id:)`` resolver — the backend
        does the lookup, so we do not pay the cost of fetching the full
        admin group list and filtering client-side. Raises
        :class:`ResourceNotFoundError` (code ``GROUP_NOT_FOUND``) if no
        group matches; the server surfaces that via ``extensions.code``
        which ``_check_graphql_errors`` maps to the SDK exception. The
        null fallback below defends against a hypothetical schema where
        the resolver returned null instead of erroring.
        """
        target = str(group_id)
        result = await self._transport.execute(load_query("get_group"), {"id": target})
        self._check_graphql_errors(result)
        data = GetGroup.model_validate(result["data"])
        if data.group is None:
            raise ResourceNotFoundError(f"Group {target} not found", "GROUP_NOT_FOUND")
        return data.group
