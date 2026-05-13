# ADR-025: Three-tier role-based authorization with default-deny GraphQL extension

**Status**: Accepted
**Date**: 2026-05-04
**Source**: GitHub issue [#179](https://github.com/opsmill/styrmin/issues/179) + [#184](https://github.com/opsmill/styrmin/issues/184)

## Context

Once authentication exists (ADR-024), every authenticated caller still needs to be classified along an axis that maps cleanly to operator intent — "this teammate can read but not change anything", "this teammate can deploy and change config", "this teammate can manage users and dangerous lifecycle". Without that classification, authentication only proves identity; it does not gate operations.

The product requirement is a small, fixed set of roles operators can reason about at a glance, not a fine-grained ACL system. The realistic v1 caller populations are: a junior operator who should not be able to deploy production workloads, a senior operator who deploys but should not manage user accounts, and an administrator who does everything. Operators have repeatedly described their model as "viewer / operator / admin", so the system should match that vocabulary directly.

Layered on top of the role choice is a CI-gating concern: it must be **impossible** to add a new mutation that ships unguarded. A reviewer looking at a `Mutation.foo` resolver should not have to remember to also check that a permission was attached — the missing permission must fail CI on its own.

Finally, this issue is the load-bearing half of a two-issue split. The follow-up issue (#180) ships the admin user/group CRUD resolvers and the lifecycle rules they enforce (last-admin guard, deactivation primacy, hard-delete-only-when-no-FKs). Those rules are decided here so the follow-up implements against a documented contract rather than rediscovering the design.

## Decision

### Three roles as an `IntEnum`

```python
class Role(IntEnum):
    READ_ONLY = 10
    READ_WRITE = 20
    ADMIN = 30
```

A single role per `User` and a single role per `Group`. Membership is many-to-many between users and groups.

`READ_ONLY` can read; `READ_WRITE` can read and execute deployment-lifecycle mutations; `ADMIN` can do everything including user/group management. The integer values are gapped (10/20/30) so an intermediate role can be inserted later without renumbering.

`IntEnum` (rather than `Enum` of strings) is deliberate — comparisons (`role >= Role.READ_WRITE`) work natively and the storage column is an ordered integer, so SQL filters like `WHERE role >= 20` are direct. The GraphQL representation is the string variant (`READ_ONLY` / `READ_WRITE` / `ADMIN`); the integer is an implementation detail that does not leak.

### Effective role = max(direct, group roles)

A user's authorization-relevant role is computed as:

```python
effective_role = max(user.role, *(group.role for group in user.groups))
```

The empty-groups case reduces cleanly to `user.role` (the splat collapses to nothing). Both the direct `User.role` and the computed `User.effectiveRole` are exposed in the schema; the backend `RequiresRole` permission check and the frontend role-gated UI **both consume `effectiveRole`** — direct role is informational only.

This rule means group membership monotonically elevates: joining a group with role `ADMIN` makes you effectively an admin even if your direct role is `READ_ONLY`. A user cannot have their access *reduced* by group membership. This matches operator intent ("groups grant capabilities, they don't take them away") and avoids the subtle bug where a user can be deauthorized by being added to a group.

### `RequiresAuthentication`: default-deny GraphQL extension

A schema extension runs **before** any resolver and rejects unauthenticated requests with a structured `UNAUTHENTICATED` error, except for an explicit allow-list:

- `Mutation.login` — the entry point; cannot require authentication or no one can log in.
- `Query.currentUser` — returns `null` for unauthenticated callers (callers booting the app distinguish "logged out" from "errored" without an error-handling branch).
- Any field whose name begins with `__` — GraphQL introspection (`__schema`, `__type`). Schema discovery is intentionally public; the schema itself does not encode secrets and tooling needs it.

Default-deny rather than default-allow is the load-bearing decision. A new resolver that forgets to opt out of the extension still requires authentication — the failure mode is "endpoint mistakenly requires login", not "endpoint mistakenly leaks data". The allow-list is short, central, and reviewable.

### `RequiresRole(role)`: per-resolver Strawberry permission

Strawberry's `PermissionExtension` carries a single `RequiresRole(role: Role)` permission class layered onto resolvers needing more than the authenticated baseline. The class compares the caller's `effective_role` to `role` and raises `FORBIDDEN` if `caller.effective_role < role`.

A field with no `RequiresRole` on it requires **only authentication** (the baseline guarantee from `RequiresAuthentication`). A field that needs `READ_WRITE` or `ADMIN` declares it explicitly:

```python
@strawberry.mutation(extensions=[PermissionExtension([RequiresRole(Role.ADMIN)])])
def create_user(self, info, ...) -> User: ...
```

One permission class with a parameter, not three classes (`RequiresReadOnly` / `RequiresReadWrite` / `RequiresAdmin`). The role being checked is data, not code; making it a parameter keeps the surface small and makes role bumps a one-token diff.

### Schema-walk completeness test

A pytest test walks the `Mutation` type at import time and asserts that every field has either:

1. A `RequiresRole` permission attached, **or**
2. A name in the documented allow-list `{login, logout}`.

A new mutation added without one of those two conditions fails this test. The allow-list lives in the test file as a literal set; adding a name to it is a deliberate, reviewable line of code in the same PR that adds the unguarded mutation. There is no ambient "skip if too cumbersome" override.

`logout` is on the allow-list because requiring a role to log out is a usability bug (a deactivated user cannot log out of their existing session, which would defeat the deactivation). `login` is on the allow-list because pre-authentication callers cannot have a role.

### Read-side gating on the `User` type

Per-field role checks on the `User` type partition fields into "any authenticated caller can see this" and "only admins can see this":

| Field | Visibility |
|-------|------------|
| `id`, `username`, `displayName` | any authenticated user |
| `role`, `effectiveRole`, `active`, `groups`, `createdOn`, `updatedOn` | admin **or self** |
| `passwordHash` | not in schema at all |

The public subset is what's needed to render `Deployment.createdBy` attribution without leaking other users' administrative metadata (a `READ_WRITE` operator seeing "deployed by alice" should not also see alice's role and group memberships). An admin needs the full surface to investigate.

The "or self" carve-out is necessary because the frontend's role-gated UI reads `currentUser.effectiveRole` on every page load: without it, non-admins see a field error that — under GraphQL's non-null propagation — nulls the entire `currentUser` and the global `UNAUTHENTICATED` handler bounces them back to `/login`. Self-visibility of one's own role doesn't leak information ("you can see what you already are") while still hiding the same fields on other users from non-admin callers.

This is implemented as per-field `IsSelfOrRole(ADMIN)` decorators on the admin-or-self fields, not as two separate types — one type is the source of truth; the GraphQL field-resolution behaviour is the gate. `IsSelfOrRole.has_permission` compares `source.id` (the resolved parent `User`) to `info.context['current_user'].id`; an admin passes the role check regardless of who they're looking at.

### Structured error codes

All authorization-flow errors flow through the existing `StructuredErrorExtension` with `extensions.code` set to one of:

- `UNAUTHENTICATED` — no valid session for a request that requires one.
- `FORBIDDEN` — authenticated but `effective_role < required_role` for the resolved field.
- `INVALID_CREDENTIALS` — `login` failure (wrong password / nonexistent user / deactivated user, indistinguishable on purpose; see ADR-024).

Three codes, distinct meanings, no overloading. Clients (the SDK and the frontend) map each to a typed exception or a typed UI handler; downstream code handles the three cases without string-matching the message.

### Lifecycle rules (deferred resolvers, decided contract)

The mutations that exercise these rules ship in #180, but the rules are documented here so #180 implements against a contract rather than redesigning at implementation time:

1. **Last-admin guard.** `updateUser`, `deleteUser`, and any `Group` change that would reduce the count of effective admins below 1 must reject with `FORBIDDEN`. The check counts admins by `effectiveRole`, not by direct role — demoting the last admin who is also in an admin group is fine; demoting the last admin user when the group is also being deleted in the same transaction is not. The guard runs in a serializable-isolation transaction so concurrent demotions cannot race past each other.
2. **Deactivation primacy.** Setting `active = false` on a `User` deletes that user's `session` rows in the same transaction. A deactivated user cannot log in and cannot continue an existing session — both gates close in one commit. Reactivation does **not** restore old sessions; the user must log in again.
3. **Hard-delete only when no FKs.** `deleteUser` hard-deletes the row only when no foreign keys reference the user (no deployments attributed via `createdBy`, no audit-log rows once those exist). When references exist, `deleteUser` deactivates instead and returns a structured "user has references; deactivated" result. This preserves attribution forever (a `Deployment` always has a non-null `createdBy`) without requiring callers to choose between losing audit data and accumulating dead user rows.

These three rules together ensure the system cannot reach a state with zero admins, with a deactivated user holding live sessions, or with a deployment whose creator FK is dangling.

## Consequences

- **Easier**: the authorization story is one sentence: "every request requires authentication; some fields require a minimum effective role." Operators, reviewers, and new contributors absorb the model in seconds.
- **Easier**: adding a new mutation that needs a role is a single decorator. The defaults push contributors toward the safe path (require auth always; require admin if you say so).
- **Easier**: the schema-walk test makes "did you remember to add a permission?" mechanical rather than a code-review judgment call. A forgotten permission fails CI before review.
- **Easier**: the SDK and frontend distinguish UNAUTHENTICATED, FORBIDDEN, and INVALID_CREDENTIALS without parsing strings — the structured error extension carries the code.
- **Easier**: deferring lifecycle resolvers to #180 still leaves a hard contract. The rules above are testable against unit-level helper functions even before the resolvers exist, so #180 can ship the resolvers as thin wrappers over already-tested invariants.
- **Harder**: three roles are coarse. Operators who want "can deploy to staging but not production" or "can read deployments but not user metadata in non-attribution contexts" cannot express that under this model. Accepted: the alternative (per-resource ACLs / ABAC) is a design that takes years to converge in the wild and we explicitly defer to a future issue.
- **Harder**: `effectiveRole = max(...)` means group membership cannot revoke. A user with direct `ADMIN` who joins a `READ_ONLY` group remains an admin. This is the intended semantic — the alternative (groups can both grant and revoke) makes "what can this user do?" require simulating the full membership graph, which we judged worse than the asymmetry. Documented here for reviewer awareness.
- **Harder**: introspection is unauthenticated. An anonymous probe of a Styrmin instance can enumerate the schema. We treat the schema itself as non-sensitive (the field names and types do not encode secrets); if an operator deployment has a stricter requirement they can front the GraphQL endpoint with a network-layer block on `application/json` POSTs containing `__schema`. Documenting this trade-off here keeps the rationale auditable.
- **Harder**: the schema-walk test is a CI gate, not a runtime gate. Someone shipping a hot-patch that bypasses CI could in principle ship an unguarded mutation. Mitigated by the pre-commit hook running the same test (see ADR-014), so a local commit would also flag it.
- **Convention to replicate**: every new field that needs more than authentication declares it via `RequiresRole(...)`. Every new error code uses the `StructuredErrorExtension` pattern with a documented code constant. Every new lifecycle rule that depends on user role state runs inside a serializable-isolation transaction.

## Alternatives Considered

- **More than three roles** (e.g., `VIEWER / OPERATOR / DEPLOYER / ADMIN / OWNER`): Rejected for v1. Operators consistently described their access model in three tiers; more granularity has no concrete user story. Adding a fourth role later is a `IntEnum` line and a permission decorator update — cheap to do when a use case emerges.
- **Per-resource ACLs / ABAC**: Rejected for v1. Solves real problems we don't have yet (per-environment authorization, per-deployment-class authorization). The right time to introduce ABAC is when an operator has explicitly hit the wall of three roles, not before.
- **Multiple roles per user**: Rejected. Equivalent to a single role being the max of the assigned set, which collapses to today's model anyway. The group mechanism already provides the "user inherits multiple roles" capability for the realistic case (admin via group membership).
- **Default-allow with explicit `RequiresAuthentication` per field**: Rejected. The failure mode is "field accidentally public" rather than "field accidentally requires login". Choosing the safer failure mode at the default-deny default is the entire point of the extension.
- **Three permission classes (`RequiresReadOnly` / `RequiresReadWrite` / `RequiresAdmin`)**: Rejected in favour of `RequiresRole(role)`. The role being checked is data; encoding it in the class name turns role bumps into refactors and obscures the comparison being performed.
- **Group roles can lower a user's effective role**: Rejected. Means a user's authorization depends on the entire membership graph in ways that are not local; "what can this user do?" becomes a non-trivial computation rather than a lookup. The asymmetry (groups grant, never revoke) is documented and intentional.
- **Allow-list lives in a config file or env var**: Rejected. The list is small (`{login, logout}` plus introspection) and adding to it should be a code change reviewed in the same PR that adds the unguarded resolver. Externalising it would let an unguarded mutation ship via config drift.
- **Combined error code (`AUTH_FAILED` covering UNAUTHENTICATED + FORBIDDEN + INVALID_CREDENTIALS)**: Rejected. SDK callers and frontend code routinely need to distinguish "log in again" from "you're not allowed" from "wrong password"; collapsing them forces every consumer to re-derive the distinction from the message string.
- **Hard-delete users always (cascade delete `Deployment.createdBy`)**: Rejected. Attribution is one of the load-bearing reasons authentication exists at all; cascade-deleting it on user removal would make the audit trail self-mutating. The "deactivate when references exist" path preserves the trail without orphaning any FK.
- **Run the lifecycle rules at the application layer with last-write-wins**: Rejected for the last-admin guard specifically. Two concurrent demotions could both pass an application-layer "is there at least one admin?" check and both succeed. Serializable-isolation transactions for these mutations make the gate race-free.
