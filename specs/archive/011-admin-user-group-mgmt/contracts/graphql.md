# Contract: GraphQL — Admin User & Group Management

**Feature**: 011-admin-user-group-mgmt
**Date**: 2026-05-11

This document is the source of truth for the GraphQL schema slice added by this feature. After implementation, `schema.graphql` at the repo root MUST match this contract (verified by `uv run styrmin export graphql-schema schema.graphql` + CI's schema-snapshot check).

## Enums

```graphql
enum Role {
  READ_ONLY
  READ_WRITE
  ADMIN
}
```

(Already exists from #179 — included for context.)

## Types

### `User` (extended with `effectiveRole` already from #179)

The existing `User` type stays as-is. Public subset (`id`, `username`, `displayName`) is unguarded; admin-only subset (`role`, `effectiveRole`, `active`, `groups`, `createdOn`, `updatedOn`) is gated by `RequiresRole(ADMIN)` per `_admin_only()` in `api/definitions/user/model.py`.

### `Group` (existing)

```graphql
type Group {
  id: UUID!
  name: String!
  role: Role!
}
```

This feature adds the resolver for `groups` query and the lifecycle mutations. The type itself doesn't change shape.

### `Deployment` — new field

```graphql
type Deployment {
  # ... existing fields ...
  createdByUsername: String      # nullable: null when the user row has been deleted (SET NULL)
}
```

`createdByUsername` is **not** admin-gated (drivers consume it). The existing `createdBy: User` field stays admin-gated.

## Inputs

```graphql
input CreateUserInput {
  username: String!
  password: String!
  displayName: String!
  role: Role!
  groupIds: [UUID!]    # optional
}

input UpdateUserInput {
  displayName: String   # null = leave
  role: Role            # null = leave
  active: Boolean       # null = leave
  groupIds: [UUID!]     # null = leave; [] = clear; [...] = replace (set semantics)
}

input CreateGroupInput {
  name: String!
  role: Role!
  memberIds: [UUID!]    # optional
}

input UpdateGroupInput {
  name: String          # null = leave
  role: Role            # null = leave
  memberIds: [UUID!]    # set semantics (same as UpdateUserInput.groupIds)
}
```

## Mutations

All admin-only — each declares `extensions=[_requires(Role.ADMIN)]`.

```graphql
type Mutation {
  createUser(input: CreateUserInput!): User!
  updateUser(id: UUID!, input: UpdateUserInput!): User!
  resetUserPassword(userId: UUID!, newPassword: String!): Boolean!
  deleteUser(id: UUID!): Boolean!

  createGroup(input: CreateGroupInput!): Group!
  updateGroup(id: UUID!, input: UpdateGroupInput!): Group!
  deleteGroup(id: UUID!): Boolean!
}
```

### Side effects per mutation

| Mutation | Side effects |
|---|---|
| `createUser` | INSERT into `user`. If `groupIds` is given, INSERT into `user_group` for each id. |
| `updateUser` | UPDATE the user. If `groupIds` is present, `replace_user_groups` runs (diff INSERT/DELETE). If `active` becomes `False`, `delete_all_sessions_for_user` runs in the same transaction. |
| `resetUserPassword` | UPDATE `user.password_hash`. `delete_all_sessions_for_user` runs in the same transaction. |
| `deleteUser` | Last-admin and FK-reference guards. DELETE from `user`. Cascades into `user_group` and `session`. |
| `createGroup` | INSERT into `group`. INSERT into `user_group` for each `memberId`. |
| `updateGroup` | UPDATE `group`. If `memberIds` is present, `replace_group_members` runs. If `role` changes, last-admin guard runs (re-promote / demote may flip membership-derived admin counts). |
| `deleteGroup` | Last-admin guard (deleting an admin-conferring group may demote its last admin). DELETE from `group`. Cascades into `user_group`. |

### Error codes returned via `extensions.code`

| Code | Mutation(s) | When |
|---|---|---|
| `UNAUTHENTICATED` | any | no session |
| `FORBIDDEN` | any | caller is not admin |
| `USER_NOT_FOUND` | `updateUser`, `resetUserPassword`, `deleteUser` | id unknown |
| `GROUP_NOT_FOUND` | mutations with `groupIds`/`memberIds`/`groupId` | id unknown |
| `DUPLICATE_USERNAME` | `createUser` | unique-constraint violation |
| `DUPLICATE_GROUP_NAME` | `createGroup`, `updateGroup` | unique-constraint violation |
| `LAST_ADMIN` | `updateUser` (deactivate or demote), `deleteUser`, `updateGroup` (member set / role change), `deleteGroup` | would_leave_zero_admins → true |
| `USER_HAS_REFERENCES` | `deleteUser` | FK references exist |
| `VALIDATION` | any | input fails length / charset / enum rules |

## Queries

```graphql
type Query {
  users(active: Boolean, role: Role, search: String): [User!]!
  groups(search: String): [Group!]!
}
```

Both are admin-only. Filters apply independently in any combination. `search` is a substring match (case-insensitive) over `username` and `display_name` for `users`; over `name` for `groups`. Returns the bare list (no cursor).

## Propagation test matrix (per `dev/guides/graphql-propagation-tests.md`)

A propagation test asserts that the value handed to the GraphQL endpoint reaches the database (for writes) and that the database state is projected to the resolver (for reads), going through the real service and repository layers.

| Field / mutation / argument | Test name |
|---|---|
| `createUser(input)` — every input field | `test_create_user_propagation` |
| `updateUser(id, input.displayName)` | `test_update_user_display_name_propagation` |
| `updateUser(id, input.role)` | `test_update_user_role_propagation` |
| `updateUser(id, input.active)` | `test_update_user_active_propagation` |
| `updateUser(id, input.groupIds)` set replacement | `test_update_user_group_ids_propagation` |
| `resetUserPassword(userId, newPassword)` — hash actually changes + sessions cleared | `test_reset_user_password_propagation` |
| `deleteUser(id)` — row + cascades | `test_delete_user_propagation` |
| `createGroup(input)` — every input field | `test_create_group_propagation` |
| `updateGroup(id, input.name)` | `test_update_group_name_propagation` |
| `updateGroup(id, input.role)` | `test_update_group_role_propagation` |
| `updateGroup(id, input.memberIds)` set replacement | `test_update_group_member_ids_propagation` |
| `deleteGroup(id)` | `test_delete_group_propagation` |
| `users(active, role, search)` filters | `test_users_query_filters_propagation` |
| `groups(search)` filter | `test_groups_query_filter_propagation` |
| `User.role`, `User.effectiveRole`, `User.active`, `User.groups`, `User.createdOn`, `User.updatedOn` (admin gating) | covered by schema-walk completeness in CI (existing test); propagation already covered by #179's `currentUser` propagation suite |
| `Group.id`, `Group.name`, `Group.role` | covered by `users` and `groups` query propagation tests when expanding nested groups |
| `Deployment.createdByUsername` | `test_deployment_created_by_username_propagation` |

## Concurrency, logging, and ordering tests (FR-010, FR-029, FR-030, D15, D16)

| Test name | Asserts |
|---|---|
| `test_concurrent_demote_last_admin_serialized` | Two async tasks each demote a different admin in an active-admin pair; at least one raises `LAST_ADMIN`. |
| `test_password_fields_masked_in_request_log` | For each of `createUser`, `resetUserPassword`, `changePassword`, `login`: captured log lines contain `"***"` and not the cleartext password. |
| `test_admin_mutation_emits_audit_line` | Each admin mutation logs a structured `admin_mutation` line with `actor`, `action`, `target`, `changed_fields` on success — and does NOT log values. |
| `test_admin_mutation_no_audit_on_rollback` | A mutation that raises inside the transaction does NOT emit an audit line. |
| `test_reset_password_atomic_under_failure` | When session-delete raises, neither the password hash nor any session row is observably changed. |
| `test_deactivate_user_atomic_under_failure` | Same property for `updateUser(active=False)`. |
| `test_list_users_eager_loads_groups` | Listing N users with memberships issues 2 queries (users + groups), not N+1. |

## Role-gating tests (per mutation)

For each admin mutation, a single functional test verifies the three-axis matrix:

| Caller | Expected |
|---|---|
| unauthenticated | `UNAUTHENTICATED` |
| `read_only` | `FORBIDDEN` |
| `read_write` | `FORBIDDEN` |
| `admin` | success |

Same matrix for each admin-only query (`users`, `groups`).

## Compatibility

No fields are renamed, removed, or have their type changed. The existing `User.role` / `User.effectiveRole` / etc. continue to be admin-gated as #179 left them. Adding the new mutations / queries / inputs / `Deployment.createdByUsername` is purely additive.
