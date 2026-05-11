"""Set-semantics membership replacement for users ↔ groups.

Both functions diff the existing membership against the requested set
and issue only the INSERT / DELETE statements needed to reach the new
state. The no-change case is observable: zero statements are emitted,
which the unit test asserts via SQLAlchemy's ``before_execute`` event.

Callers MUST run these inside an open ``UnitOfWork`` transaction. The
helpers do NOT commit — that is the service-layer wrapper's job, so the
whole admin mutation (write + membership replace + session cleanup)
commits atomically per ``research.md`` §D15.

See ``specs/011-admin-user-group-mgmt/research.md`` §D2.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete
from sqlmodel import select

from styrmin_backend.db.models import UserGroup
from styrmin_backend.services.unit_of_work import UnitOfWork


async def _existing_groups_for_user(uow: UnitOfWork, user_id: UUID) -> set[UUID]:
    """Return the user's current ``group_id`` set."""
    result = await uow.session.exec(
        select(UserGroup.group_id).where(UserGroup.user_id == user_id)
    )
    return set(result.all())


async def _existing_members_for_group(uow: UnitOfWork, group_id: UUID) -> set[UUID]:
    """Return the group's current ``user_id`` set."""
    result = await uow.session.exec(
        select(UserGroup.user_id).where(UserGroup.group_id == group_id)
    )
    return set(result.all())


async def replace_user_groups(
    uow: UnitOfWork,
    *,
    user_id: UUID,
    group_ids: list[UUID],
) -> tuple[int, int]:
    """Make the user's group memberships exactly equal to ``group_ids``.

    Returns ``(added, removed)``. When the requested set equals the
    existing set this is a strict no-op: zero INSERTs and zero DELETEs
    are issued and ``(0, 0)`` is returned. Duplicate ids in the input
    are coalesced by the ``set`` conversion.
    """
    existing = await _existing_groups_for_user(uow, user_id)
    requested = set(group_ids)
    to_add = requested - existing
    to_remove = existing - requested

    # Short-circuit so the no-change path issues *no* SQL — the unit
    # test asserts this via a statement counter, and any spurious query
    # here (even an empty INSERT) would fail it.
    if not to_add and not to_remove:
        return (0, 0)

    for group_id in to_add:
        uow.session.add(UserGroup(user_id=user_id, group_id=group_id))

    if to_remove:
        await uow.session.exec(
            delete(UserGroup)
            .where(UserGroup.user_id == user_id)
            .where(UserGroup.group_id.in_(to_remove))  # type: ignore[attr-defined]
        )

    # Flush so the INSERTs/DELETEs hit the connection within this
    # transaction; the caller commits.
    await uow.session.flush()
    return (len(to_add), len(to_remove))


async def replace_group_members(
    uow: UnitOfWork,
    *,
    group_id: UUID,
    member_ids: list[UUID],
) -> tuple[int, int]:
    """Make the group's members exactly equal to ``member_ids``.

    Returns ``(added, removed)``. Symmetric to
    :func:`replace_user_groups`. Same no-op contract: zero statements
    when the existing set equals the requested set.
    """
    existing = await _existing_members_for_group(uow, group_id)
    requested = set(member_ids)
    to_add = requested - existing
    to_remove = existing - requested

    if not to_add and not to_remove:
        return (0, 0)

    for user_id in to_add:
        uow.session.add(UserGroup(user_id=user_id, group_id=group_id))

    if to_remove:
        await uow.session.exec(
            delete(UserGroup)
            .where(UserGroup.group_id == group_id)
            .where(UserGroup.user_id.in_(to_remove))  # type: ignore[attr-defined]
        )

    await uow.session.flush()
    return (len(to_add), len(to_remove))
