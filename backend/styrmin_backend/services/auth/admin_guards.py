"""Pure-function guards for last-admin and hard-delete preconditions.

This module is deliberately database-free: callers assemble an
:class:`AdminSnapshot` from the repository under transactional locks (see
``research.md`` §D1) and pass it in. That keeps the guard logic
table-driven testable without any database fixtures and keeps the
repository layer free of authorization semantics.

The guards answer a single question per call:

* :func:`would_leave_zero_admins` — would performing ``action`` against
  ``target_user_id`` drop the count of active *effective* admins to zero?
* :func:`can_hard_delete_user` — is hard-deleting ``user_id`` allowed
  given the FK-reference state captured in ``fk_refs_present``?

Service-layer callers translate a ``True`` from the first or ``False``
from the second into the appropriate :class:`ServiceError` subclass
(``LastAdminError`` / ``UserHasReferencesError``). The guards never
raise.

See ``specs/011-admin-user-group-mgmt/data-model.md`` for the snapshot
shape and ``research.md`` §D1 for the concurrency strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping
from uuid import UUID


class AdminAction(Enum):
    """The kind of mutation being proposed against ``target_user_id``.

    Each variant represents a distinct admin-state transition the guard
    must reason about. The enum keeps the call sites self-documenting
    and lets the matrix in ``would_leave_zero_admins`` be exhaustive.
    """

    # Setting ``user.active = False`` on the target.
    DEACTIVATE = "DEACTIVATE"
    # Hard-deleting the target row.
    DELETE = "DELETE"
    # Lowering ``user.role`` below ADMIN.
    DEMOTE = "DEMOTE"
    # Removing the target from an admin-conferring group (or removing
    # the admin role from a group they belong to, or deleting that
    # group). Modelled as a single action because all three collapse to
    # "the target loses their admin-via-group conferral".
    REMOVE_FROM_ADMIN_GROUP = "REMOVE_FROM_ADMIN_GROUP"


@dataclass(frozen=True, slots=True)
class AdminSnapshot:
    """Minimal view of admin-conferring state at the moment of the request.

    All sets contain user ids; ``direct_admin_user_ids`` and
    ``group_admin_user_ids`` are not required to be disjoint — a user
    can be a direct admin *and* belong to an admin group. The guard
    treats them as a union for the "is currently admin" check.

    ``active_by_user_id`` MUST cover at least the target and the actor;
    the full active-by-id map is acceptable. Users missing from the map
    are treated as inactive (defensive default: an unknown user cannot
    count toward the active-admin total).
    """

    direct_admin_user_ids: frozenset[UUID]
    group_admin_user_ids: frozenset[UUID]
    active_by_user_id: Mapping[UUID, bool]


def _effective_admin_ids(snapshot: AdminSnapshot) -> frozenset[UUID]:
    """Union of direct-admins and group-admins. See ADR-025 §"Effective role"."""
    return snapshot.direct_admin_user_ids | snapshot.group_admin_user_ids


def _active_effective_admins(snapshot: AdminSnapshot) -> set[UUID]:
    """Currently-active effective-admin ids.

    Users absent from ``active_by_user_id`` are treated as inactive.
    """
    return {
        uid
        for uid in _effective_admin_ids(snapshot)
        if snapshot.active_by_user_id.get(uid, False)
    }


def would_leave_zero_admins(
    action: AdminAction,
    target_user_id: UUID,
    snapshot: AdminSnapshot,
) -> bool:
    """Return ``True`` iff ``action`` against ``target_user_id`` would
    leave zero active effective admins.

    The function does not mutate ``snapshot``; it computes the would-be
    set after the action and asks whether it is empty. The behaviour
    per action:

    * ``DEACTIVATE`` — flip ``active`` of the target to ``False``. The
      target drops out of the active-admin set iff they are currently
      counted there.
    * ``DELETE`` — same outcome as ``DEACTIVATE`` for guard purposes:
      the row stops contributing to the active-admin set.
    * ``DEMOTE`` — strip the target's direct ADMIN role. If they remain
      admin via group membership and that membership is still in the
      snapshot, they stay an active admin; otherwise they drop out.
    * ``REMOVE_FROM_ADMIN_GROUP`` — strip the target's group-derived
      admin conferral. If they retain a direct ADMIN role, they stay
      an active admin; otherwise they drop out.

    The guard is intentionally conservative: if the target is not
    currently counted as an active effective admin, the function still
    walks the math and returns whether the post-action set is empty —
    so callers can dispatch the same check for any action without
    pre-filtering.
    """
    currently_active_admins = _active_effective_admins(snapshot)

    # Compute the would-be active-effective-admin set after `action`.
    if action in (AdminAction.DEACTIVATE, AdminAction.DELETE):
        # The target stops being active. Other users are unaffected.
        post = currently_active_admins - {target_user_id}
    elif action is AdminAction.DEMOTE:
        # Direct ADMIN role is stripped. If the target still confers
        # admin via group membership AND is active, they remain in the
        # set; otherwise they drop out.
        target_active = snapshot.active_by_user_id.get(target_user_id, False)
        still_admin_via_group = (
            target_user_id in snapshot.group_admin_user_ids and target_active
        )
        if still_admin_via_group:
            post = currently_active_admins
        else:
            post = currently_active_admins - {target_user_id}
    elif action is AdminAction.REMOVE_FROM_ADMIN_GROUP:
        # Group-derived admin conferral is stripped. The target
        # remains an active admin only via their direct role.
        target_active = snapshot.active_by_user_id.get(target_user_id, False)
        still_admin_via_direct = (
            target_user_id in snapshot.direct_admin_user_ids and target_active
        )
        if still_admin_via_direct:
            post = currently_active_admins
        else:
            post = currently_active_admins - {target_user_id}
    else:  # pragma: no cover - exhaustive enum
        raise AssertionError(f"Unknown AdminAction: {action!r}")

    return len(post) == 0


def can_hard_delete_user(
    user_id: UUID,  # noqa: ARG001 - signature is part of the public contract
    fk_refs_present: bool,
) -> bool:
    """Return ``True`` iff the user row can be hard-deleted.

    The function is currently a pure pass-through of ``fk_refs_present``
    — hard-delete is allowed iff there are no FK references holding the
    row in place. The ``user_id`` argument is preserved in the signature
    so future preconditions (per-user grace windows, etc.) can be added
    without breaking call sites.
    """
    return not fk_refs_present
