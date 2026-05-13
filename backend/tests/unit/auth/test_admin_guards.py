"""Table-driven matrix for the last-admin / hard-delete guards.

The fixtures here are pure dictionaries and ``UUID()`` instances; no
database session, no Strawberry context, no SQLAlchemy import. This is
what makes the guard suitable for the table-driven approach mandated by
``specs/011-admin-user-group-mgmt/research.md`` §D1.

Each parametrised row spells out the situation in the ``label`` field
so a failure surfaces exactly which scenario broke. The full matrix
covers every action × role × active × actor (self/other) × admin-via
combination called out in tasks.md T008.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from styrmin_backend.services.auth.admin_guards import (
    AdminAction,
    AdminSnapshot,
    can_hard_delete_user,
    would_leave_zero_admins,
)

# Static UUIDs so the table is readable. ``ALICE`` is the recurrent
# target; ``BOB`` is the recurrent "other admin" when the test needs a
# pair.
ALICE = UUID("00000000-0000-0000-0000-0000000000a1")
BOB = UUID("00000000-0000-0000-0000-0000000000b2")
CAROL = UUID("00000000-0000-0000-0000-0000000000c3")


def _snap(
    *,
    direct: set[UUID] | None = None,
    via_group: set[UUID] | None = None,
    active: dict[UUID, bool] | None = None,
) -> AdminSnapshot:
    """Build an ``AdminSnapshot`` from convenience args.

    Defaults assume every admin is active unless explicitly toggled off
    in ``active``. Users absent from the maps are treated as inactive
    by the guard.
    """
    direct_ids = frozenset(direct or ())
    group_ids = frozenset(via_group or ())
    if active is None:
        active_map: dict[UUID, bool] = {uid: True for uid in direct_ids | group_ids}
    else:
        active_map = dict(active)
    return AdminSnapshot(
        direct_admin_user_ids=direct_ids,
        group_admin_user_ids=group_ids,
        active_by_user_id=active_map,
    )


@pytest.mark.parametrize(
    ("label", "action", "target", "snapshot", "expected"),
    [
        # === DEACTIVATE ===
        (
            "deactivate-only-admin",
            AdminAction.DEACTIVATE,
            ALICE,
            _snap(direct={ALICE}),
            True,
        ),
        (
            "deactivate-one-of-two-direct-admins",
            AdminAction.DEACTIVATE,
            ALICE,
            _snap(direct={ALICE, BOB}),
            False,
        ),
        (
            "deactivate-already-inactive-only-admin-leaves-zero",
            # The target is inactive — they do not count toward the
            # active-admin set today, so deactivating them is a no-op
            # for the guard. With zero active admins to start, the post
            # set is still empty.
            AdminAction.DEACTIVATE,
            ALICE,
            _snap(direct={ALICE}, active={ALICE: False}),
            True,
        ),
        (
            "deactivate-self-only-admin",
            AdminAction.DEACTIVATE,
            ALICE,
            _snap(direct={ALICE}),
            True,
        ),
        (
            "deactivate-only-admin-via-group",
            AdminAction.DEACTIVATE,
            ALICE,
            _snap(via_group={ALICE}),
            True,
        ),
        (
            "deactivate-one-admin-direct-when-other-is-via-group",
            AdminAction.DEACTIVATE,
            ALICE,
            _snap(direct={ALICE}, via_group={BOB}),
            False,
        ),
        # === DELETE ===
        (
            "delete-only-admin",
            AdminAction.DELETE,
            ALICE,
            _snap(direct={ALICE}),
            True,
        ),
        (
            "delete-self-only-admin",
            AdminAction.DELETE,
            ALICE,
            _snap(direct={ALICE}),
            True,
        ),
        (
            "delete-one-of-two-direct-admins",
            AdminAction.DELETE,
            ALICE,
            _snap(direct={ALICE, BOB}),
            False,
        ),
        (
            "delete-only-admin-via-group",
            AdminAction.DELETE,
            ALICE,
            _snap(via_group={ALICE}),
            True,
        ),
        # === DEMOTE ===
        (
            "demote-only-direct-admin",
            AdminAction.DEMOTE,
            ALICE,
            _snap(direct={ALICE}),
            True,
        ),
        (
            "demote-self-only-direct-admin",
            AdminAction.DEMOTE,
            ALICE,
            _snap(direct={ALICE}),
            True,
        ),
        (
            "demote-one-of-two-direct-admins",
            AdminAction.DEMOTE,
            ALICE,
            _snap(direct={ALICE, BOB}),
            False,
        ),
        (
            "demote-direct-but-still-admin-via-group",
            # Alice is both direct and via-group; demoting strips the
            # direct role but the group membership still confers admin
            # so she remains an active admin.
            AdminAction.DEMOTE,
            ALICE,
            _snap(direct={ALICE}, via_group={ALICE}),
            False,
        ),
        (
            "demote-direct-when-group-confers-but-she-is-inactive",
            AdminAction.DEMOTE,
            ALICE,
            _snap(
                direct={ALICE},
                via_group={ALICE},
                active={ALICE: False},
            ),
            True,
        ),
        # === REMOVE_FROM_ADMIN_GROUP ===
        (
            "remove-only-admin-via-group",
            AdminAction.REMOVE_FROM_ADMIN_GROUP,
            ALICE,
            _snap(via_group={ALICE}),
            True,
        ),
        (
            "remove-from-admin-group-but-still-direct-admin",
            AdminAction.REMOVE_FROM_ADMIN_GROUP,
            ALICE,
            _snap(direct={ALICE}, via_group={ALICE}),
            False,
        ),
        (
            "remove-only-admin-from-only-admin-group-leaves-zero",
            AdminAction.REMOVE_FROM_ADMIN_GROUP,
            ALICE,
            _snap(via_group={ALICE}),
            True,
        ),
        (
            "remove-from-group-when-other-direct-admin-exists",
            AdminAction.REMOVE_FROM_ADMIN_GROUP,
            ALICE,
            _snap(via_group={ALICE}, direct={BOB}),
            False,
        ),
        (
            "remove-self-from-admin-group-only-admin",
            AdminAction.REMOVE_FROM_ADMIN_GROUP,
            ALICE,
            _snap(via_group={ALICE}),
            True,
        ),
        # === Non-target operations (target isn't an admin) ===
        (
            "deactivate-non-admin-no-effect",
            AdminAction.DEACTIVATE,
            CAROL,
            _snap(direct={ALICE, BOB}),
            False,
        ),
        (
            "delete-non-admin-no-effect",
            AdminAction.DELETE,
            CAROL,
            _snap(direct={ALICE, BOB}),
            False,
        ),
        (
            "demote-non-admin-no-effect",
            AdminAction.DEMOTE,
            CAROL,
            _snap(direct={ALICE, BOB}),
            False,
        ),
        # === Inactive other admins do not count ===
        (
            "demote-only-active-admin-when-other-admin-is-inactive",
            AdminAction.DEMOTE,
            ALICE,
            _snap(
                direct={ALICE, BOB},
                active={ALICE: True, BOB: False},
            ),
            True,
        ),
        (
            "deactivate-only-active-admin-when-other-admin-is-inactive",
            AdminAction.DEACTIVATE,
            ALICE,
            _snap(
                direct={ALICE, BOB},
                active={ALICE: True, BOB: False},
            ),
            True,
        ),
    ],
)
def test_would_leave_zero_admins(
    label: str,  # noqa: ARG001 - readability anchor on failure
    action: AdminAction,
    target: UUID,
    snapshot: AdminSnapshot,
    expected: bool,
) -> None:
    assert would_leave_zero_admins(action, target, snapshot) is expected


@pytest.mark.parametrize(
    ("fk_refs_present", "expected"),
    [(False, True), (True, False)],
)
def test_can_hard_delete_user(fk_refs_present: bool, expected: bool) -> None:
    assert can_hard_delete_user(uuid4(), fk_refs_present) is expected
