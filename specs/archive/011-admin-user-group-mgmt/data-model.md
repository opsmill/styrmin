# Data Model: Admin User & Group Management

**Feature**: 011-admin-user-group-mgmt
**Date**: 2026-05-11

## Existing tables (from #179) — no changes

### `user`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `username` | TEXT | `UNIQUE` (case-folded by server) |
| `password_hash` | TEXT | argon2id |
| `display_name` | TEXT | required |
| `active` | BOOLEAN | default `TRUE` |
| `role` | ENUM `Role` | `READ_ONLY` / `READ_WRITE` / `ADMIN` |
| `created_on` | TIMESTAMPTZ | server-default `now()` |
| `updated_on` | TIMESTAMPTZ | `onupdate=now()` |

Relationships: `users.groups ↔ groups.users` via `user_group`; `users.sessions` via `session.user_id` (`ondelete=CASCADE`).

### `group`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `name` | TEXT | `UNIQUE` |
| `role` | ENUM `Role` | default `READ_ONLY` |
| `created_on`, `updated_on` | TIMESTAMPTZ | as User |

### `user_group` (link table)

| Column | Type | Notes |
|---|---|---|
| `user_id` | UUID | `FK user.id ondelete=CASCADE`, part of composite PK |
| `group_id` | UUID | `FK group.id ondelete=CASCADE`, part of composite PK |

Composite PK `(user_id, group_id)` prevents duplicate memberships.

### `session`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `user_id` | UUID | `FK user.id ondelete=CASCADE` |
| `token_hash` | BYTEA | `UNIQUE` |
| `created_at`, `last_used_at`, `expires_at` | TIMESTAMPTZ | |

### Deployment audit FK (already in #179)

`deployment.created_by_user_id` exists with `FK user.id ondelete=SET NULL`. This feature reuses it without modification.

## New GraphQL input types

These are Python/Strawberry input classes — they do **not** create new DB rows by themselves. They live in `backend/styrmin_backend/api/definitions/user/model.py`.

### `CreateUserInput`

```python
@strawberry.input
class CreateUserInput:
    username: str          # required
    password: str          # required
    display_name: str      # required
    role: Role             # required — no implicit default
    group_ids: list[strawberry.ID] | None = None  # optional; absent and empty both mean "no groups"
```

Validation (server-side, raises `ValidationError`):

- `username`: 1..64 chars, allowed set matches `^[a-z0-9._-]+$` after `.casefold()` (rejects whitespace/`@`/control chars). Uniqueness is enforced by the DB constraint; client sees `DUPLICATE_USERNAME`.
- `password`: server delegates to `hash_password` which enforces argon2 length policy (≥8 chars from #179).
- `display_name`: 1..128 chars.
- `role`: must be one of `READ_ONLY` / `READ_WRITE` / `ADMIN`.
- `group_ids`: every id MUST refer to an existing group; missing id → `GROUP_NOT_FOUND` (this is an admin-only path, leaking existence is acceptable to the admin caller).

### `UpdateUserInput`

```python
@strawberry.input
class UpdateUserInput:
    # Each field is None to mean "leave alone".
    display_name: str | None = None
    role: Role | None = None
    active: bool | None = None
    group_ids: list[strawberry.ID] | None = None   # None = leave; [] = clear; [...] = replace
```

Note: **no `username` field** — username is immutable post-create. A client sending `username` gets a Strawberry schema error (unknown field), not silent acceptance.

### `CreateGroupInput`

```python
@strawberry.input
class CreateGroupInput:
    name: str              # required, unique, 1..64 chars, ^[A-Za-z0-9_-]+$
    role: Role             # required
    member_ids: list[strawberry.ID] | None = None
```

### `UpdateGroupInput`

```python
@strawberry.input
class UpdateGroupInput:
    name: str | None = None            # may rename; uniqueness enforced
    role: Role | None = None
    member_ids: list[strawberry.ID] | None = None  # same semantics as UpdateUserInput.group_ids
```

## Pure-function snapshot used by the last-admin guard

```python
@dataclass(frozen=True, slots=True)
class AdminSnapshot:
    direct_admin_user_ids: frozenset[UUID]
    group_admin_user_ids: frozenset[UUID]       # users admin only via group membership
    active_by_user_id: Mapping[UUID, bool]      # at least target + acting user; full set acceptable
```

`AdminSnapshot` is assembled by the service-layer wrapper in a single read:

```sql
SELECT u.id, u.role, u.active,
       BOOL_OR(g.role = 'ADMIN') AS has_admin_group
FROM "user" u
LEFT JOIN user_group ug ON ug.user_id = u.id
LEFT JOIN "group" g ON g.id = ug.group_id
WHERE u.active = TRUE
GROUP BY u.id;
```

Effective admins = `{u.id : u.role = ADMIN OR has_admin_group}` filtered by `active = TRUE`. The function then evaluates whether removing the target from that set under the proposed `action` leaves it empty.

## Field-level lifecycle behavior

### Session lifecycle hooks (this feature adds three triggers)

- `resetUserPassword(userId, newPassword)` → DELETE all sessions WHERE `user_id = userId`. **All target sessions.**
- `updateUser(input.active = False)` → DELETE all sessions WHERE `user_id = id`. **All target sessions, in the same transaction as the active flag flip.**
- `changePassword(...)` (existing in #179 — unchanged) → DELETE sessions WHERE `user_id = self AND id != calling_session_id`. **All caller's *other* sessions; calling session preserved.**

### Hard-delete preconditions

`deleteUser(id)`:

1. Check `can_hard_delete_user(id, fk_refs_present=any_deployments_or_other_refs(id))`. If false → `USER_HAS_REFERENCES`.
2. Check last-admin guard with `action=DELETE`. If `would_leave_zero_admins(...)` → `LAST_ADMIN`.
3. Delete the row. Sessions cascade via `ondelete=CASCADE`. Memberships cascade via `ondelete=CASCADE` on `user_group`.

### Membership replacement (set-semantics)

Used by `updateUser.group_ids` and `updateGroup.member_ids`:

```python
existing: set[UUID] = ...
new: set[UUID] = set(provided_ids)
to_add = new - existing
to_remove = existing - new
# INSERT to_add rows, DELETE to_remove rows. Both empty → no-op (no statements).
```

No statements issued in the no-change case (verified by an SQL-statement-count assertion in the unit test).

## State invariants (asserted by tests)

| Invariant | Where asserted |
|---|---|
| Hard-delete is never allowed when `deployment.created_by_user_id == user.id` | functional test `test_delete_user_blocked_by_fk` |
| `active=False` invalidates all sessions of the target in the same transaction | functional test `test_deactivate_invalidates_sessions` |
| `resetUserPassword` invalidates all target sessions | functional test `test_reset_password_invalidates_all_sessions` |
| Last-admin guard rejects: deactivate-only-admin, delete-only-admin, demote-only-admin, remove-only-admin-from-only-admin-group, self-demote, self-deactivate, self-delete | unit test `test_admin_guards.py::test_would_leave_zero_admins` (table-driven, role × active × actor=self/other × admin-via-group/admin-direct) |
| `username` is canonical-folded server-side | functional test `test_create_user_canonicalizes_username` |
| Duplicate username surfaces `DUPLICATE_USERNAME` | functional test `test_create_user_duplicate_returns_structured_error` |
| Membership no-op produces zero INSERT/DELETE | unit test `test_membership.py::test_replace_user_groups_noop` |
| `groupIds = []` on update clears all memberships | unit test `test_membership.py::test_replace_user_groups_clear_all` |

## New structured error codes

Defined in `backend/styrmin_backend/services/exceptions.py`:

| Code | Class | Surfaced by |
|---|---|---|
| `USER_NOT_FOUND` | `UserNotFoundError` | `updateUser`, `resetUserPassword`, `deleteUser` when id unknown |
| `GROUP_NOT_FOUND` | `GroupNotFoundError` | mutation with unknown `group_id` / `member_id` |
| `DUPLICATE_USERNAME` | `DuplicateUsernameError` | `createUser` on unique-constraint violation |
| `DUPLICATE_GROUP_NAME` | `DuplicateGroupNameError` | `createGroup` / `updateGroup` rename |
| `LAST_ADMIN` | `LastAdminError` | any operation that would leave zero active admins |
| `USER_HAS_REFERENCES` | `UserHasReferencesError` | `deleteUser` when FK references exist |
