"""Admin group mutations + listing service.

Implements the group side of the admin user / group management feature
(see ``specs/011-admin-user-group-mgmt``). Mirrors
:mod:`styrmin_backend.services.auth.users` from chunk 5: every mutation
that can affect admin-conferring state assembles an
:class:`AdminSnapshot` under transactional locks (per research.md §D1),
evaluates the pure last-admin guards in
:mod:`styrmin_backend.services.auth.admin_guards`, then performs the
write and commits once.

Audit log (FR-030): every admin mutation emits a single structured
``admin_mutation`` Loguru line **after** the transaction commits. Lines
contain field NAMES only — values are never logged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import select

from styrmin_backend.db.models import (
    Group as GroupModel,
    Role as RoleModel,
    User as UserModel,
    UserGroup,
)
from styrmin_backend.services.auth.admin_guards import (
    AdminAction,
    AdminSnapshot,
    would_leave_zero_admins,
)
from styrmin_backend.services.auth.membership import replace_group_members
from styrmin_backend.services.exceptions import (
    DuplicateGroupNameError,
    GroupNotFoundError,
    LastAdminError,
    UserNotFoundError,
    ValidationError,
)
from styrmin_backend.services.unit_of_work import UnitOfWork

# Group name canonical form: 1..64 chars, ``A-Za-z0-9_-`` only. Group
# names are case-preserved (unlike usernames) — uniqueness is enforced
# verbatim by the DB constraint on ``group.name``.
_GROUP_NAME_REGEX = re.compile(r"^[A-Za-z0-9_-]+$")
_GROUP_NAME_MAX_LEN = 64


# ---------------------------------------------------------------------
# Input DTOs — internal to the service layer. The Strawberry input
# types in api/definitions/user/model.py are converted to these by the
# resolvers so the service signatures stay free of GraphQL imports.
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CreateGroupData:
    name: str
    role: RoleModel
    member_ids: list[UUID] | None = None


@dataclass(frozen=True, slots=True)
class UpdateGroupData:
    name: str | None = None
    role: RoleModel | None = None
    member_ids: list[UUID] | None = None


# ---------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------


def _validate_group_name(raw: str) -> str:
    stripped = raw.strip()
    if not 1 <= len(stripped) <= _GROUP_NAME_MAX_LEN:
        raise ValidationError(f"group name must be 1..{_GROUP_NAME_MAX_LEN} characters")
    if not _GROUP_NAME_REGEX.fullmatch(stripped):
        raise ValidationError("group name may only contain letters, digits, '_', '-'")
    return stripped


# ---------------------------------------------------------------------
# Snapshot assembly — research.md §D1 concurrency strategy
# ---------------------------------------------------------------------


async def _load_admin_snapshot(uow: UnitOfWork) -> AdminSnapshot:
    """Assemble an :class:`AdminSnapshot` under transactional locks.

    Mirrors ``services/auth/users._load_admin_snapshot``: locks every
    admin-conferring row (direct admins + members of admin groups) with
    ``SELECT ... FOR UPDATE`` so concurrent admin-state mutations are
    forced to wait. SQLite ignores the clause — that's fine for the
    unit-test fixtures, concurrency is not exercised there.
    """
    direct_stmt = (
        select(UserModel.id, UserModel.active)
        .where(UserModel.role == RoleModel.ADMIN)
        .with_for_update()
    )
    direct_result = await uow.session.exec(direct_stmt)
    direct_rows = list(direct_result.all())

    group_stmt = (
        select(UserModel.id, UserModel.active)
        .join(UserGroup, UserGroup.user_id == UserModel.id)
        .join(GroupModel, GroupModel.id == UserGroup.group_id)
        .where(GroupModel.role == RoleModel.ADMIN)
        .with_for_update()
    )
    group_result = await uow.session.exec(group_stmt)
    group_rows = list(group_result.all())

    direct_ids: set[UUID] = set()
    group_ids: set[UUID] = set()
    active_by_id: dict[UUID, bool] = {}

    for row in direct_rows:
        uid, active = row
        direct_ids.add(uid)
        active_by_id[uid] = active
    for row in group_rows:
        uid, active = row
        group_ids.add(uid)
        active_by_id.setdefault(uid, active)

    return AdminSnapshot(
        direct_admin_user_ids=frozenset(direct_ids),
        group_admin_user_ids=frozenset(group_ids),
        active_by_user_id=active_by_id,
    )


# ---------------------------------------------------------------------
# Loaders / validators
# ---------------------------------------------------------------------


async def _load_group_with_users(uow: UnitOfWork, group_id: UUID) -> GroupModel:
    """Fetch a group with eager-loaded ``users`` or raise GROUP_NOT_FOUND."""
    result = await uow.session.exec(
        select(GroupModel)
        .where(GroupModel.id == group_id)
        .options(selectinload(GroupModel.users))  # type: ignore[arg-type]
    )
    group = result.first()
    if group is None:
        raise GroupNotFoundError()
    return group


async def _verify_user_ids_exist(uow: UnitOfWork, user_ids: Iterable[UUID]) -> None:
    ids = list({*user_ids})
    if not ids:
        return
    result = await uow.session.exec(
        select(UserModel.id).where(UserModel.id.in_(ids))  # type: ignore[attr-defined]
    )
    found = set(result.all())
    missing = set(ids) - found
    if missing:
        raise UserNotFoundError(
            f"Unknown user id(s): {', '.join(str(i) for i in sorted(missing))}"
        )


async def _existing_member_ids(uow: UnitOfWork, group_id: UUID) -> set[UUID]:
    result = await uow.session.exec(
        select(UserGroup.user_id).where(UserGroup.group_id == group_id)
    )
    return set(result.all())


def _audit_log(
    *,
    action: str,
    actor_user_id: UUID,
    target_group_id: UUID,
    changed_fields: list[str] | None = None,
) -> None:
    """Emit the FR-030 structured audit line.

    Called only after the transaction commits — a rollback must not
    leave a phantom audit entry.
    """
    fields = ",".join(changed_fields) if changed_fields else "-"
    logger.info(
        "admin_mutation actor={} action={} target={} changed_fields={}",
        actor_user_id,
        action,
        target_group_id,
        fields,
    )


# ---------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------


async def create_group(
    uow: UnitOfWork,
    *,
    input: CreateGroupData,
    actor_user_id: UUID,
) -> GroupModel:
    """Insert a new group row + optional initial members in one commit.

    No last-admin risk: ``create_group(role=ADMIN)`` only *adds* admin
    paths, it cannot remove the last admin. Member validation surfaces
    ``USER_NOT_FOUND`` for unknown ids before the INSERT runs.
    """
    name = _validate_group_name(input.name)

    if input.member_ids:
        await _verify_user_ids_exist(uow, input.member_ids)

    group = GroupModel(name=name, role=input.role)
    uow.session.add(group)
    try:
        await uow.session.flush()
    except IntegrityError as exc:
        await uow.session.rollback()
        raise DuplicateGroupNameError(
            f"A group with name {name!r} already exists"
        ) from exc

    if input.member_ids:
        await replace_group_members(uow, group_id=group.id, member_ids=input.member_ids)

    await uow.session.commit()
    group = await _load_group_with_users(uow, group.id)

    fields = ["name", "role"]
    if input.member_ids is not None:
        fields.append("member_ids")
    _audit_log(
        action="create_group",
        actor_user_id=actor_user_id,
        target_group_id=group.id,
        changed_fields=fields,
    )
    return group


async def update_group(
    uow: UnitOfWork,
    *,
    group_id: UUID,
    input: UpdateGroupData,
    actor_user_id: UUID,
) -> GroupModel:
    """Apply a partial update to a group.

    ``role=<lower>`` (when current is ADMIN) and ``member_ids`` changes
    that strip admin-derived memberships trigger a last-admin guard:
    every user that loses their admin-via-this-group path is checked
    with :data:`AdminAction.REMOVE_FROM_ADMIN_GROUP`.
    """
    # Concurrency: when the requested change can affect admin state,
    # load the snapshot under FOR UPDATE before reading the group row.
    will_check_admin = input.role is not None or input.member_ids is not None
    snapshot: AdminSnapshot | None = None
    if will_check_admin:
        snapshot = await _load_admin_snapshot(uow)

    group = await _load_group_with_users(uow, group_id)

    changed_fields: list[str] = []

    if input.name is not None:
        new_name = _validate_group_name(input.name)
        if new_name != group.name:
            group.name = new_name
            changed_fields.append("name")

    # Track whether the group is admin-conferring BEFORE any role change
    # — this is what determines whether membership churn can demote.
    was_admin_group = group.role == RoleModel.ADMIN

    if input.role is not None and input.role != group.role:
        # Demoting an admin-conferring group strips the admin-via-group
        # path for every current member. Check each member who loses
        # their admin path; if any of them are the last admin, reject.
        if was_admin_group and input.role < RoleModel.ADMIN:
            assert snapshot is not None
            current_members = await _existing_member_ids(uow, group.id)
            for member_id in current_members:
                if would_leave_zero_admins(
                    AdminAction.REMOVE_FROM_ADMIN_GROUP, member_id, snapshot
                ):
                    raise LastAdminError(
                        "Cannot demote the last admin's only admin group"
                    )
        group.role = input.role
        changed_fields.append("role")

    if input.member_ids is not None:
        await _verify_user_ids_exist(uow, input.member_ids)
        # Removing a user from an admin-conferring group can strip their
        # admin-via-group conferral. Use the snapshot to confirm each
        # removed user retains at least one admin path.
        #
        # Use the ORIGINAL ``was_admin_group`` flag — even if the role
        # was just demoted in this same mutation, the admin path was
        # still in place at snapshot time. The guard is consistent:
        # both the demotion check above and this check evaluate against
        # the pre-mutation snapshot.
        if was_admin_group:
            assert snapshot is not None
            existing = await _existing_member_ids(uow, group.id)
            new_set = set(input.member_ids)
            removed_member_ids = existing - new_set
            for removed_id in removed_member_ids:
                if would_leave_zero_admins(
                    AdminAction.REMOVE_FROM_ADMIN_GROUP, removed_id, snapshot
                ):
                    raise LastAdminError(
                        "Cannot remove the last admin from their only admin group"
                    )
        added, removed = await replace_group_members(
            uow, group_id=group.id, member_ids=input.member_ids
        )
        if added or removed:
            changed_fields.append("member_ids")

    if not changed_fields:
        await uow.session.commit()
        return await _load_group_with_users(uow, group.id)

    uow.session.add(group)
    try:
        await uow.session.flush()
    except IntegrityError as exc:
        await uow.session.rollback()
        raise DuplicateGroupNameError(
            f"A group with name {group.name!r} already exists"
        ) from exc

    await uow.session.commit()
    group = await _load_group_with_users(uow, group.id)
    _audit_log(
        action="update_group",
        actor_user_id=actor_user_id,
        target_group_id=group.id,
        changed_fields=changed_fields,
    )
    return group


async def delete_group(
    uow: UnitOfWork,
    *,
    group_id: UUID,
    actor_user_id: UUID,
) -> bool:
    """Hard-delete a group.

    Deleting an admin-conferring group strips the admin-via-group path
    for every current member. Each member is checked with
    ``REMOVE_FROM_ADMIN_GROUP``; if any of them is the last active
    admin, the delete is rejected.

    ``user_group`` rows cascade via ``ondelete=CASCADE`` on the link
    table FK.
    """
    snapshot = await _load_admin_snapshot(uow)
    group = await _load_group_with_users(uow, group_id)

    if group.role == RoleModel.ADMIN:
        current_members = await _existing_member_ids(uow, group.id)
        for member_id in current_members:
            if would_leave_zero_admins(
                AdminAction.REMOVE_FROM_ADMIN_GROUP, member_id, snapshot
            ):
                raise LastAdminError("Cannot delete the last admin's only admin group")

    await uow.session.delete(group)
    await uow.session.commit()
    _audit_log(
        action="delete_group",
        actor_user_id=actor_user_id,
        target_group_id=group_id,
        changed_fields=None,
    )
    return True


async def list_groups(
    uow: UnitOfWork,
    *,
    search: str | None = None,
) -> list[GroupModel]:
    """Filtered listing of groups, ordered by name.

    ``search`` is a case-insensitive substring match against ``name``.
    Returns the bare list — no cursor.
    """
    stmt = select(GroupModel)

    if search:
        like = f"%{search.casefold()}%"
        stmt = stmt.where(GroupModel.name.ilike(like))  # type: ignore[attr-defined]

    stmt = stmt.order_by(GroupModel.name)
    result = await uow.session.exec(stmt)
    return list(result.all())


async def get_group(uow: UnitOfWork, *, group_id: UUID) -> GroupModel:
    """Single-group lookup.

    Internal helper for resolvers / SDK paths. Raises
    :class:`GroupNotFoundError` when ``group_id`` is unknown.
    """
    return await _load_group_with_users(uow, group_id)
