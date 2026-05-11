# Feature Specification: Admin User & Group Management

**Feature Branch**: `011-admin-user-group-mgmt`
**Created**: 2026-05-11
**Status**: Draft
**Input**: GitHub issue [opsmill/styrmin#180](https://github.com/opsmill/styrmin/issues/180) — "feat: admin user & group management — CRUD mutations and admin UI"

## Context

Issue #179 lands the authentication foundation (user/session models, login/logout/`currentUser`/`changePassword`, default-deny GraphQL, `RequiresRole` permission class, bootstrap, password hashing, session token plumbing, audit FK propagation, `STYRMIN_TOKEN` SDK env var). After #179, Styrmin is authenticated but administrators have no tooling to manage users and groups: every onboarding, password reset, role change, group membership update, and offboarding requires either an SDK script or a manual SQL session. There is no login page for browser users, no header surface that shows who is logged in, no self-service way to change a password through the UI, and no role-gating on the existing pages — so the new permission system has no visible affordances.

This feature closes that gap. After it ships, an administrator can complete the full user lifecycle entirely from the frontend, and the admin UI is the first surface that visibly enforces the auth model from #179.

This feature **strictly depends on #179** and consumes the foundation it builds without duplicating any of it.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Authenticated session in the browser (Priority: P1)

A user arrives at Styrmin in a browser. If they are not authenticated, the system presents a login page. Once logged in, the app header shows their display name and a small role badge, and a menu in that header gives them access to Profile and Logout actions. If a request later returns `UNAUTHENTICATED` (the session expired or was revoked), the next action redirects them back to the login page rather than surfacing a confusing error toast.

**Why this priority**: Without a login page and authenticated header state, no other browser-facing flow is reachable. This is the visible carrier of issue #179's auth model and the prerequisite for every later story.

**Independent Test**: With #179's auth foundation already deployed, navigate to the app unauthenticated → land on `/login` → submit valid credentials → arrive at the home page with display name and role badge in the header → click the header menu and see Profile + Logout → click Logout → land back on `/login`.

**Acceptance Scenarios**:

1. **Given** the user is unauthenticated, **When** they navigate to any app route, **Then** the app routes them to the login page.
2. **Given** the user submits invalid credentials, **When** the login fails, **Then** the form shows the generic message "Invalid username or password." (it does not distinguish wrong-username from wrong-password).
3. **Given** the user is authenticated, **When** the app renders, **Then** the header shows their display name and a role badge derived from their effective role.
4. **Given** the user is authenticated, **When** they open the header menu, **Then** they see Profile and Logout items.
5. **Given** the user is authenticated, **When** they navigate to `/login`, **Then** the app redirects them to `/`.
6. **Given** the user is authenticated, **When** a subsequent GraphQL request returns `UNAUTHENTICATED`, **Then** the client clears the in-memory auth state and redirects to `/login` (no error toast).
7. **Given** the user is authenticated, **When** a request returns `FORBIDDEN`, **Then** the client surfaces a clear in-place error (a toast) and does **not** redirect.

---

### User Story 2 — Admin manages users (Priority: P1)

A Styrmin administrator opens a Users page, sees the full user list with username, display name, role, group memberships, and active status, and can filter by `active`, by `role`, and by free-text search across username and display name. From this page they create new users, edit existing users (display name, role, group memberships, active flag), reset another user's password without knowing the current one, and hard-delete users that have no foreign-key references. The system refuses any operation that would leave zero active admins.

**Why this priority**: This is the explicit ask of issue #180. Without it, administrators must drop to SDK scripts or SQL for every user lifecycle action.

**Independent Test**: Log in as the seeded admin → open `/users` → see the table → create a new `read_write` user with a display name, password, and one group membership → edit that user's display name and toggle `active` off → reset that user's password → attempt to delete the seeded admin and observe rejection (zero-active-admins guard) → delete the newly-created user (no FK references) successfully.

**Acceptance Scenarios**:

1. **Given** an admin is on `/users`, **When** the page loads, **Then** they see a paginated table with columns username, display name, role, group memberships, active status.
2. **Given** an admin is on `/users`, **When** they apply a filter (`active`, `role`, or search), **Then** the visible rows reflect the filter without a page reload.
3. **Given** an admin opens "Create user", **When** they submit username, display name, initial password, role, and optional group memberships, **Then** the user is created and appears in the table. Username is required, display name is required, role is required (no implicit default).
4. **Given** an admin edits an existing user, **When** they change display name, role, group memberships, or the active flag, **Then** the change is persisted. Username is not editable.
5. **Given** an admin chooses "Reset password" for another user, **When** they submit a new password, **Then** the target user's password is set and **all of that user's existing sessions are invalidated**.
6. **Given** an admin sets a target user's `active` to `false`, **When** the change is committed, **Then** all of the target user's sessions are invalidated in the same transaction and the user can no longer log in. Attribution history (deployments they created, etc.) is preserved.
7. **Given** a user is deactivated, **When** an admin sets their `active` back to `true`, **Then** they can log in again.
8. **Given** an admin attempts hard-delete of a user with no FK references, **When** they confirm, **Then** the user row is removed.
9. **Given** an admin attempts hard-delete of a user with FK references (e.g., they created a deployment), **When** the attempt is made, **Then** the operation is rejected with a clear structured error.
10. **Given** any operation would leave zero active admins (deactivate the last admin, delete the last admin, demote the last admin, remove the last admin from their admin-conferring group, **including the admin acting on themselves**), **When** the admin submits it, **Then** the operation is rejected with a clear structured error and no state changes.
11. **Given** an admin attempts to create a user with a duplicate username, **When** the request is sent, **Then** the server returns a clear structured error.

---

### User Story 3 — Admin manages groups (Priority: P1)

A Styrmin administrator opens a Groups page that mirrors the Users page workflow: list, create, edit, delete, and manage members. When editing a group, the form lets them set the group's role and replace the group's full member set in one submission (a "select multiple users" affordance).

**Why this priority**: Groups are part of the foundational role model from #179. Without admin tooling for groups, the group-conferred-role pathway is unmanaged from the UI.

**Independent Test**: Log in as admin → open `/groups` → create a group "platform-admins" with role `admin` and two members → edit that group, change role to `read_write`, and replace the member set with a different pair of users → delete the group.

**Acceptance Scenarios**:

1. **Given** an admin is on `/groups`, **When** the page loads, **Then** they see the list of groups (with optional free-text search).
2. **Given** an admin opens "Create group", **When** they submit name, role, and an initial member set, **Then** the group is created.
3. **Given** an admin edits a group, **When** they change the role or the full member set, **Then** the change is persisted as a single submission. The membership change uses **set semantics**: the provided list is the new full set; rows added are inserted, rows removed are deleted, no-change is a no-op.
4. **Given** an admin deletes a group, **When** they confirm, **Then** the group is removed.
5. **Given** an admin attempts a group change that would leave zero active admins (e.g., removing the only admin from the only admin-conferring group), **When** the attempt is made, **Then** the operation is rejected.

---

### User Story 4 — User manages their own profile (Priority: P1)

Any authenticated user can open a Profile page where they edit their own display name and change their own password. Changing the password requires their current password. After a successful password change, all of the user's **other** sessions are invalidated; the calling session is preserved.

**Why this priority**: Self-service password change is table stakes and unblocks rotation without requiring an admin. It also pairs with admin-driven password reset to cover both lockout-recovery paths.

**Independent Test**: Log in as any user → open Profile → change display name and observe the header update → change password successfully → observe other open sessions log out on next request while the current session continues to work → submit wrong current password and observe the form error.

**Acceptance Scenarios**:

1. **Given** an authenticated user is on Profile, **When** they edit their display name and save, **Then** the change is persisted and the header reflects the new name.
2. **Given** an authenticated user is on Profile, **When** they submit current + new password correctly, **Then** the password is changed and all of their *other* sessions are invalidated; the calling session continues to work.
3. **Given** an authenticated user submits the wrong current password, **When** they save, **Then** the form shows a clear in-place error and nothing changes.

---

### User Story 5 — Role-gated UI ("hide-not-disable") (Priority: P1)

Users with insufficient role for an action do not see the action in their chrome. `read_only` users do not see mutation buttons throughout the app; `read_write` users do not see admin-only buttons. The Users/Groups nav entries are hidden from non-admins entirely. A user who is admin only via group membership (direct role `read_only`, but a group of role `admin`) sees the admin UI because frontend gating reads **effective role**, not direct role. Direct navigation to `/users` or `/groups` without admin role redirects to `/`.

**Why this priority**: Without role gating, the new permission system has no visible affordances and admin-only UI advertises itself to users who cannot use it.

**Independent Test**: Log in as `read_only` → no mutation buttons or Users/Groups nav visible → log in as `read_write` → mutation buttons visible, admin nav hidden → log in as a user whose effective role is admin via group membership → admin UI visible → as `read_only`, navigate to `/users` directly → redirected to `/`.

**Acceptance Scenarios**:

1. **Given** a `read_only` user, **When** any page renders, **Then** mutation buttons that would call write mutations are not in the DOM (hidden, not just disabled).
2. **Given** a `read_only` user, **When** the nav renders, **Then** the "Users" and "Groups" entries are absent.
3. **Given** a `read_write` user, **When** the nav renders, **Then** the "Users" and "Groups" entries are absent and admin-only mutation buttons are not in the DOM.
4. **Given** a user with direct role `read_only` and group-membership-derived role `admin`, **When** any page renders, **Then** the admin UI is visible (gating reads effective role).
5. **Given** a non-admin navigates directly to `/users` or `/groups`, **When** the route resolves, **Then** they are redirected to `/`.

---

### User Story 6 — SDK parity for user/group management (Priority: P2)

The Python SDK exposes a `client.users` namespace (`create`, `update`, `reset_password`, `delete`, `list(active=, role=, search=)`, `get(id)`) and a parallel `client.groups` namespace (`create`, `update`, `delete`, `list(search=)`, `get(id)`). These mirror the admin GraphQL surface so operators can script user/group management.

**Why this priority**: SDK access is required for the lifecycle E2E scenario's api-mode variant and for operator scripts. It is P2 because the UI delivers the primary user value; SDK parity is a parallel deliverable.

**Independent Test**: Run a Python script using `client.users.create(...)` followed by `client.users.list(role=...)` and observe correct typed results; same for `client.groups`.

**Acceptance Scenarios**:

1. **Given** the SDK is installed, **When** an operator calls `client.users.create(...)`, **Then** a user is created via the GraphQL admin mutation.
2. **Given** the SDK is installed, **When** an operator calls `client.users.list(active=True, role=READ_WRITE, search="ann")`, **Then** the SDK returns the matching users typed.
3. **Given** the SDK is installed, **When** an operator calls a `users` or `groups` method as a non-admin token, **Then** the SDK surfaces the GraphQL `FORBIDDEN` error cleanly.

---

### User Story 7 — Operator documentation (Priority: P2)

A user-facing guide under `dev/guides/` walks a new operator through the role model, default admin bootstrap, and admin UI usage. It lands in this feature because most of the content (admin UI walkthroughs, profile page tour) is meaningless without the UI.

**Why this priority**: Required for self-service onboarding of new operators. P2 because the feature is usable without it but undocumented features hurt adoption.

**Independent Test**: A new operator reads the guide and successfully bootstraps an admin, creates a user via the UI, and resets a password — without reading source.

**Acceptance Scenarios**:

1. **Given** a new operator, **When** they read the guide, **Then** they understand the three roles, the default-admin bootstrap path, and the admin UI workflow.

---

### User Story 8 — End-to-end auth lifecycle (Priority: P1)

A single E2E scenario exercises the full auth lifecycle: log in as the seeded admin, create a `read_write` user, log in as that new user (api-mode: SDK login; ui-mode: drive the actual login form, **not** cookie injection), perform a `read_write`-permitted mutation and assert success, attempt an admin-only mutation and assert `FORBIDDEN`. The scenario runs in **both** api-mode and ui-mode. The existing UI-mode E2E suite continues to use session-scoped Playwright cookie injection at session start; the new auth-lifecycle scenario opts out of cookie injection so the login page is genuinely exercised.

**Why this priority**: This is the explicit "shipped to a pass" requirement for the feature and the only end-to-end proof that the auth model from #179 plus the admin tooling from #180 actually work together.

**Independent Test**: Run the auth-lifecycle E2E in api-mode and in ui-mode; both pass.

**Acceptance Scenarios**:

1. **Given** the lifecycle scenario runs in api-mode, **When** the seeded admin creates a `read_write` user via SDK, that user logs in via SDK, performs a `read_write`-permitted mutation, and attempts an admin-only mutation, **Then** the permitted mutation succeeds and the admin-only mutation is rejected with `FORBIDDEN`.
2. **Given** the lifecycle scenario runs in ui-mode, **When** the same sequence happens via the actual login form and admin UI (no cookie injection), **Then** the result matches api-mode.
3. **Given** any existing E2E scenario, **When** the suite runs, **Then** it uses session-scoped Playwright cookie injection at session start (no per-test login flow), so no existing test slows down or flakes from the new auth requirement.

---

### Edge Cases

- **Last-admin protection covers four operations**: deactivate, hard-delete, demote (change role away from `admin`), and remove from the only admin-conferring group. Each must be rejected when it would result in zero active admins, **including when the acting admin operates on themselves**.
- **Hard-delete with FK references**: rejected with a clear structured error. v1 hides or grays the Delete button when references exist; no dedicated "Users with FK references" UI.
- **Self-demotion**: rejected by the same last-admin guard when the actor is the only active admin.
- **Group-conferred admin promotion**: when a user's direct role is `read_only` but they belong to a group with role `admin`, their **effective role** is `admin`. UI gating reads effective role.
- **Group-conferred admin removal**: a user who is admin only via group membership loses admin access when the group is deleted, when their membership is removed, or when the group's role is changed. The last-admin guard applies to these paths too.
- **Mid-flow session expiry**: a request that returns `UNAUTHENTICATED` triggers an automatic redirect to `/login` (clearing auth state); a request that returns `FORBIDDEN` surfaces an in-place error without redirecting.
- **Filtering combinations on `users`**: `active`, `role`, and `search` are independent filters; any combination is supported. Search matches across username and display name.
- **No cursor / server-side pagination on `users` or `groups`** in v1: the admin tables use **client-side pagination** over the bare list returned by the API. Revisit when user count justifies it.
- **`createUser` with duplicate username**: rejected with a clear structured error.
- **`username` is immutable post-create**: the update input does not accept a `username` field; any client sending one should be rejected by the schema, not silently ignored.
- **Login failure leaks no information**: the error message is generic ("Invalid username or password.") and does not distinguish wrong-username from wrong-password.
- **Frontend role checks always read `effectiveRole`, never the direct `role`**, so a user who is admin via group membership sees the same UI as a directly-assigned admin.

## Requirements *(mandatory)*

### Functional Requirements

**Admin GraphQL surface** (each mutation/query is admin-only via the `RequiresRole(ADMIN)` permission class introduced in #179):

- **FR-001**: System MUST expose `createUser(input: CreateUserInput!): User!` where `username`, `displayName`, `password`, and `role` are required. `groupIds` is optional.
- **FR-002**: System MUST expose `updateUser(id: UUID!, input: UpdateUserInput!): User!` where `displayName`, `role`, `active`, and `groupIds` are each optional/nullable; absent means "leave alone". `groupIds` uses **set semantics**: the provided list is the full new set. The input MUST NOT accept a `username` field (immutable post-create).
- **FR-003**: System MUST expose `resetUserPassword(userId: UUID!, newPassword: String!): Boolean!` as a dedicated mutation (not a flag on `updateUser`) and MUST invalidate **all** of the target user's existing sessions.
- **FR-004**: System MUST expose `deleteUser(id: UUID!): Boolean!` and MUST reject the operation when foreign-key references exist (e.g., the user created a deployment).
- **FR-005**: System MUST expose `createGroup(input: CreateGroupInput!): Group!`, `updateGroup(id: UUID!, input: UpdateGroupInput!): Group!` (with `memberIds` using **set semantics**), and `deleteGroup(id: UUID!): Boolean!`.
- **FR-006**: System MUST expose `users(active: Boolean, role: Role, search: String): [User!]!` returning a bare list (no cursor) and `groups(search: String): [Group!]!` returning a bare list. Filters apply independently in any combination.
- **FR-007**: System MUST gate every admin mutation and every admin-only field on the `User` type (`role`, `effectiveRole`, `active`, `groups`, timestamps) and the entire `Group` type with `RequiresRole(ADMIN)`. A `read_write` caller of any admin mutation MUST receive `FORBIDDEN`; an unauthenticated caller MUST receive `UNAUTHENTICATED`.
- **FR-008**: System MUST reject `createUser` with a duplicate username with a clear structured error.
- **FR-009**: System MUST invalidate the target user's sessions in the same transaction as the change when `updateUser` sets `active: false`.

**Last-admin protection** (applies symmetrically to self and others):

- **FR-010**: System MUST reject any single operation (`updateUser` setting `active: false`, `updateUser` changing role away from `admin`, `deleteUser`, `updateUser`/`updateGroup` removing the only admin from the only admin-conferring group) that would leave zero active admins. Pre-condition is checked at request time against current state.

**Membership replacement**:

- **FR-011**: When `updateUser.groupIds` is present, the system MUST replace the user's full group set with the provided list in a single transaction (diff against existing → INSERT new, DELETE removed; no-change is a no-op with no spurious INSERT/DELETE statements). Equivalent behavior MUST hold for `updateGroup.memberIds`.

**Validation**:

- **FR-012**: `CreateUserInput` and `UpdateUserInput` MUST enforce required fields, length bounds, and valid role enum values. Username immutability MUST be enforced by the schema (sending `username` on update returns a schema error, not silent acceptance).

**SDK**:

- **FR-013**: SDK MUST expose `client.users.create`, `client.users.update`, `client.users.reset_password`, `client.users.delete`, `client.users.list(active=, role=, search=)`, `client.users.get(id)` mirroring the admin GraphQL surface.
- **FR-014**: SDK MUST expose `client.groups.create`, `client.groups.update`, `client.groups.delete`, `client.groups.list(search=)`, `client.groups.get(id)` mirroring the admin GraphQL surface.

**Frontend — authentication and routing**:

- **FR-015**: Frontend MUST provide an auth context (`AuthProvider`) that exposes `{ currentUser, loading, refresh, logout }` and renders a small loading indicator until the first `currentUser` response resolves on boot.
- **FR-016**: Frontend GraphQL fetcher MUST send the session cookie (`credentials: 'include'`), map GraphQL `extensions.code` to typed client errors, redirect to `/login` (and clear the auth context) on `UNAUTHENTICATED`, and surface a toast (without redirecting) on `FORBIDDEN`.
- **FR-017**: Frontend MUST add routes `/login`, `/profile`, `/users`, `/users/$id`, `/groups`, `/groups/$id`. Admin routes MUST redirect to `/` when `effectiveRole !== 'ADMIN'`; `/login` MUST redirect to `/` when the user is already authenticated.

**Frontend — header, profile, admin pages**:

- **FR-018**: Frontend MUST render the authenticated user's display name and an effective-role badge in the app header, with a header menu containing Profile and Logout items.
- **FR-019**: Profile page MUST allow the authenticated user to edit their own display name and to change their own password. Password change MUST require the current password and MUST invalidate **only** the user's *other* sessions (the calling session is preserved).
- **FR-020**: Users admin page MUST show a paginated (client-side) table with columns username, display name, role, group memberships, active status, and MUST support filtering by `active`, by `role`, and by free-text search across username and display name.
- **FR-021**: Groups admin page MUST mirror the Users page workflow (list, create, edit, delete, member management). The group edit form MUST allow setting role and replacing the full member set in a single submission.

**Frontend — role gating** ("hide-not-disable"; gating always reads **effective** role):

- **FR-022**: Frontend MUST hide (not disable) mutation buttons for users whose effective role is below the action's required minimum. Implementation surface is an `<IfRole minimum=...>` helper / `useEffectiveRole()` hook applied to existing mutation buttons and admin-only chrome.
- **FR-023**: Frontend MUST hide the Users and Groups nav entries for users whose effective role is below `ADMIN`.

**Login page**:

- **FR-024**: Login page MUST present a single form (username + password), call the login mutation on submit, refetch `currentUser` on success (routing transition handled by the auth context), and render the generic message "Invalid username or password." on failure.

**Documentation**:

- **FR-025**: Repository MUST ship a user-facing guide under `dev/guides/` covering the role model, default-admin bootstrap, and admin UI usage. The guide is part of this feature's definition of done.

**End-to-end coverage**:

- **FR-026**: Repository MUST ship a single auth-lifecycle E2E scenario that runs in both api-mode and ui-mode and exercises: log in as seeded admin → create `read_write` user → log in as that user → perform a `read_write`-permitted mutation (asserts success) → attempt an admin-only mutation (asserts `FORBIDDEN`). The ui-mode variant MUST drive the actual login form (no cookie injection).
- **FR-027**: Existing UI-mode E2E suite MUST adopt session-scoped Playwright cookie injection at session start so existing scenarios do not slow down or flake from the new auth requirement. The new auth-lifecycle scenario opts out of cookie injection.

**Deployment attribution exposed to drivers**:

- **FR-028**: System MUST expose `Deployment.createdBy.username` to deployment drivers (specifically the `UiScenarioDriver`) so a UI scenario can assert on attribution rendered in the UI.

### Key Entities

- **User**: A human principal with `id`, `username` (immutable post-create), `displayName`, `role` (`admin | read_write | read_only`), `active` flag, `groups` (membership), `effectiveRole` (derived: max of direct role and group-conferred roles), and audit timestamps. Admin-only fields are gated by `RequiresRole(ADMIN)`.
- **Group**: A named collection of users with a `role` that confers admin/read_write/read_only on its members. Admin gating applies to the entire `Group` type.
- **Session**: An authenticated browser/SDK token issued at login, invalidated by: explicit logout, admin-driven `resetUserPassword`, admin-driven deactivation (`updateUser.active = false`), and password change (all *other* sessions; calling session preserved). Sessions are created and consumed by #179; this feature only invalidates them in the listed paths.
- **AdminGuardState**: Conceptual view used by the last-admin guard: the count of currently active admin users (direct role `admin` or group-conferred admin via an active admin-conferring group). Operations are pre-checked against this view at request time.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An administrator can complete the **full user lifecycle** (create → edit → reset password → deactivate → reactivate → hard-delete an unreferenced user) entirely from the browser, with **zero SDK or database access**. Measured: the Phase 8 lifecycle E2E ui-mode variant passes.
- **SC-002**: A `read_only` user opening the app sees **no mutation buttons and no admin nav entries** in the DOM. Measured: rendered HTML contains zero matches for the Users/Groups nav entry and for mutation buttons in any rendered page.
- **SC-003**: An operation that would leave zero active admins is rejected **100% of the time** across the four operation classes (deactivate, delete, demote, group-removal) and across self-vs-other. Measured: the unit-test matrix for `would_leave_zero_admins` covers all role × active × actor permutations with zero false positives or negatives.
- **SC-004**: The auth-lifecycle E2E scenario passes in **both** api-mode and ui-mode in CI.
- **SC-005**: Admin password reset on a target user invalidates **all** of that target's existing sessions in the same transaction. Measured: an integration test that issues a session for the target, calls `resetUserPassword`, and asserts the prior session is rejected.
- **SC-006**: Self password change invalidates **only** the user's *other* sessions; the calling session continues to work. Measured: integration test with two sessions for the same user — change password from session A, assert session A still works and session B is rejected.
- **SC-007**: Existing UI-mode E2E scenarios show **no measurable runtime regression** after introducing cookie-injection-at-session-start (the auth requirement adds no per-test overhead). Measured: CI elapsed-time delta for the suite is ≤ +5% versus the pre-#180 baseline.
- **SC-008**: A new operator can read the `dev/guides/` guide and complete the admin-bootstrap → create-user → reset-password workflow **without reading source**. Measured: dry-run with a new operator (or a documentation-review subagent acting as one) finds no missing prerequisite step.

## Assumptions

- **#179 has shipped** and is on `develop` before this feature starts: the `User` and `Session` models, login/logout/`currentUser`/`changePassword` mutations, default-deny GraphQL, `RequiresRole` permission class, bootstrap of the default admin, password hashing, session token plumbing, audit FK propagation (`createdBy`), and the `STYRMIN_TOKEN` SDK env var are all in place.
- **Frontend stack is TanStack Router + TanStack Query + a custom `graphqlFetcher`** (per ADR-011), **not** urql. Auth wiring extends `graphqlFetcher` rather than introducing a new GraphQL client or a separate exchange.
- **Three roles only**: `admin`, `read_write`, `read_only`. No per-resource ACLs, no attribute-based access control, no service accounts, no API tokens — those are explicit out-of-scope items.
- **`Deployment.createdBy` already exists** from #179's audit FK propagation; this feature only adds `username` exposure to drivers (FR-028), not a new column.
- **"Hide-not-disable" is a UX choice**, not a security boundary. The backend remains the source of truth and rejects unauthorized mutations regardless of which buttons render. Frontend gating reduces visual clutter and never substitutes for backend enforcement.
- **Client-side pagination is acceptable for v1** because the user/group population in initial deployments is small (tens to low hundreds). Server-side cursor pagination is explicitly out of scope; revisit when scale justifies it.
- **Existing E2E scenarios already use a `session_scenario_driver` whose `StyrminClient` is token-injected by #179**. This feature adds the auth-lifecycle scenario alongside that infrastructure and switches existing UI-mode tests to Playwright cookie injection at session start.
- **The `auth/admin_guards` module is shipped by this feature** (not #179), as pure functions that the admin mutations call into. Pure-function design enables table-driven unit tests without a database.
- **The `auth/membership` module is shipped by this feature** (not #179) and implements set-semantics replacement for both `user → groups` and `group → members`.
- **No email-based password reset, no MFA, no brute-force lockout, no "log out everywhere" UI, no audit-log table, no SSO/OIDC/SAML, no CLI `styrmin login` subcommand**. All explicitly out of scope.
- **CI machine baseline is stable enough to measure the ≤ +5% E2E elapsed-time bound in SC-007** with a single comparison run; if CI noise is high we accept a 10% bound and document the observed delta.
