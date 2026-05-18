from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

import strawberry
from strawberry.permission import PermissionExtension

from styrmin_backend.api.auth.permissions import IsSelfOrRole
from styrmin_backend.db.models import Group as GroupModel
from styrmin_backend.db.models import Role as RoleModel
from styrmin_backend.db.models import User as UserModel
from styrmin_backend.services.auth.roles import effective_role


@strawberry.enum
class Role(Enum):
    """GraphQL representation of the authorization role. See ADR-017."""

    READ_ONLY = "READ_ONLY"
    READ_WRITE = "READ_WRITE"
    ADMIN = "ADMIN"

    @classmethod
    def from_model(cls, role: RoleModel) -> "Role":
        return cls[role.name]


@strawberry.type
class Group:
    """Authorization group. See ADR-017."""

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


def _self_or_admin() -> PermissionExtension:
    """Sugar — User fields visible to admins or the user reading their own
    record. See ADR-017: the "self" carve-out is required because the
    frontend's role-gated UI needs ``currentUser.effectiveRole``, and
    non-null GraphQL error propagation would otherwise null the whole
    ``currentUser`` and bounce non-admins back to /login.
    """
    return PermissionExtension([IsSelfOrRole(RoleModel.ADMIN)])


@strawberry.type
class User:
    """User account. Public subset = id/username/displayName; the
    administrative subset is gated by ``IsSelfOrRole(ADMIN)`` — admins see
    every user's admin fields, every user sees their own. See ADR-017.
    """

    id: UUID
    username: str
    display_name: str

    # Admin-or-self fields. Source of truth is one type — the GraphQL
    # field-resolution behaviour is the gate.
    role: Role = strawberry.field(extensions=[_self_or_admin()])
    effective_role: Role = strawberry.field(extensions=[_self_or_admin()])
    active: bool = strawberry.field(extensions=[_self_or_admin()])
    groups: list[Group] = strawberry.field(extensions=[_self_or_admin()])
    created_on: datetime | None = strawberry.field(extensions=[_self_or_admin()])
    updated_on: datetime | None = strawberry.field(extensions=[_self_or_admin()])

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


# ---------------------------------------------------------------------
# Admin mutation input types — see specs/011-admin-user-group-mgmt
# (data-model.md, contracts/graphql.md). Validation (length / charset
# / role-enum) is enforced in the service layer; declaring the shapes
# here keeps the GraphQL schema small and the resolver bodies focused
# on dispatch.
# ---------------------------------------------------------------------


@strawberry.input
class CreateUserInput:
    """Payload for ``createUser``. All required fields are non-null."""

    username: str
    password: str
    display_name: str
    role: Role
    # Optional list of group memberships to attach on creation. ``None``
    # and ``[]`` both mean "no groups"; explicit ids are inserted into
    # ``user_group`` in the same transaction as the user row.
    group_ids: list[strawberry.ID] | None = None


@strawberry.input
class UpdateUserInput:
    """Partial-update payload for ``updateUser``.

    Each field is nullable: ``None`` means "leave alone", a present
    non-None value means "apply". ``group_ids`` follows the explicit
    three-state contract from data-model.md (None = leave, [] = clear,
    [...] = replace).

    Note: **username is intentionally absent** — usernames are
    immutable post-create. A client sending ``username`` gets a
    schema-level error from Strawberry, not silent acceptance.
    """

    display_name: str | None = None
    role: Role | None = None
    active: bool | None = None
    group_ids: list[strawberry.ID] | None = None


@strawberry.input
class CreateGroupInput:
    """Payload for ``createGroup``."""

    name: str
    role: Role
    # Optional initial member set. Same semantics as ``group_ids`` on
    # :class:`CreateUserInput`.
    member_ids: list[strawberry.ID] | None = None


@strawberry.input
class UpdateGroupInput:
    """Partial-update payload for ``updateGroup``.

    ``member_ids`` carries the same three-state contract as
    ``UpdateUserInput.group_ids``.
    """

    name: str | None = None
    role: Role | None = None
    member_ids: list[strawberry.ID] | None = None
