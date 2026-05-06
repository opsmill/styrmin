"""Default-deny GraphQL schema extension. See ADR-020.

Runs before any resolver and rejects unauthenticated requests with the
structured ``UNAUTHENTICATED`` error code, except for the documented
allow-list (``login`` mutation, ``currentUser`` query, introspection,
plus agent-callback entries until service-account auth lands).
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from graphql import GraphQLError, GraphQLResolveInfo
from strawberry.extensions import SchemaExtension

from styrmin_backend.api.auth.allowlist import (
    MUTATION_ALLOW_LIST,
    QUERY_ALLOW_LIST,
)


def _is_root_field(info: GraphQLResolveInfo) -> bool:
    """Top-level field on Query/Mutation/Subscription, not a nested field."""
    return info.path.prev is None


def _is_allow_listed(info: GraphQLResolveInfo) -> bool:
    if info.field_name.startswith("__"):
        return True
    parent_name = info.parent_type.name
    if parent_name == "Mutation":
        return info.field_name in MUTATION_ALLOW_LIST
    if parent_name == "Query":
        return info.field_name in QUERY_ALLOW_LIST
    return False


class RequiresAuthentication(SchemaExtension):
    """Reject unauthenticated requests at root-field resolution time.

    Only the *root* field is inspected — once an authenticated request is
    inside a resolver, nested field resolution does not re-check (the
    parent's resolution already passed the gate). For unauthenticated
    requests, only allow-listed root fields are permitted to resolve.
    """

    def resolve(
        self,
        _next: Callable[..., Any],
        root: Any,
        info: GraphQLResolveInfo,
        *args: str,
        **kwargs: Any,
    ) -> Awaitable[object] | object:
        if _is_root_field(info) and not _is_allow_listed(info):
            context = info.context
            current_user = (
                context.get("current_user") if isinstance(context, dict) else None
            )
            if current_user is None:
                raise GraphQLError(
                    "Authentication is required",
                    extensions={"code": "UNAUTHENTICATED"},
                )
        return _next(root, info, *args, **kwargs)
