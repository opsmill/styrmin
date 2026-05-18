"""Unit tests for the effective-role pure function. See ADR-025."""

from __future__ import annotations

from uuid import uuid4

import pytest

from styrmin_backend.db.models import Group, Role, User
from styrmin_backend.services.auth.roles import effective_role


def _user(role: Role) -> User:
    return User(
        id=uuid4(),
        username=f"u-{uuid4().hex[:6]}",
        password_hash="not-a-hash",
        display_name="example",
        active=True,
        role=role,
    )


def _group(role: Role) -> Group:
    return Group(id=uuid4(), name=f"g-{uuid4().hex[:6]}", role=role)


@pytest.mark.parametrize(
    ("user_role", "group_roles", "expected"),
    [
        # Empty groups — falls through to the user's direct role.
        (Role.READ_ONLY, [], Role.READ_ONLY),
        (Role.READ_WRITE, [], Role.READ_WRITE),
        (Role.ADMIN, [], Role.ADMIN),
        # Single group dominates when its role is higher.
        (Role.READ_ONLY, [Role.READ_WRITE], Role.READ_WRITE),
        (Role.READ_ONLY, [Role.ADMIN], Role.ADMIN),
        # User dominates when its role is higher.
        (Role.ADMIN, [Role.READ_ONLY], Role.ADMIN),
        (Role.READ_WRITE, [Role.READ_ONLY], Role.READ_WRITE),
        # Multiple groups — winner is the max across the whole set.
        (Role.READ_ONLY, [Role.READ_WRITE, Role.ADMIN], Role.ADMIN),
        (Role.READ_ONLY, [Role.READ_ONLY, Role.READ_ONLY], Role.READ_ONLY),
        # Equal-role tie — the role itself wins (max is idempotent).
        (Role.READ_WRITE, [Role.READ_WRITE], Role.READ_WRITE),
    ],
)
def test_effective_role_table_driven(
    user_role: Role, group_roles: list[Role], expected: Role
) -> None:
    user = _user(user_role)
    groups = [_group(r) for r in group_roles]
    assert effective_role(user, groups=groups) == expected


def test_effective_role_admin_via_group_on_read_only_user() -> None:
    """ADR-025: groups grant capabilities, never revoke them.

    A READ_ONLY user added to an ADMIN group is effectively an admin.
    This is the load-bearing test that locks in the asymmetry.
    """
    user = _user(Role.READ_ONLY)
    admin_group = _group(Role.ADMIN)
    assert effective_role(user, groups=[admin_group]) == Role.ADMIN


def test_effective_role_groups_default_to_user_groups_attribute() -> None:
    """When ``groups`` arg is omitted, falls through to ``user.groups``.

    The override exists so callers that already loaded the membership
    list can avoid a lazy relationship hit; default behaviour is to read
    the attribute on the User model.
    """
    user = _user(Role.READ_ONLY)
    user.groups = [_group(Role.READ_WRITE)]
    assert effective_role(user) == Role.READ_WRITE
