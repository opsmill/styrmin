"""Admin user mutations + listing service.

Implements the user side of the admin user / group management feature
(see ``specs/011-admin-user-group-mgmt``). Each mutation that can
affect admin-conferring state assembles an :class:`AdminSnapshot`
under transactional locks (per research.md §D1), evaluates the pure
last-admin guards in
:mod:`styrmin_backend.services.auth.admin_guards`, then performs the
write and commits once.

Audit log (FR-030): every admin mutation emits a single structured
``admin_mutation`` Loguru line **after** the transaction commits. Lines
contain field NAMES only — values are never logged, because values
include passwords and PII.

Session invalidation (research.md §D15): ``update_user(active=False)``
and ``reset_user_password`` flush the user-row change first, then call
:func:`delete_all_sessions_for_user` against the same DB session, then
commit once — so a failure in step 2 rolls back the password / active
flip too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import or_, select

from styrmin_backend.db.models import (
    Deployment,
    Group as GroupModel,
    Role as RoleModel,
    Session as SessionModel,
    User as UserModel,
    UserGroup,
)
from styrmin_backend.services.auth.admin_guards import (
    AdminAction,
    AdminSnapshot,
    can_hard_delete_user,
    would_leave_zero_admins,
)
from styrmin_backend.services.auth.bootstrap import ACTIONS_SERVICE_ACCOUNT_USERNAME
from styrmin_backend.services.auth.membership import replace_user_groups
from styrmin_backend.services.auth.password import hash_password
from styrmin_backend.services.auth.session import delete_all_sessions_for_user
from styrmin_backend.services.exceptions import (
    ActionsServiceAccountError,
    DuplicateUsernameError,
    GroupNotFoundError,
    LastAdminError,
    UserHasReferencesError,
    UserNotFoundError,
    ValidationError,
)
from styrmin_backend.services.unit_of_work import UnitOfWork

# Username canonical form: lowercase, 1..64 chars, ``a-z0-9._-`` only.
# Enforced server-side after ``.casefold()`` so the DB always stores the
# canonical form and duplicate detection is case-insensitive.
_USERNAME_REGEX = re.compile(r"^[a-z0-9._-]+$")
_USERNAME_MAX_LEN = 64
_DISPLAY_NAME_MAX_LEN = 128
_GROUP_NAME_MAX_LEN = 64


# ---------------------------------------------------------------------
# Input DTOs — internal to the service layer. The Strawberry input
# types in api/definitions/user/model.py are converted to these by the
# resolvers so the service signatures stay free of GraphQL imports.
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CreateUserData:
    username: str
    password: str
    display_name: str
    role: RoleModel
    group_ids: list[UUID] | None = None


@dataclass(frozen=True, slots=True)
class UpdateUserData:
    display_name: str | None = None
    role: RoleModel | None = None
    active: bool | None = None
    group_ids: list[UUID] | None = None


# ---------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------


def _validate_username(raw: str) -> str:
    """Canonicalise + validate. Returns the casefolded form."""
    canonical = raw.casefold().strip()
    if not 1 <= len(canonical) <= _USERNAME_MAX_LEN:
        raise ValidationError(f"username must be 1..{_USERNAME_MAX_LEN} characters")
    if not _USERNAME_REGEX.fullmatch(canonical):
        raise ValidationError(
            "username may only contain lowercase letters, digits, '.', '_', '-'"
        )
    return canonical


def _validate_display_name(raw: str) -> str:
    stripped = raw.strip()
    if not 1 <= len(stripped) <= _DISPLAY_NAME_MAX_LEN:
        raise ValidationError(
            f"display_name must be 1..{_DISPLAY_NAME_MAX_LEN} characters"
        )
    return stripped


# ---------------------------------------------------------------------
# Snapshot assembly — research.md §D1 concurrency strategy
# ---------------------------------------------------------------------


async def _load_admin_snapshot(uow: UnitOfWork) -> AdminSnapshot:
    """Assemble an :class:`AdminSnapshot` under transactional locks.

    Issues a SELECT ... FOR UPDATE against every active admin-conferring
    row (direct admins + members of admin groups) so a concurrent
    demotion / deactivation is forced to wait. PostgreSQL honours the
    lock under default ``READ COMMITTED``; on SQLite the clause is a
    no-op which is fine for unit-test fixtures (concurrency is not
    exercised there).
    """
    # Direct admins: users with role=ADMIN.
    direct_stmt = (
        select(UserModel.id, UserModel.active)
        .where(UserModel.role == RoleModel.ADMIN)
        .with_for_update()
    )
    direct_result = await uow.session.exec(direct_stmt)
    direct_rows = list(direct_result.all())

    # Admin-via-group: users that belong to any group with role=ADMIN.
    # The join over user_group / group is locked too so removing the
    # admin role from a group / removing the user from the group blocks
    # concurrent mutations.
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
        # Direct + group: keep the strictest "is currently active" view.
        active_by_id.setdefault(uid, active)

    return AdminSnapshot(
        direct_admin_user_ids=frozenset(direct_ids),
        group_admin_user_ids=frozenset(group_ids),
        active_by_user_id=active_by_id,
    )


# ---------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------


async def _load_user_with_groups(uow: UnitOfWork, user_id: UUID) -> UserModel:
    """Fetch a user with eager-loaded ``groups`` or raise USER_NOT_FOUND."""
    result = await uow.session.exec(
        select(UserModel)
        .where(UserModel.id == user_id)
        .options(selectinload(UserModel.groups))  # type: ignore[arg-type]
    )
    user = result.first()
    if user is None:
        raise UserNotFoundError()
    return user


async def _verify_group_ids_exist(uow: UnitOfWork, group_ids: Iterable[UUID]) -> None:
    ids = list({*group_ids})
    if not ids:
        return
    result = await uow.session.exec(
        select(GroupModel.id).where(GroupModel.id.in_(ids))  # type: ignore[attr-defined]
    )
    found = set(result.all())
    missing = set(ids) - found
    if missing:
        raise GroupNotFoundError(
            f"Unknown group id(s): {', '.join(str(i) for i in sorted(missing))}"
        )


def _audit_log(
    *,
    action: str,
    actor_user_id: UUID,
    target_user_id: UUID,
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
        target_user_id,
        fields,
    )


async def create_user(
    uow: UnitOfWork,
    *,
    input: CreateUserData,
    actor_user_id: UUID,
) -> UserModel:
    """Insert a new user row + optional group memberships in one commit."""
    canonical = _validate_username(input.username)
    if canonical == ACTIONS_SERVICE_ACCOUNT_USERNAME:
        raise ActionsServiceAccountError(
            "The username styrmin-actions is reserved for driver actions"
        )
    display_name = _validate_display_name(input.display_name)
    # ``hash_password`` enforces the argon2 length policy and raises
    # ``PasswordPolicyError`` (error_code=VALIDATION_ERROR) on violation.
    password_hash = hash_password(input.password)

    if input.group_ids:
        await _verify_group_ids_exist(uow, input.group_ids)

    user = UserModel(
        username=canonical,
        password_hash=password_hash,
        display_name=display_name,
        active=True,
        role=input.role,
    )
    uow.session.add(user)
    try:
        await uow.session.flush()
    except IntegrityError as exc:
        # Unique-constraint violation on `user.username` is the only
        # path that surfaces here; keep the error message generic so
        # we don't leak constraint internals.
        await uow.session.rollback()
        raise DuplicateUsernameError(
            f"A user with username {canonical!r} already exists"
        ) from exc

    if input.group_ids:
        await replace_user_groups(uow, user_id=user.id, group_ids=input.group_ids)

    await uow.session.commit()
    # Refresh with eager-loaded groups so the resolver can render the
    # full User type without lazy-load hits.
    user = await _load_user_with_groups(uow, user.id)

    fields = ["username", "password", "display_name", "role"]
    if input.group_ids is not None:
        fields.append("group_ids")
    _audit_log(
        action="create_user",
        actor_user_id=actor_user_id,
        target_user_id=user.id,
        changed_fields=fields,
    )
    return user


async def update_user(
    uow: UnitOfWork,
    *,
    user_id: UUID,
    input: UpdateUserData,
    actor_user_id: UUID,
) -> UserModel:
    """Apply a partial update to a user.

    ``role=<lower>`` or ``active=False`` triggers a last-admin guard.
    ``active=False`` also invalidates every session belonging to the
    target in the same transaction (research.md §D15).
    """
    # Concurrency: when the requested change can affect admin state,
    # load the snapshot under FOR UPDATE before reading the user row so
    # the lock surface ordering is stable across concurrent callers.
    will_check_admin = (
        input.role is not None or input.active is False or input.group_ids is not None
    )
    snapshot: AdminSnapshot | None = None
    if will_check_admin:
        snapshot = await _load_admin_snapshot(uow)

    user = await _load_user_with_groups(uow, user_id)

    changed_fields: list[str] = []

    if input.display_name is not None:
        new_display = _validate_display_name(input.display_name)
        if new_display != user.display_name:
            user.display_name = new_display
            changed_fields.append("display_name")

    if input.role is not None and input.role != user.role:
        # Demote check: only fires when moving down from ADMIN.
        if user.role == RoleModel.ADMIN and input.role < RoleModel.ADMIN:
            assert snapshot is not None
            if would_leave_zero_admins(AdminAction.DEMOTE, user.id, snapshot):
                raise LastAdminError("Cannot demote the last active admin")
        user.role = input.role
        changed_fields.append("role")

    deactivating = input.active is False and user.active is True
    if input.active is not None and input.active != user.active:
        if deactivating:
            assert snapshot is not None
            if would_leave_zero_admins(AdminAction.DEACTIVATE, user.id, snapshot):
                raise LastAdminError("Cannot deactivate the last active admin")
        user.active = input.active
        changed_fields.append("active")

    if input.group_ids is not None:
        await _verify_group_ids_exist(uow, input.group_ids)
        # Removing the user from an admin-conferring group might leave
        # zero admins. The pure guard only sees the snapshot, so we
        # evaluate REMOVE_FROM_ADMIN_GROUP if the requested set drops
        # ALL admin-groups the user currently belongs to.
        if snapshot is not None and user.id in snapshot.group_admin_user_ids:
            # Check whether the new group set still contains any admin
            # group; if not, the user loses their admin-via-group
            # conferral.
            new_ids = set(input.group_ids)
            # Look up admin-group ids out of the requested set.
            if new_ids:
                admin_group_result = await uow.session.exec(
                    select(GroupModel.id)
                    .where(GroupModel.id.in_(new_ids))  # type: ignore[attr-defined]
                    .where(GroupModel.role == RoleModel.ADMIN)
                )
                still_admin_group = bool(list(admin_group_result.all()))
            else:
                still_admin_group = False
            if not still_admin_group and would_leave_zero_admins(
                AdminAction.REMOVE_FROM_ADMIN_GROUP, user.id, snapshot
            ):
                raise LastAdminError(
                    "Cannot remove the last admin from their admin group(s)"
                )
        added, removed = await replace_user_groups(
            uow, user_id=user.id, group_ids=input.group_ids
        )
        if added or removed:
            changed_fields.append("group_ids")

    if not changed_fields:
        # Nothing to do — keep the transaction clean and return the
        # row as-is. No audit line: nothing actually changed.
        await uow.session.commit()
        return await _load_user_with_groups(uow, user.id)

    uow.session.add(user)
    await uow.session.flush()

    # Per research.md §D15: write first, then invalidate sessions in
    # the same transaction. If session-delete raises, the active flag
    # / password change rolls back too.
    if deactivating:
        await delete_all_sessions_for_user(uow.session, user.id)

    await uow.session.commit()
    user = await _load_user_with_groups(uow, user.id)
    _audit_log(
        action="update_user",
        actor_user_id=actor_user_id,
        target_user_id=user.id,
        changed_fields=changed_fields,
    )
    return user


async def reset_user_password(
    uow: UnitOfWork,
    *,
    user_id: UUID,
    new_password: str,
    actor_user_id: UUID,
) -> bool:
    """Reset a user's password and invalidate every session they hold.

    Refuses ``styrmin-actions``, so that no person can log in as it (ADR-059).
    """
    user = await _load_user_with_groups(uow, user_id)
    if user.username == ACTIONS_SERVICE_ACCOUNT_USERNAME:
        raise ActionsServiceAccountError(
            "The password of the styrmin-actions user cannot be reset"
        )
    # ``hash_password`` enforces the length policy and raises
    # ``PasswordPolicyError`` (VALIDATION_ERROR) on violation.
    user.password_hash = hash_password(new_password)
    uow.session.add(user)
    await uow.session.flush()
    # Per research.md §D15: same transaction as the password write so
    # a session-delete failure rolls the password back too.
    await delete_all_sessions_for_user(uow.session, user.id)
    await uow.session.commit()
    _audit_log(
        action="reset_user_password",
        actor_user_id=actor_user_id,
        target_user_id=user.id,
        changed_fields=["password"],
    )
    return True


async def _has_deployment_references(uow: UnitOfWork, user_id: UUID) -> bool:
    """Return whether any FK references hold the user row in place.

    ``deployment.created_by_user_id`` is the only NOT-NULL FK to
    ``user.id`` outside the cascading link tables (``user_group``,
    ``session``). If that ever grows, extend this helper and the
    matching test.
    """
    result = await uow.session.exec(
        select(Deployment.id).where(Deployment.created_by_user_id == user_id).limit(1)
    )
    return result.first() is not None


async def delete_user(
    uow: UnitOfWork,
    *,
    user_id: UUID,
    actor_user_id: UUID,
) -> bool:
    """Hard-delete a user.

    Two preconditions: no FK references (``USER_HAS_REFERENCES``) and
    not the last active admin (``LAST_ADMIN``). Sessions and
    user_group rows cascade via ``ondelete=CASCADE``.
    """
    snapshot = await _load_admin_snapshot(uow)
    user = await _load_user_with_groups(uow, user_id)

    fk_refs_present = await _has_deployment_references(uow, user.id)
    if not can_hard_delete_user(user.id, fk_refs_present=fk_refs_present):
        raise UserHasReferencesError(
            "User has foreign-key references and cannot be deleted"
        )

    if would_leave_zero_admins(AdminAction.DELETE, user.id, snapshot):
        raise LastAdminError("Cannot delete the last active admin")

    # Explicitly delete owned sessions first so the ORM observes the
    # rows leaving the session before the cascade fires; without this
    # the relationship's ``cascade="all, delete-orphan"`` warning trips
    # on AsyncSession in some SQLAlchemy configurations.
    session_rows = await uow.session.exec(
        select(SessionModel).where(SessionModel.user_id == user.id)
    )
    for row in session_rows.all():
        await uow.session.delete(row)

    await uow.session.delete(user)
    await uow.session.commit()
    _audit_log(
        action="delete_user",
        actor_user_id=actor_user_id,
        target_user_id=user_id,
        changed_fields=None,
    )
    return True


async def list_users(
    uow: UnitOfWork,
    *,
    active: bool | None = None,
    role: RoleModel | None = None,
    search: str | None = None,
) -> list[UserModel]:
    """Filtered listing of users with eager-loaded ``groups``.

    Per research.md §D16: ``selectinload(User.groups)`` so rendering N
    users with memberships costs 2 queries (users + groups), not N+1.
    """
    stmt = select(UserModel).options(selectinload(UserModel.groups))  # type: ignore[arg-type]

    if active is not None:
        stmt = stmt.where(UserModel.active == active)
    if role is not None:
        stmt = stmt.where(UserModel.role == role)
    if search:
        like = f"%{search.casefold()}%"
        stmt = stmt.where(
            or_(
                UserModel.username.ilike(like),  # type: ignore[attr-defined]
                UserModel.display_name.ilike(like),  # type: ignore[attr-defined]
            )
        )

    stmt = stmt.order_by(UserModel.username)
    result = await uow.session.exec(stmt)
    return list(result.all())


async def get_user(uow: UnitOfWork, *, user_id: UUID) -> UserModel:
    """Single-user lookup with eager-loaded ``groups``.

    Internal helper for resolvers / SDK paths. Raises
    :class:`UserNotFoundError` when ``user_id`` is unknown.
    """
    return await _load_user_with_groups(uow, user_id)
