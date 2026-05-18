"""Per-resolver role permissions. See ADR-025.

A field with no ``RequiresRole`` requires only the authenticated baseline
from ``RequiresAuthentication``. Fields needing READ_WRITE or ADMIN
declare it explicitly with ``PermissionExtension([RequiresRole(...)])``.
"""

from __future__ import annotations

from typing import Any

from strawberry import Info
from strawberry.permission import BasePermission

from styrmin_backend.db.models import Role, User
from styrmin_backend.services.auth.roles import effective_role


class RequiresRole(BasePermission):
    """Reject when ``effective_role(caller) < required_role``.

    The caller is the authenticated user on ``info.context['current_user']``.
    ``RequiresAuthentication`` runs first, so by the time this permission
    fires the user is guaranteed non-None — but we defensively check anyway
    in case a field opts out of the authentication extension while keeping
    a role gate.
    """

    message = "Insufficient permissions"
    error_extensions = {"code": "FORBIDDEN"}

    def __init__(self, role: Role) -> None:
        self.required_role = role

    def has_permission(
        self,
        source: Any,
        info: Info,
        **kwargs: Any,
    ) -> bool:
        del source, kwargs
        context = info.context
        current_user: User | None = (
            context.get("current_user") if isinstance(context, dict) else None
        )
        if current_user is None:
            self.message = "Authentication is required"
            self.error_extensions = {"code": "UNAUTHENTICATED"}
            return False
        return effective_role(current_user) >= self.required_role


class IsSelfOrRole(BasePermission):
    """Permit when the caller is reading their own ``User`` record OR has
    ``effective_role >= required_role``.

    Used on per-field gates of the ``User`` GraphQL type so that a user can
    always see their own ``role`` / ``effectiveRole`` / ``groups`` /
    ``active`` (needed for frontend role gating), while still hiding the
    same fields on *other* users from non-admin callers.

    ``source`` is the parent ``User`` object that Strawberry resolved; for
    ``currentUser`` that's the caller themselves, so the equality check
    short-circuits the role check.
    """

    message = "Insufficient permissions"
    error_extensions = {"code": "FORBIDDEN"}

    def __init__(self, role: Role) -> None:
        self.required_role = role

    def has_permission(
        self,
        source: Any,
        info: Info,
        **kwargs: Any,
    ) -> bool:
        del kwargs
        context = info.context
        current_user: User | None = (
            context.get("current_user") if isinstance(context, dict) else None
        )
        if current_user is None:
            self.message = "Authentication is required"
            self.error_extensions = {"code": "UNAUTHENTICATED"}
            return False
        source_id = getattr(source, "id", None)
        if source_id is not None and source_id == current_user.id:
            return True
        return effective_role(current_user) >= self.required_role
