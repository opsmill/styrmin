from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

import strawberry
from strawberry.permission import PermissionExtension

from styrmin_backend.api.auth.permissions import RequiresRole
from styrmin_backend.db.models import Group as GroupModel
from styrmin_backend.db.models import Role as RoleModel
from styrmin_backend.db.models import User as UserModel
from styrmin_backend.services.auth.roles import effective_role


@strawberry.enum
class Role(Enum):
    """GraphQL representation of the authorization role. See ADR-020."""

    READ_ONLY = "READ_ONLY"
    READ_WRITE = "READ_WRITE"
    ADMIN = "ADMIN"

    @classmethod
    def from_model(cls, role: RoleModel) -> "Role":
        return cls[role.name]


@strawberry.type
class Group:
    """Authorization group. See ADR-020."""

    id: UUID
    name: str
    role: Role

    @classmethod
    def from_instance(cls, instance: GroupModel) -> "Group":
        return cls(
            id=instance.id,
            name=instance.name,
            role=Role.from_model(instance.role),
        )


def _admin_only() -> PermissionExtension:
    """Sugar — User fields gated to admins. See ADR-020."""
    return PermissionExtension([RequiresRole(RoleModel.ADMIN)])


@strawberry.type
class User:
    """User account. Public subset = id/username/displayName; admin-only
    subset gated via per-field RequiresRole(ADMIN). See ADR-020.
    """

    id: UUID
    username: str
    display_name: str

    # Admin-only fields. Source of truth is one type — the GraphQL
    # field-resolution behaviour is the gate.
    role: Role = strawberry.field(extensions=[_admin_only()])
    effective_role: Role = strawberry.field(extensions=[_admin_only()])
    active: bool = strawberry.field(extensions=[_admin_only()])
    groups: list[Group] = strawberry.field(extensions=[_admin_only()])
    created_on: datetime | None = strawberry.field(extensions=[_admin_only()])
    updated_on: datetime | None = strawberry.field(extensions=[_admin_only()])

    @classmethod
    def from_instance(cls, instance: UserModel) -> "User":
        # Materialise group memberships eagerly so the computed
        # ``effective_role`` is consistent with ``groups`` in the same
        # response. The admin-only field gate prevents leaking either to
        # non-admins; the values are still safe to compute here because
        # the values themselves are not the secret — visibility is.
        member_groups = list(instance.groups) if instance.groups is not None else []
        return cls(
            id=instance.id,
            username=instance.username,
            display_name=instance.display_name,
            role=Role.from_model(instance.role),
            effective_role=Role.from_model(
                effective_role(instance, groups=member_groups)
            ),
            active=instance.active,
            groups=[Group.from_instance(g) for g in member_groups],
            created_on=instance.created_on,
            updated_on=instance.updated_on,
        )


@strawberry.type
class LoginResult:
    token: str
    user: User
