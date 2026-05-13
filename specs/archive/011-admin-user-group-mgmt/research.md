# Research: Admin User & Group Management

**Feature**: 011-admin-user-group-mgmt
**Date**: 2026-05-11

This document records the decisions made during Phase 0. All open questions raised by the spec or implied by the tech stack are resolved here; the plan and tasks proceed against these decisions.

## Decisions

### D1. Last-admin guard shape — pure function over an explicit snapshot

**Decision**: Implement `auth/admin_guards` as two pure functions that take their state as parameters rather than reaching into the DB:

```python
# admin_guards.py
@dataclass(frozen=True, slots=True)
class AdminSnapshot:
    """Minimal view of admin-conferring state at the moment of the request."""
    # Direct-admin user ids.
    direct_admin_user_ids: frozenset[UUID]
    # User ids that are admin only via group membership.
    group_admin_user_ids: frozenset[UUID]
    # Active flag per user id we care about (target + actor).
    active_by_user_id: Mapping[UUID, bool]

def would_leave_zero_admins(
    action: AdminAction,         # enum: DEACTIVATE | DELETE | DEMOTE | REMOVE_FROM_ADMIN_GROUP
    target_user_id: UUID,
    snapshot: AdminSnapshot,
) -> bool: ...

def can_hard_delete_user(
    user_id: UUID,
    fk_refs_present: bool,
) -> bool: ...
```

**Rationale**: pure-function design makes the guards table-driven testable without a database. The service-layer caller assembles `AdminSnapshot` from the repository with a single query and a single materialised set of admin-conferring memberships.

**Alternatives considered**:

- *Inline checks in each mutation.* Rejected — duplicates the four-action matrix across four call sites, hides the rule in resolver code, and forces every test to hit the DB.
- *A `LastAdminError` exception raised from the repository layer.* Rejected — the repository would have to know about authorization semantics, which violates Principle III layering.

**Concurrency strategy** (FR-010): the pure-function check itself is stateless, but the *snapshot* it consumes MUST be captured under transactional guarantees. Approach:

1. Each admin mutation that touches admin-conferring state opens its UnitOfWork transaction.
2. The service-layer wrapper issues `SELECT id, role, active FROM "user" WHERE active = TRUE AND role = 'ADMIN' FOR UPDATE` to lock every active direct admin row, and `SELECT g.id, g.role FROM "group" g WHERE g.role = 'ADMIN' FOR UPDATE` plus the corresponding `user_group` rows for active admin-conferring memberships, so a concurrent demotion is forced to wait.
3. The snapshot is built from the locked rows. `would_leave_zero_admins(...)` runs against it.
4. The mutation proceeds. Commit releases the locks.

PostgreSQL's default `READ COMMITTED` is sufficient given the explicit `FOR UPDATE`; we do NOT need to escalate to `REPEATABLE READ` or `SERIALIZABLE`. The lock surface is tiny (admin users + admin groups), so contention is negligible at any realistic admin headcount.

Test: `test_concurrent_demote_last_admin_serialized` — opens two async sessions in parallel, has each call `updateUser(role=READ_WRITE)` against a different admin in an active pair, and asserts that at least one transaction raises `LastAdminError`.

### D2. Membership replacement — diff-and-mutate in one transaction

**Decision**: `auth/membership` exposes two functions:

```python
async def replace_user_groups(
    uow: UnitOfWork, *, user_id: UUID, group_ids: list[UUID]
) -> tuple[int, int]:
    """Return (added, removed). No-change → (0, 0) with no INSERT/DELETE statements."""

async def replace_group_members(
    uow: UnitOfWork, *, group_id: UUID, member_ids: list[UUID]
) -> tuple[int, int]:
    """Symmetric."""
```

Both load the existing membership, compute `to_add = new - existing` and `to_remove = existing - new`, INSERT/DELETE only those rows, and commit once. When both sets are empty, zero statements are issued.

**Rationale**: matches the spec's set-semantics requirement (FR-011), is observable in unit tests by counting SQL statements via `sqlalchemy.event.listens_for(engine, "before_execute")`, and lets the resolver hand the list straight in without normalising.

**Alternatives considered**:

- *Full-replace (`DELETE all → INSERT all`)*. Rejected — produces spurious INSERT/DELETE on no-change paths (violates the test in spec § Edge Cases).

### D3. `graphqlFetcher` UNAUTHENTICATED / FORBIDDEN handling

**Decision**: extend `frontend/src/lib/graphql-fetcher.ts` to:

1. Always send `credentials: 'include'` (the session cookie is `HttpOnly`, set by the backend on login).
2. After parsing the response, inspect `errors[0]?.extensions?.code`:
   - `UNAUTHENTICATED` → call a registered `signalUnauthenticated()` callback (set by `AuthProvider` at mount), then throw a typed `UnauthenticatedError`.
   - `FORBIDDEN` → throw a typed `ForbiddenError` with the original `message` so the calling hook surfaces it via the existing toast system.
   - Any other code → throw `GraphQLOperationError` carrying `code` and `message`.

Concretely:

```typescript
type ErrorCallback = () => void;
let onUnauthenticated: ErrorCallback | null = null;
export function setUnauthenticatedHandler(cb: ErrorCallback | null): void {
  onUnauthenticated = cb;
}

// In graphqlFetcher:
const code = json.errors?.[0]?.extensions?.code;
if (code === "UNAUTHENTICATED") {
  onUnauthenticated?.();
  throw new UnauthenticatedError(message);
}
if (code === "FORBIDDEN") {
  throw new ForbiddenError(message);
}
```

`AuthProvider` registers `() => { queryClient.clear(); window.location.assign('/login'); }` on mount and clears it on unmount.

**Rationale**: keeps the fetcher transport-only (no React imports), avoids React Context dependency on every call, and isolates the side effect to a single registered callback. The error subclasses give consumers typed error branches that survive minification.

**Alternatives considered**:

- *Wire UNAUTHENTICATED handling via React Query's `onError` in `QueryClient`.* Rejected — the error fires inside the calling hook, by which time the user has already seen a spinner-to-stale-data transition. Earlier handling in the fetcher is cleaner.
- *Throw `UnauthenticatedError` and rely on a top-level error boundary.* Rejected — every page would need to import that boundary; the redirect side effect is the same anyway.

### D4. TanStack Router auth context and `beforeLoad` admin guards

**Decision**: register an `auth` object on the router context so guards can read `auth.currentUser` synchronously without a hook:

```typescript
// router.ts
export const router = createRouter({
  routeTree,
  context: { auth: undefined as unknown as AuthContextValue },
});

// AuthProvider — once we have currentUser:
useEffect(() => { router.update({ context: { auth: { currentUser, ... } } }); }, [currentUser]);

// route file:
beforeLoad: ({ context }) => {
  if (context.auth.currentUser?.effectiveRole !== "ADMIN") {
    throw redirect({ to: "/" });
  }
},
```

`/login` does the inverse:

```typescript
beforeLoad: ({ context }) => {
  if (context.auth.currentUser != null) throw redirect({ to: "/" });
},
```

**Rationale**: matches TanStack Router's documented pattern for auth-aware routes, makes guards synchronous (no waterfall), and lets the same context value drive `useAuth()` for non-route code.

**Alternatives considered**:

- *Route-level loader that awaits a `currentUser` query.* Rejected — slower (waterfall on every nav), and the data is already in `AuthProvider`.
- *Wrap each admin page in a `<RequireAdmin>` component.* Rejected — the URL bar can briefly flash the page before redirecting, which the spec explicitly forbids ("redirect away").

### D5. Existing E2E suite — session-scoped Playwright cookie injection

**Decision**: add a new pytest fixture (`backend/tests/e2e/fixtures/auth.py`) that runs once per session:

1. Calls `client.auth.login(seeded_admin_username, seeded_admin_password)` against the live backend via SDK.
2. Reads the response `Set-Cookie` header for the session cookie.
3. On every browser context creation that the dual-entrypoint scenario driver opens, injects the cookie via `context.add_cookies(...)`.

Tests that need a clean unauthenticated browser opt out with `@pytest.mark.no_cookie_injection`. The auth-lifecycle test does this; everything else inherits the injection.

**Rationale**: no per-test login → no measurable runtime regression (SC-007 ≤ +5%). The injection is opt-out, not opt-in, so the default for existing tests stays "you have a session"; only the new lifecycle test exercises the form.

**Alternatives considered**:

- *Per-test login via the login form.* Rejected — adds seconds of overhead × N tests; flake surface; defeats SC-007.
- *Disable auth in E2E by setting an env var.* Rejected — defeats the purpose of having auth at all in CI.

### D6. Database schema — zero changes

**Decision**: this feature performs **no** schema migrations. Tables `user`, `group`, `user_group`, and `session` already exist from #179 and contain every column we need:

- `User.username` is `unique=True` (DuplicateUsernameError surfaces from the IntegrityError).
- `User.active` exists and defaults to `True`.
- `UserGroup` is the link table for set-semantics membership replacement.
- `Session.user_id` has `ondelete="CASCADE"` so `deleteUser` cleans up sessions automatically.

**Rationale**: respects the "Database schema changes" governance gate (no changes needed → no approval needed).

### D7. No allow-list changes

**Decision**: every new mutation and query gets `extensions=[_requires(Role.ADMIN)]`. None of them are appended to `MUTATION_ALLOW_LIST` / `QUERY_ALLOW_LIST` in `backend/styrmin_backend/api/auth/allowlist.py`.

**Rationale**: admin-only operations must be authenticated and authorized; the allow-list is for public bootstrap endpoints (`login`, `logout`, `currentUser`) and the agent ingress endpoints, neither of which apply here.

### D8. Username canonicalization is server-side and silent

**Decision**: `createUser` and `login` already canonicalize usernames via `.casefold()` in #179's code. The admin form accepts whatever the user types; the backend casefolds before insertion. The schema returns the canonicalized form. Duplicate-username detection is therefore case-insensitive.

**Rationale**: matches the existing #179 behavior. Avoids surprising operators with "ALICE" and "alice" being different users.

### D9. Required vs optional fields on `Update*Input`

**Decision**: `UpdateUserInput` and `UpdateGroupInput` declare every field as nullable; the resolver treats `None` as "leave alone" and a present non-None value as "apply". `groupIds` (resp. `memberIds`) is a nullable `list[UUID]` — `None` means leave alone, `[]` means clear all memberships, a populated list means replace with that exact set.

**Rationale**: matches the spec's partial-update contract (FR-002), keeps the GraphQL surface explicit ("absent" vs "empty" are semantically different), and dovetails with `replace_user_groups`/`replace_group_members`.

**Alternatives considered**:

- *Separate mutations for membership (`assignUserToGroup`, `removeUserFromGroup`)*. Rejected — the spec explicitly wants set-semantics in one submission (FR-011), and exposing two mutations would push set-construction onto every client.

### D10. SDK error surface

**Decision**: the SDK `client.users` and `client.groups` resources surface backend errors via the existing `_check_graphql_errors` mechanism in `BaseResource`. New error codes (`LAST_ADMIN`, `DUPLICATE_USERNAME`, `USER_HAS_REFERENCES`, `USER_NOT_FOUND`) propagate through `extensions.code` unchanged. The SDK does not introduce typed Python exception subclasses for these — callers `except StyrminGraphQLError` and switch on `.code`.

**Rationale**: matches the SDK's existing pattern for cluster/environment/deployment errors. Avoids exception explosion. If a specific caller needs a typed error, they wrap themselves.

### D11. Frontend admin tables — client-side pagination over the bare list

**Decision**: `UsersListPage` and `GroupsListPage` call `client.users.list(...)` once on mount, store the full list in TanStack Query, and paginate client-side (e.g., 25 rows per page via a `useMemo` slice + a `Pagination` UI control matching the existing `backup-storage-locations` page). Filters (`active`, `role`, `search`) are passed to the GraphQL query so the server can filter server-side; the in-memory list is the filtered result, paginated locally.

**Rationale**: the spec explicitly defers cursor pagination (Out-of-Scope). Server-side filtering keeps wire size sane.

### D12. `Deployment.createdBy.username` for drivers

**Decision**: the existing `Deployment.createdBy` resolver is admin-gated for reading the full `User` shape (per #179's `_admin_only()` extension). For driver consumption, add a separate `Deployment.createdByUsername: String` field that returns only the username and is **not** admin-gated — drivers in test fixtures and the `UiScenarioDriver` consume it. The full `createdBy: User` field remains admin-only for general API use.

**Rationale**: matches FR-028 without breaking the admin-gating of the `User` type. Username alone is the minimal field the UI scenario needs to assert attribution.

**Alternatives considered**:

- *Lower the gate on the entire `User.username` field.* Rejected — username is already public, but the way it's reached (via `Deployment.createdBy`) is admin-gated by the parent. A dedicated string field is cleaner than weakening the gating story.
- *Have drivers read username via a separate `users(id: ...)` lookup.* Rejected — `users` query is admin-gated; drivers run as the seeded admin in tests so this would work, but the scalar `createdByUsername` field is a lighter contract.

### D13. Password masking in request logs (FR-029)

**Decision**: extend the existing GraphQL request-logging path with a static mask-list of field names: `password`, `newPassword`, `currentPassword`. Before the logger emits a request, walk the `variables` dict (and any extracted-from-body field names matching the list) and replace each value with `"***"`. The list is a module-level constant in `backend/styrmin_backend/api/logging/mask.py` (NEW), exported as `MASKED_VARIABLE_NAMES: frozenset[str]`. The existing logging middleware imports this set and applies it in one place.

**Rationale**: a static field-name allow-list is simple to audit (one import) and harder to break than per-mutation handling. Adding a new password field in the future means appending to the set, which is a one-line PR change that triggers code review.

**Test**: `test_password_fields_masked_in_request_log` — issues `createUser`, `resetUserPassword`, `changePassword`, `login` and inspects the captured log lines via `loguru.logger.remove(); loguru.logger.add(sink, ...)`. Asserts each line contains `"***"` and does not contain the original password substring.

### D14. Admin-mutation audit log (FR-030)

**Decision**: every admin mutation, on success, emits one structured Loguru line:

```python
logger.info(
    "admin_mutation actor={} action={} target={} changed_fields={}",
    actor_id, action_name, target_id, comma_separated_field_names,
)
```

The line is part of the mutation's service function (not the resolver) so it is recorded **only when the transaction commits**. No values are logged, only field names (`role`, `active`, `groupIds`) — values may contain passwords or PII.

**Test**: each functional test in `test_admin_user_mutations.py` / `test_admin_group_mutations.py` captures Loguru output and asserts the audit line shape.

### D15. Transaction ordering for "write + invalidate sessions"

**Decision**: in `resetUserPassword` and `updateUser(active=False)`, the service function:

1. Updates the user row (`password_hash` or `active`) and flushes — but does NOT commit.
2. Calls `delete_all_sessions_for_user(...)` against the same `db_session`.
3. Commits once.

If step 2 raises, the password / active flag is also rolled back. If step 1 raises, sessions stay intact.

**Test**: `test_reset_password_atomic_under_failure` monkeypatches `delete_all_sessions_for_user` to raise and asserts neither the password change nor any session deletion is observable post-rollback.

### D16. Eager loading of `users.groups` to avoid N+1

**Decision**: `list_users(...)` in `services/auth/users.py` uses `select(User).options(selectinload(User.groups))` so the `groups` field on each `User` is populated in a single follow-up query rather than per-row lazy-load. Mirrors the pattern `authenticate()` already uses in #179.

**Test**: a unit test with an SQL-statement counter asserts that listing 10 users with varied memberships executes 2 queries total (users + groups), not 11.

## Open Risks / Watch-outs

- **`router.update({ context })`** rerunning every route's `beforeLoad` when the auth changes. In practice this is what we want (becoming admin should re-evaluate guards), but worth a watch in code review.
- **The session cookie is HttpOnly** — frontend cannot read it directly. `credentials: 'include'` is the only knob; tests assert this is sent by inspecting `fetch` mock calls.
- **Cookie injection across browser contexts** in Playwright: the fixture must re-inject on each new `BrowserContext` (Playwright recreates one per test by default). The session-scoped fixture computes the cookie value once and provides it as a function that any per-test context creation can call.
- **Schema-walk completeness test in CI**: every new field must declare a permission. We assert that the test would catch a missing gate as part of the contract.
- **Duplicate-username race**: rely on the `unique=True` constraint on `User.username` to raise `IntegrityError` and surface it as `DuplicateUsernameError`. No pre-check needed.
