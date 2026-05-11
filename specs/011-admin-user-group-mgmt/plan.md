# Implementation Plan: Admin User & Group Management

**Branch**: `011-admin-user-group-mgmt` | **Date**: 2026-05-11 | **Spec**: [./spec.md](./spec.md)
**Input**: Feature specification from `/specs/011-admin-user-group-mgmt/spec.md`

## Summary

Build the admin tooling on top of the auth foundation already in place from #179 (`User`, `Group`, `Session`, `UserGroup` SQLModel tables; `RequiresRole` permission class; `login` / `logout` / `currentUser` / `changePassword` resolvers; `Role` GraphQL enum and `User.from_instance`/`Group.from_instance` types; password hashing; session lifecycle; default-admin bootstrap; `Deployment.createdBy` audit FK with role-gated read). This feature adds:

1. **Backend**: admin-only GraphQL mutations and queries (`createUser`, `updateUser`, `resetUserPassword`, `deleteUser`, `createGroup`, `updateGroup`, `deleteGroup`, `users`, `groups`), two new service modules (`auth/admin_guards`, `auth/membership`), structured-error codes for the new failure cases, and exposure of `Deployment.createdBy.username` to `UiScenarioDriver`.
2. **SDK**: `client.users.*` and `client.groups.*` resource namespaces with `.graphql` operation files and ariadne-codegen-generated typed models.
3. **Frontend**: `AuthProvider` + `useAuth` over TanStack Query; `graphqlFetcher` rewrite to send the session cookie and to map `extensions.code` to typed errors (UNAUTHENTICATED → redirect+clear, FORBIDDEN → toast); new routes `/login`, `/profile`, `/users`, `/users/$id`, `/groups`, `/groups/$id` wired through the existing `routeTree.ts`; header user menu with display-name + role badge + Profile/Logout; `IfRole` helper + `useEffectiveRole` hook applied to existing mutation buttons; admin guards on the new routes via `beforeLoad`.
4. **Docs**: `dev/guides/users-and-groups.md` walking through roles, bootstrap, admin UI usage.
5. **E2E**: dual-entrypoint `test_auth_lifecycle.py` (api-mode + ui-mode, opts out of session-scoped cookie injection); switch the rest of the UI-mode suite to session-scoped Playwright cookie injection so the existing tests do not slow down.

## Technical Context

**Language/Version**: Python 3.14+ (backend, SDK), TypeScript 5.9.3 + Node 22 (frontend)
**Primary Dependencies**: Strawberry GraphQL, SQLModel + SQLAlchemy async (backend); React 19, TanStack Router, TanStack Query, custom `graphqlFetcher` per ADR-011 (frontend); httpx + ariadne-codegen (SDK)
**Storage**: PostgreSQL via SQLModel — **no schema changes**; all required tables (`user`, `group`, `user_group`, `session`) already exist from #179.
**Testing**: pytest (unit + functional + e2e — `@pytest.mark.ci` for the lifecycle e2e); Vitest + React Testing Library (frontend); Playwright via the existing `ScenarioDriver` dual-entrypoint pattern.
**Target Platform**: Linux servers (backend), evergreen browsers (frontend), Python 3.14+ (SDK).
**Project Type**: Web application (`backend/` + `frontend/` + `python_sdk/`).
**Performance Goals**: client-side pagination over `users`/`groups` is acceptable while user count is in the tens-to-low-hundreds (per Out-of-Scope in spec). Login p95 already meets #179's bar; no new perf bar from this feature.
**Constraints**: zero schema migrations; `username` immutable post-create (schema-enforced); `RequiresRole(ADMIN)` on every admin mutation; the last-admin guard must be a pure function so it is unit-testable without a DB.
**Scale/Scope**: ~7 mutations, 2 queries, 2 new backend service modules, 1 SDK resource pair (`users` + `groups`), 6 new frontend routes (5 pages + login), 1 e2e test, 1 user guide.

## Constitution Check

| Principle | Check |
|---|---|
| **I. Declarative State Reconciliation** | N/A — admin mutations are imperative CRUD on a non-reconciled resource (`User`/`Group`). No driver involvement. |
| **II. Driver-Based Deployment** | N/A — no driver changes. FR-028 exposes an existing `Deployment.createdBy` field to drivers; no driver authoring. |
| **III. Layered Architecture** | PASS — GraphQL resolvers in `api/schema/mutation.py` and `api/schema/query.py` call service functions in `services/auth/`. The two new modules (`auth/admin_guards`, `auth/membership`) live in the services layer. The pure-function `admin_guards` is queried by service functions that load the necessary state from the repository. UnitOfWork coordinates each mutation. |
| **IV. Type Safety and Typed Errors** | PASS — all new service functions are typed; new structured-error subclasses (`UserNotFoundError`, `DuplicateUsernameError`, `LastAdminError`, `UserHasReferencesError`) extend `ServiceError` and surface as GraphQL `extensions.code`. No union types. |
| **V. Test-First Development** | PASS — feature ships a dual-entrypoint lifecycle E2E (`test_auth_lifecycle.py`) marked `@pytest.mark.ci`; unit tests for `auth/admin_guards` and `auth/membership`; functional tests for each mutation; propagation tests per `dev/guides/graphql-propagation-tests.md` for every new field/mutation. |
| **VI. Format and Lint Before Commit** | PASS — `uv run invoke format lint` and `pnpm lint` enforced via pre-commit and CI. |
| **Governance gates — Auth changes** | The auth foundation (#179) has merged. This feature consumes that foundation. The admin guards and membership modules are net-new authorization logic and ARE auth changes — they are documented here and in the spec; no further out-of-band approval is needed because issue #180 itself is the explicit authorization for this work. |
| **Governance gates — GraphQL schema modifications** | This feature adds 7 mutations, 2 queries, and a `Deployment.createdBy.username` field exposure — propagation tests are required per Principle V and are explicitly enumerated in Phase 1 contracts below. |
| **Governance gates — Database schema changes** | None. All tables already exist from #179. |

No constitutional violations to track.

## Project Structure

### Documentation (this feature)

```text
specs/011-admin-user-group-mgmt/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (GraphQL schema slice + SDK + frontend contracts)
│   ├── graphql.md
│   ├── sdk.md
│   └── frontend.md
└── tasks.md             # Phase 2 output (NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── api/
│   ├── auth/
│   │   └── allowlist.py                  # (no change — admin mutations require ADMIN, none added to allow-list)
│   ├── definitions/
│   │   └── user/
│   │       └── model.py                  # extend with CreateUserInput, UpdateUserInput, CreateGroupInput, UpdateGroupInput
│   └── schema/
│       ├── mutation.py                   # add createUser/updateUser/resetUserPassword/deleteUser + createGroup/updateGroup/deleteGroup
│       └── query.py                      # add users(active, role, search) + groups(search)
├── services/
│   ├── auth/
│   │   ├── admin_guards.py               # NEW — pure functions: would_leave_zero_admins, can_hard_delete_user
│   │   ├── membership.py                 # NEW — replace_user_groups, replace_group_members (set-semantics)
│   │   ├── users.py                      # NEW — create/update/reset_password/delete service functions
│   │   └── groups.py                     # NEW — create/update/delete service functions
│   └── exceptions.py                     # add LastAdminError, DuplicateUsernameError, UserHasReferencesError
└── tests/
    ├── unit/auth/
    │   ├── test_admin_guards.py          # NEW — table-driven
    │   └── test_membership.py            # NEW
    ├── functional/auth/
    │   ├── test_admin_user_mutations.py  # NEW — propagation + role gating
    │   └── test_admin_group_mutations.py # NEW — propagation + role gating
    └── e2e/
        ├── test_auth_lifecycle.py        # NEW — dual-entrypoint, opts OUT of cookie injection
        └── pages/
            ├── login.py                  # NEW — LoginPage page object
            └── users_admin.py            # NEW — UsersAdminPage page object

python_sdk/
├── src/styrmin_sdk/
│   ├── client.py                          # register users + groups resources
│   ├── graphql/                            # snake_case .graphql files (one per operation)
│   │   ├── create_user.graphql
│   │   ├── update_user.graphql
│   │   ├── reset_user_password.graphql
│   │   ├── delete_user.graphql
│   │   ├── list_users.graphql
│   │   ├── get_user.graphql
│   │   ├── create_group.graphql
│   │   ├── update_group.graphql
│   │   ├── delete_group.graphql
│   │   ├── list_groups.graphql
│   │   └── get_group.graphql
│   └── resources/
│       ├── users.py                       # NEW
│       └── groups.py                      # NEW
└── tests/
    ├── test_resources_users.py            # NEW — round-trip through generated models
    └── test_resources_groups.py           # NEW

frontend/
├── src/
│   ├── auth/                              # NEW
│   │   ├── AuthProvider.tsx
│   │   ├── useAuth.ts
│   │   ├── IfRole.tsx
│   │   └── useEffectiveRole.ts
│   ├── lib/
│   │   ├── graphql-fetcher.ts             # extend: credentials: 'include' + extensions.code mapping
│   │   └── graphql-fetcher.test.ts        # extend: UNAUTHENTICATED redirect + FORBIDDEN toast
│   ├── components/
│   │   ├── AppShell.tsx                   # add user menu (display name, role badge, Profile, Logout)
│   │   └── HeaderUserMenu.tsx             # NEW
│   ├── pages/
│   │   ├── login/                         # NEW
│   │   │   └── LoginPage.tsx
│   │   ├── profile/                       # NEW
│   │   │   └── ProfilePage.tsx
│   │   ├── users/                         # NEW (mirrors backup-storage-locations pattern)
│   │   │   ├── UsersListPage.tsx
│   │   │   └── UserDetailPage.tsx
│   │   └── groups/                        # NEW
│   │       ├── GroupsListPage.tsx
│   │       └── GroupDetailPage.tsx
│   ├── routes/
│   │   ├── login.tsx                      # NEW — beforeLoad: redirect to / when authenticated
│   │   ├── profile.tsx                    # NEW
│   │   ├── usersList.tsx                  # NEW — beforeLoad: redirect / when not admin
│   │   ├── userDetail.tsx                 # NEW
│   │   ├── groupsList.tsx                 # NEW
│   │   └── groupDetail.tsx                # NEW
│   ├── routeTree.ts                       # register the 6 new routes + auth context
│   ├── router.ts                          # add `context` parameter so beforeLoad can read auth
│   └── App.tsx                            # wrap RouterProvider with AuthProvider
└── src/__tests__/
    ├── AuthProvider.test.tsx              # NEW
    ├── IfRole.test.tsx                    # NEW
    ├── LoginPage.test.tsx                 # NEW
    ├── ProfilePage.test.tsx               # NEW
    └── UsersListPage.test.tsx             # NEW

dev/guides/
└── users-and-groups.md                    # NEW — roles, bootstrap, admin UI walkthrough
```

**Structure Decision**: Web application layout (`backend/` + `frontend/` + `python_sdk/`) — already established by the project. This feature only adds files inside the existing layout. No top-level reshuffling.

## Phase 0 — Outline & Research

See [research.md](./research.md) for the consolidated findings. Summary of decisions:

1. **Admin guards as pure functions over a snapshot view**: `would_leave_zero_admins(action, target_user_id, snapshot)` and `can_hard_delete_user(user_id, fk_refs_present)` accept the relevant state explicitly so unit tests pass synthetic snapshots and assert outcomes without a DB. The service-layer wrapper assembles the snapshot from the repository in a single query.
2. **Set-semantics membership replacement in one transaction**: load current set → compute diff → INSERT new rows + DELETE removed rows → commit. No-change paths produce zero INSERT/DELETE statements (verified by counting the SQL log in the unit test).
3. **`graphqlFetcher` redirect on UNAUTHENTICATED**: the fetcher reads `errors[0].extensions.code`, calls a `signalUnauthenticated` callback registered by `AuthProvider` (clears the React Query cache + navigates to `/login`), and re-throws so the calling hook does not enter the success branch with stale data.
4. **TanStack Router admin guards**: `beforeLoad: ({ context }) => { if (context.auth.currentUser?.effectiveRole !== 'ADMIN') throw redirect({ to: '/' }) }`. Auth context is registered on the router via `router.update({ context: { auth } })` from inside `AuthProvider` so guards always see fresh state.
5. **Cookie-injection at session start for existing E2E**: implement a new `e2e/fixtures/auth.py` fixture that takes a Playwright browser context once per pytest session, logs in via SDK, extracts the cookie, and calls `context.add_cookies(...)`. The auth-lifecycle test marks itself `pytest.mark.no_cookie_injection` to opt out.
6. **No new database schema**: every required field, table, and FK is already in place from #179. Membership uses the existing `UserGroup` link table.
7. **No allow-list changes**: every admin mutation declares `RequiresRole(ADMIN)`; no new public/agent allow-list entries.

## Phase 1 — Design & Contracts

See:

- [data-model.md](./data-model.md) — User / Group / Session / UserGroup (existing); CreateUserInput / UpdateUserInput / CreateGroupInput / UpdateGroupInput (new); admin-snapshot view used by guards.
- [contracts/graphql.md](./contracts/graphql.md) — full GraphQL slice (types, inputs, mutations, queries) and propagation-test matrix.
- [contracts/sdk.md](./contracts/sdk.md) — SDK `client.users.*` and `client.groups.*` signatures and `.graphql` operation file list.
- [contracts/frontend.md](./contracts/frontend.md) — `AuthProvider` API, `graphqlFetcher` extension points, `IfRole` API, route map.
- [quickstart.md](./quickstart.md) — operator dry-run for the feature: bootstrap admin → log in via UI → create a user → reset password → deactivate → reactivate → delete; plus the lifecycle E2E recipe.

**Agent context update**: between the `<!-- SPECKIT START -->` and `<!-- SPECKIT END -->` markers in `CLAUDE.md`, point at this plan file (`specs/011-admin-user-group-mgmt/plan.md`). The `## Active Technologies` and `## Recent Changes` blocks below the markers are updated by Phase 4 tasks, not here.

## Complexity Tracking

No constitutional violations to justify. The pure-function `admin_guards` module is the closest thing to a deviation — it duplicates a small amount of state inspection that *could* be inlined in each mutation — but the duplication is intentional: pure functions are table-driven testable without a DB, and inlining would lose that. This is consistent with Principle III (the service layer is allowed thin pure helpers).
