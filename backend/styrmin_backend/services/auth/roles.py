"""Effective-role computation. See ADR-020.

A user's authorization-relevant role is the max of their direct role
and every group's role. Group membership monotonically elevates —
joining a group cannot reduce a user's access. Empty-groups reduces to
``user.role``; the splat collapses to nothing.
"""

from __future__ import annotations

from styrmin_backend.db.models import Group, Role, User


def effective_role(user: User, *, groups: list[Group] | None = None) -> Role:
    """Compute ``max(user.role, *(g.role for g in groups))``.

    ``groups`` defaults to ``user.groups``. The override is for callers
    that already loaded the membership list and want to avoid a lazy
    relationship hit.
    """
    member_groups = user.groups if groups is None else groups
    return max((user.role, *(g.role for g in member_groups)))
