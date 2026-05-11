---

description: "Tasks for 011-admin-user-group-mgmt — admin user & group management (issue #180)"
---

# Tasks: Admin User & Group Management

**Input**: Design documents from `/specs/011-admin-user-group-mgmt/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md (all present)

**Tests**: Generated. The spec mandates unit + functional + propagation + E2E coverage (Constitution §V); tests are part of the definition of done.

**Organization**: Tasks are grouped by user story. Each story is independently testable per the Independent Test criteria in spec.md. The MVP is US1 (browser session) — once US1 lands, the frontend has a real authenticated experience even though admin tooling is not yet there.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Parallelizable (different files, no dependencies on incomplete tasks).
- **[Story]**: US1, US2, ..., US8 — maps to the eight user stories in spec.md.
- Every task carries the exact file path the change lands in.

## Path Conventions

Web-app layout per plan.md: `backend/`, `frontend/`, `python_sdk/`, `dev/guides/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify the auth foundation from #179 is on the branch and that local tooling is ready. There is **no new project initialization** in this feature.

- [X] T001 Verify #179 is merged into the base branch: confirm `backend/styrmin_backend/db/models.py` contains `User`, `Group`, `Session`, `UserGroup`, `Role`; `services/auth/{login,session,password,password_change,bootstrap,roles}.py` exist; `api/auth/{allowlist,extensions,permissions}.py` exist; `api/definitions/user/model.py` exports `User`, `Group`, `Role`, `LoginResult`. If any are missing, STOP — this feature depends on #179.
- [X] T002 [P] Run `uv sync && cd frontend && pnpm install` and confirm `uv run invoke generate` succeeds against the current schema (baseline for codegen). No changes expected at this stage.
- [X] T003 [P] Run `uv run invoke format lint` and `cd frontend && pnpm lint` to confirm the working tree is green before changes start.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Cross-cutting modules every user story depends on: typed exceptions, the password-masking middleware, the admin guards, the membership module, the new GraphQL input types, and the `graphqlFetcher` cookie + error-mapping rewrite. No user story can begin its backend or frontend work until these land.

**⚠️ CRITICAL**: No user-story task may start until Phase 2 is complete.

### Backend foundational

- [X] T004 [P] Add new `ServiceError` subclasses (`UserNotFoundError`, `GroupNotFoundError`, `DuplicateUsernameError`, `DuplicateGroupNameError`, `LastAdminError`, `UserHasReferencesError`) in `backend/styrmin_backend/services/exceptions.py` with `error_code` set to `USER_NOT_FOUND`, `GROUP_NOT_FOUND`, `DUPLICATE_USERNAME`, `DUPLICATE_GROUP_NAME`, `LAST_ADMIN`, `USER_HAS_REFERENCES` respectively, plus matching `default_message`.
- [X] T005 [P] Create `backend/styrmin_backend/api/logging/__init__.py` and `backend/styrmin_backend/api/logging/mask.py` exporting `MASKED_VARIABLE_NAMES: frozenset[str] = frozenset({"password", "newPassword", "currentPassword"})` and a helper `mask_variables(variables: dict) -> dict` that returns a deep-copied dict with masked field values replaced by `"***"`. Per research.md D13 / FR-029.
- [X] T006 [US2-foundation] Wire `mask_variables(...)` into the GraphQL request-logging middleware (find the existing middleware that records request bodies — likely under `backend/styrmin_backend/server/` or `backend/styrmin_backend/api/`; depends on T005). On every request, before the log emit, replace `variables` with the masked copy.
- [X] T007 [P] Create the `auth/admin_guards.py` pure-function module at `backend/styrmin_backend/services/auth/admin_guards.py`: `AdminAction` enum (`DEACTIVATE | DELETE | DEMOTE | REMOVE_FROM_ADMIN_GROUP`), `AdminSnapshot` frozen dataclass per data-model.md, `would_leave_zero_admins(action, target_user_id, snapshot) -> bool`, `can_hard_delete_user(user_id, fk_refs_present) -> bool`. No DB imports — pure functions only.
- [X] T008 [P] Unit-test the guards in `backend/tests/unit/auth/test_admin_guards.py`: table-driven matrix covering deactivate-only-admin, deactivate-one-of-two, demote-only-admin, demote-one-of-two, remove-only-admin-from-only-admin-group, self-demote, self-deactivate, self-delete, admin-via-group-only as last admin, all role × active × actor permutations. Each row: synthetic `AdminSnapshot` + expected boolean. Use pytest.mark.parametrize.
- [X] T009 [P] Create the `auth/membership.py` module at `backend/styrmin_backend/services/auth/membership.py`: `async def replace_user_groups(uow, *, user_id, group_ids) -> tuple[int, int]` and `async def replace_group_members(uow, *, group_id, member_ids) -> tuple[int, int]`. Diff-and-mutate in a single transaction. No-change → `(0, 0)` with zero INSERT/DELETE statements.
- [X] T010 [P] Unit-test membership replacement in `backend/tests/unit/auth/test_membership.py`: empty→populated, populated→different-populated, populated→empty, no-change is no-op. Use `sqlalchemy.event.listens_for(engine, "before_execute")` to count INSERT and DELETE statements; assert zero on no-change.
- [X] T011 [P] Extend `backend/styrmin_backend/api/definitions/user/model.py` with the four new input types: `CreateUserInput`, `UpdateUserInput`, `CreateGroupInput`, `UpdateGroupInput`. Field shapes per data-model.md and contracts/graphql.md. `UpdateUserInput` has NO `username` field. Validation for length / charset / role-enum runs in the service layer; declare types only here.
- [X] T012 [US2-foundation] Regenerate `schema.graphql` at repo root via `uv run styrmin export graphql-schema schema.graphql` (depends on T011). Verify the new inputs appear in the diff; commit the updated schema.

### Frontend foundational

- [X] T013 [P] Extend `frontend/src/lib/graphql-fetcher.ts`: add `credentials: 'include'` to the `fetch` options; introduce `GraphQLOperationError`, `UnauthenticatedError`, `ForbiddenError`; introduce `setUnauthenticatedHandler(cb)` module-scope state; map `errors[0].extensions.code` per research.md D3. Preserve `GraphQLTransportError` behavior. Per contracts/frontend.md.
- [X] T014 [P] Extend `frontend/src/lib/graphql-fetcher.test.ts`: add the four new cases per contracts/frontend.md (credentials include sent; UNAUTHENTICATED calls handler + throws; FORBIDDEN throws without calling handler; unknown code preserves `code`).
- [X] T015 Create `frontend/src/auth/AuthProvider.tsx` exporting `AuthProvider` component and the `useAuth` hook. Boots by issuing `currentUser` query; renders a centered spinner until the first response; registers `setUnauthenticatedHandler(...)` that calls `queryClient.clear()` + `router.navigate({ to: '/login' })`; pushes auth into `router.update({ context: { auth } })` on every change. Depends on T013.
- [X] T016 [P] Create `frontend/src/auth/useEffectiveRole.ts` exporting `useEffectiveRole()` that reads `useAuth().currentUser?.effectiveRole ?? null`.
- [X] T017 [P] Create `frontend/src/auth/IfRole.tsx` exporting `<IfRole minimum={Role} fallback={ReactNode?}>`. Uses `useEffectiveRole()`; compares `READ_ONLY < READ_WRITE < ADMIN`; renders children when effective ≥ minimum, else fallback (default: null).
- [X] T018 [P] Test `frontend/src/auth/IfRole.test.tsx`: hide/show by minimum; admin-via-group user with direct READ_ONLY but effectiveRole=ADMIN renders ADMIN-minimum content.
- [X] T019 [P] Test `frontend/src/auth/AuthProvider.test.tsx`: (a) spinner before first response; (b) null currentUser → children not rendered (login route handles UI); (c) authenticated user → children rendered; (d) UNAUTHENTICATED later → handler invoked + queryClient.clear() called + router.navigate('/login') called.

**Checkpoint**: All cross-cutting plumbing is in place. User stories can now proceed in parallel.

---

## Phase 3: User Story 1 — Authenticated session in the browser (Priority: P1) 🎯 MVP

**Goal**: A browser user lands on `/login` when unauthenticated, can log in via the form, sees their display name + role badge + Profile/Logout menu in the header, and is redirected back to `/login` (without a confusing toast) when their session expires.

**Independent Test**: Navigate to `/` unauthenticated → land on `/login` → submit valid credentials → arrive at `/` with display-name + role badge in the header → open header menu and see Profile + Logout → click Logout → land back on `/login`. Then forcibly delete the session row in DB → next click triggers an `UNAUTHENTICATED` and redirects to `/login` (no error toast).

### Tests for US1

- [ ] T020 [P] [US1] `frontend/src/__tests__/LoginPage.test.tsx`: (a) happy path triggers `login` mutation + `currentUser` refetch; (b) error path renders the literal string "Invalid username or password."; (c) submit disabled while in flight.
- [ ] T021 [P] [US1] `frontend/src/__tests__/HeaderUserMenu.test.tsx`: renders display name + role badge derived from `effectiveRole`; clicking Logout invokes the supplied handler.

### Implementation for US1

- [ ] T022 [P] [US1] Create `frontend/src/pages/login/LoginPage.tsx` per contracts/frontend.md: single form, calls `login` mutation via `graphqlFetcher`, refetches `currentUser` on success, renders the generic error on failure. Use Radix UI primitives consistent with existing pages.
- [ ] T023 [P] [US1] Create `frontend/src/components/HeaderUserMenu.tsx` per contracts/frontend.md: props `{ user, onLogout }`, shows display name (truncated >20 chars), role badge from `effectiveRole`, dropdown with Profile (navigates to `/profile`) and Logout (calls `onLogout`).
- [ ] T024 [US1] Wire `HeaderUserMenu` into `frontend/src/components/AppShell.tsx`: consume `useAuth()`, render to the right of the existing theme toggle, hide when `currentUser` is null. The header must still render when on `/login` but `HeaderUserMenu` must NOT.
- [ ] T025 [US1] Create `frontend/src/routes/login.tsx` exporting `loginRoute`: path `/login`, `beforeLoad: ({ context }) => { if (context.auth.currentUser != null) throw redirect({ to: '/' }); }`, component `<LoginPage />`. Add to `routeTree.ts` and `router.ts` (register `context.auth` typing).
- [ ] T026 [US1] Update `frontend/src/routes/__root.tsx` to require authentication for every route except `/login` and `/profile`: `beforeLoad: requireAuth` (a helper that throws `redirect({ to: '/login' })` when `context.auth.currentUser == null`). `/profile` requires authenticated but not admin.
- [ ] T027 [US1] Update `frontend/src/App.tsx` to wrap `<RouterProvider />` with `<AuthProvider />` so the auth context is available before routing begins.
- [ ] T028 [US1] Manually run `uv run invoke dev` and verify the browser flow end-to-end: unauthenticated → /login, valid creds → /, invalid creds → generic error, header menu visible with name + role + Profile + Logout, click Logout → /login. Document the manual check in the PR description; this is the visible MVP.

**Checkpoint**: US1 is fully functional. The browser experience is now authenticated end-to-end; everything that follows extends from here.

---

## Phase 4: User Story 2 — Admin manages users (Priority: P1)

**Goal**: An admin can list, filter, create, edit, reset password, deactivate/reactivate, and hard-delete users from `/users` and `/users/$id`. Last-admin guard and FK-reference guard apply.

**Independent Test**: Per spec § US2 Independent Test — happy path + the four guard rejections.

### Backend — admin user mutations (depends on Phase 2 T004–T012)

- [ ] T029 [P] [US2] Create `backend/styrmin_backend/services/auth/users.py` exposing `async def create_user(uow, *, input)`, `async def update_user(uow, *, user_id, input, actor_user_id)`, `async def reset_user_password(uow, *, user_id, new_password)`, `async def delete_user(uow, *, user_id)`, `async def list_users(uow, *, active, role, search)`, `async def get_user(uow, *, user_id)`. Each function:
  - Loads `AdminSnapshot` via `SELECT ... FOR UPDATE` on admin-conferring rows (per research.md D1 concurrency strategy) when the mutation can affect admin state.
  - Calls `would_leave_zero_admins(...)` / `can_hard_delete_user(...)` from `admin_guards`.
  - For `update_user` with `active=False` or `reset_user_password`: writes password/active first, then calls `delete_all_sessions_for_user`, then commits once (per research.md D15).
  - Emits the audit log line per FR-030 on success: `logger.info("admin_mutation actor={} action={} target={} changed_fields={}", ...)`.
  - Uses `selectinload(User.groups)` for `list_users` per research.md D16.
  - Calls `replace_user_groups` from `auth/membership` when `input.group_ids` is present.
- [ ] T030 [P] [US2] Add to `backend/styrmin_backend/api/schema/mutation.py`: `create_user`, `update_user`, `reset_user_password`, `delete_user` mutations each declaring `extensions=[_requires(Role.ADMIN)]` and calling the service functions in `services/auth/users.py`. Map `DuplicateUsernameError`, `LastAdminError`, `UserHasReferencesError`, etc. via the existing `StructuredErrorExtension` middleware (no schema-level changes needed — the error_code on the exception flows through).
- [ ] T031 [P] [US2] Add to `backend/styrmin_backend/api/schema/query.py`: `users(active: Boolean, role: Role, search: String) -> [User!]!` field declaring `extensions=[_requires(Role.ADMIN)]`. Resolver delegates to `list_users(...)`.
- [ ] T032 [US2] Regenerate `schema.graphql` (depends on T030, T031). Confirm the diff matches contracts/graphql.md.

### Backend tests for US2

- [ ] T033 [P] [US2] Propagation + happy-path tests in `backend/tests/functional/auth/test_admin_user_mutations.py`: cover every test in contracts/graphql.md propagation matrix for users (`test_create_user_propagation`, `test_update_user_*_propagation`, `test_reset_user_password_propagation`, `test_delete_user_propagation`, `test_users_query_filters_propagation`, `test_create_user_canonicalizes_username`, `test_create_user_duplicate_returns_structured_error`, `test_deactivate_invalidates_sessions`, `test_reset_password_invalidates_all_sessions`, `test_delete_user_blocked_by_fk`).
- [ ] T034 [P] [US2] Role-gating tests in the same file: for each admin mutation/query, assert `UNAUTHENTICATED` (no session), `FORBIDDEN` (read_write), `FORBIDDEN` (read_only), success (admin) — matrix from contracts/graphql.md.
- [ ] T035 [P] [US2] Concurrency test `test_concurrent_demote_last_admin_serialized` in `backend/tests/functional/auth/test_last_admin_concurrency.py`: two async tasks call `update_user` to demote two different admins in an active pair; assert at least one raises `LastAdminError`. Use `asyncio.gather` with `return_exceptions=True`.
- [ ] T036 [P] [US2] Atomic-on-failure tests `test_reset_password_atomic_under_failure` and `test_deactivate_user_atomic_under_failure` in the same file as T033: monkeypatch `delete_all_sessions_for_user` to raise; assert neither the password change nor any session deletion is observable post-rollback.
- [ ] T037 [P] [US2] N+1 protection test `test_list_users_eager_loads_groups` in `backend/tests/functional/auth/test_users_query_eager_loading.py`: seed 10 users with varied memberships; capture executed SQL via SQLAlchemy event listener; assert exactly 2 queries (users + memberships).
- [ ] T038 [P] [US2] Audit-log test `test_admin_mutation_emits_audit_line` in `backend/tests/functional/auth/test_admin_user_mutations.py`: capture Loguru output; for each successful admin mutation, assert one `admin_mutation` log line with the expected `actor`, `action`, `target`, `changed_fields`. Also `test_admin_mutation_no_audit_on_rollback`: mutation that raises emits no audit line.

### SDK glue for US2 (so the frontend tests + e2e can drive the admin paths)

- [ ] T039 [P] [US2] Create the SDK `.graphql` files under `python_sdk/src/styrmin_sdk/graphql/`: `create_user.graphql`, `update_user.graphql`, `reset_user_password.graphql`, `delete_user.graphql`, `list_users.graphql`, `get_user.graphql`. Operation bodies per contracts/sdk.md.
- [ ] T040 [P] [US2] Create `python_sdk/src/styrmin_sdk/resources/users.py` exposing `UserResource(BaseResource)` with `create`, `update`, `reset_password`, `delete`, `list`, `get`. Mirrors contracts/sdk.md.
- [ ] T041 [US2] Register `self.users = UserResource(self._transport)` in `python_sdk/src/styrmin_sdk/client.py` (depends on T040).
- [ ] T042 [US2] Run `uv run invoke generate` to regenerate `python_sdk/src/styrmin_sdk/graphql/_generated/` (depends on T032, T039).
- [ ] T043 [P] [US2] SDK test `python_sdk/tests/test_resources_users.py`: create round-trip, update clears groups (`group_ids=[]`), reset_password returns true, delete raises `USER_HAS_REFERENCES`, list with filters, FORBIDDEN for non-admin token.

### Frontend for US2

- [ ] T044 [P] [US2] Add `.graphql` operations under `frontend/src/graphql/` (snake_case): the same six operations as the SDK, but consumed by `graphqlFetcher` + TanStack Query. (Frontend uses the operation strings directly via `graphqlFetcher`.)
- [ ] T045 [P] [US2] Create `frontend/src/pages/users/UsersListPage.tsx` per contracts/frontend.md: query `users(active, role, search)`, filter row, table with client-side pagination (25 rows/page), "Create user" button opens a dialog form. Mirror `pages/backup-storage-locations/` structure.
- [ ] T046 [P] [US2] Create `frontend/src/pages/users/UserDetailPage.tsx`: inline-edit display name, role, active, group memberships (multi-select of `groups()`). Reset-password and Delete-user buttons with confirmation. Surface server `LAST_ADMIN` / `USER_HAS_REFERENCES` errors as toasts AND inline on the affected field (per FR-010 edge case in spec).
- [ ] T047 [P] [US2] Create `frontend/src/routes/usersList.tsx` and `frontend/src/routes/userDetail.tsx` with admin `beforeLoad` guards per research.md D4. Register in `routeTree.ts`.
- [ ] T048 [P] [US2] Test `frontend/src/__tests__/UsersListPage.test.tsx`: renders rows from query; role filter updates query variables; client-side pagination shows 25 rows per page.
- [ ] T049 [US2] Update navigation in `AppShell.tsx`: add "Users" link wrapped in `<IfRole minimum="ADMIN">` (depends on T017).

**Checkpoint**: An admin can complete the full user lifecycle via `/users` and `/users/$id`. The lifecycle-test scenario for users is now sufficient.

---

## Phase 5: User Story 3 — Admin manages groups (Priority: P1)

**Goal**: An admin can list, filter, create, edit (role + full member set replacement), and delete groups from `/groups` and `/groups/$id`. Last-admin guard applies to group changes that affect admin-conferring memberships.

**Independent Test**: Per spec § US3 Independent Test.

### Backend — admin group mutations

- [ ] T050 [P] [US3] Create `backend/styrmin_backend/services/auth/groups.py` exposing `create_group`, `update_group`, `delete_group`, `list_groups`, `get_group`. Same patterns as `users.py` from T029: lock admin-conferring rows FOR UPDATE when the operation touches admin state; call `would_leave_zero_admins` with `action=REMOVE_FROM_ADMIN_GROUP` for member-set changes against an admin-conferring group; call `replace_group_members(...)` from `auth/membership` when `input.member_ids` is present; emit FR-030 audit log line.
- [ ] T051 [P] [US3] Add to `mutation.py`: `create_group`, `update_group`, `delete_group` each `extensions=[_requires(Role.ADMIN)]`.
- [ ] T052 [P] [US3] Add to `query.py`: `groups(search: String) -> [Group!]!` admin-gated.
- [ ] T053 [US3] Regenerate `schema.graphql` (depends on T051, T052).

### Backend tests for US3

- [ ] T054 [P] [US3] `backend/tests/functional/auth/test_admin_group_mutations.py`: propagation matrix from contracts/graphql.md (create/update/delete/list/get; name, role, member_ids replacement). Role-gating matrix. Last-admin rejection on group changes. Audit-log lines.

### SDK glue for US3

- [ ] T055 [P] [US3] Create the SDK `.graphql` files for groups: `create_group.graphql`, `update_group.graphql`, `delete_group.graphql`, `list_groups.graphql`, `get_group.graphql`.
- [ ] T056 [P] [US3] Create `python_sdk/src/styrmin_sdk/resources/groups.py`.
- [ ] T057 [US3] Register `self.groups = GroupResource(self._transport)` in `client.py` (depends on T056).
- [ ] T058 [US3] Re-run `uv run invoke generate` (depends on T053, T055).
- [ ] T059 [P] [US3] SDK test `python_sdk/tests/test_resources_groups.py` mirroring T043.

### Frontend for US3

- [ ] T060 [P] [US3] Add frontend `.graphql` operations for groups under `frontend/src/graphql/`.
- [ ] T061 [P] [US3] Create `frontend/src/pages/groups/GroupsListPage.tsx` and `frontend/src/pages/groups/GroupDetailPage.tsx`. Detail page lets the admin set name, role, and `memberIds` (multi-select of `users(active=true)`). Member list uses set semantics on submission.
- [ ] T062 [P] [US3] Create routes `frontend/src/routes/groupsList.tsx` and `frontend/src/routes/groupDetail.tsx` with admin `beforeLoad`. Register in `routeTree.ts`.
- [ ] T063 [US3] Add "Groups" nav link to `AppShell.tsx` wrapped in `<IfRole minimum="ADMIN">`.

**Checkpoint**: Group management is now complete; the admin tooling story is whole.

---

## Phase 6: User Story 4 — Profile page (Priority: P1)

**Goal**: Any authenticated user can edit their own display name and change their own password from `/profile`. Password change invalidates other sessions only.

**Independent Test**: Per spec § US4 Independent Test.

### Frontend

- [ ] T064 [P] [US4] Create `frontend/src/pages/profile/ProfilePage.tsx` per contracts/frontend.md: read-only `username` field with helper text "Username cannot be changed — contact an admin." (per spec acceptance scenario #4), display-name edit form calling `updateUser(self.id, { displayName })`, change-password form calling existing `changePassword(currentPassword, newPassword)` from #179. `newPasswordConfirm` is a client-side check only.
- [ ] T065 [P] [US4] Create `frontend/src/routes/profile.tsx`: requires authenticated (inherited from root `beforeLoad`), no admin gate. Register in `routeTree.ts`.
- [ ] T066 [P] [US4] Test `frontend/src/__tests__/ProfilePage.test.tsx`: (a) display-name save calls `updateUser`; (b) password change happy path; (c) wrong-current-password renders inline error; (d) password-mismatch on confirm renders inline error without submitting.

**Checkpoint**: Profile page is reachable from the header menu (US1 T023) and works.

---

## Phase 7: User Story 5 — Role-gated UI (hide-not-disable) (Priority: P1)

**Goal**: `read_only` users see no mutation buttons or admin nav. `read_write` users see no admin-only buttons or admin nav. Direct navigation to admin routes redirects to `/`.

**Independent Test**: Per spec § US5 Independent Test.

### Frontend — wrap existing mutation buttons

- [ ] T067 [P] [US5] In `frontend/src/pages/backup-storage-locations/`, wrap every write-mutation button (`Create`, `Edit`, `Delete`) with `<IfRole minimum="READ_WRITE">`.
- [ ] T068 [P] [US5] In `frontend/src/pages/deployments/`, wrap every write-mutation button (Create deployment, Delete deployment, Upgrade, etc.) with `<IfRole minimum="READ_WRITE">`.
- [ ] T069 [P] [US5] In `frontend/src/pages/drivers/`, wrap every write-mutation button (Add driver, Delete) with `<IfRole minimum="READ_WRITE">`.
- [ ] T070 [P] [US5] In `frontend/src/pages/environments/`, wrap every write-mutation button (env-var update, create env, delete env, update config, etc.) with `<IfRole minimum="READ_WRITE">`.
- [ ] T071 [P] [US5] In `frontend/src/pages/settings/`, wrap any write actions with `<IfRole minimum="READ_WRITE">`.
- [ ] T072 [P] [US5] In `frontend/src/components/deployment/` and `frontend/src/components/environment/`, audit every component that renders a write button (Add/Edit/Delete/Save) and wrap appropriately. Use grep on `<Button` + `onClick` to enumerate.
- [ ] T073 [US5] Add a Vitest snapshot or RTL test in `frontend/src/__tests__/role_gating.test.tsx` that mounts the AppShell + a sample page with a `read_only` mock user and asserts no `<Button>` for write mutations appears (queryByText for "Create", "Delete", etc. returns null). Same for `read_write`: admin-only buttons absent. Same for ADMIN: all buttons present.

**Checkpoint**: Every page now honours effective role.

---

## Phase 8: User Story 8 — End-to-end auth lifecycle (Priority: P1)

**Goal**: Single dual-entrypoint E2E test passes in both api-mode and ui-mode. Existing UI-mode tests use session-scoped cookie injection.

**Independent Test**: `uv run pytest backend/tests/e2e/test_auth_lifecycle.py -v --pdb` passes in both `[api-chromium]` and `[ui-chromium]` variants.

### Implementation

- [ ] T074 [US8] Create `backend/tests/e2e/fixtures/auth.py` per research.md D5: session-scoped pytest fixture that logs in once as the seeded admin via SDK, captures the session cookie, and provides a callable `inject_session_cookie(context)` for per-test Playwright contexts. Honours `@pytest.mark.no_cookie_injection` (skip the inject on opt-out tests).
- [ ] T075 [US8] Update existing E2E `conftest.py` (`backend/tests/e2e/conftest.py`) to invoke `inject_session_cookie` on every new browser context that does NOT carry `no_cookie_injection`. This is the SC-007 structural-check requirement.
- [ ] T076 [P] [US8] Create `backend/tests/e2e/pages/login.py` with the `LoginPage` page object: `goto()`, `fill_username(value)`, `fill_password(value)`, `submit()`, `expect_error_message(text)`.
- [ ] T077 [P] [US8] Create `backend/tests/e2e/pages/users_admin.py` with the `UsersAdminPage` page object: `goto_list()`, `open_create_dialog()`, `fill_create_form(username, display_name, password, role)`, `submit()`, `find_row(username)`, `open_user(username)`, `set_active(value)`, `reset_password(new_password)`, `delete_user()`.
- [ ] T078 [US8] Create `backend/tests/e2e/test_auth_lifecycle.py`: marked `@pytest.mark.ci` and `@pytest.mark.no_cookie_injection`. Steps per spec § US8: log in as seeded admin → create read_write user → log in as that new user (api-mode: SDK login; ui-mode: drive `LoginPage`) → perform a `read_write`-permitted mutation (e.g., createEnvironment) and assert success → attempt an admin-only mutation (e.g., createUser) and assert `FORBIDDEN`. Use the dual-entrypoint `ScenarioDriver` pattern from existing E2E tests.
- [ ] T079 [US8] Run the full E2E suite locally with `sleep infinity | uv run pytest backend/tests/e2e/ -v -s --pdb 2>&1 | tee /tmp/e2e.log` and confirm: (a) `test_auth_lifecycle.py` passes in both `[api-chromium]` and `[ui-chromium]`; (b) every other existing UI-mode E2E test still passes with cookie injection. This is the SC-004 + SC-007 gate.

**Checkpoint**: The auth-lifecycle E2E is the explicit ask from issue #180 and is now green.

---

## Phase 9: User Story 6 — SDK parity (Priority: P2)

**Goal**: `client.users.*` and `client.groups.*` are usable as a public SDK surface.

The bulk of SDK work landed in T039–T043 (US2) and T055–T059 (US3) because both backend phases needed an SDK path for their own propagation tests. This phase covers any remaining polish.

### Implementation

- [ ] T080 [P] [US6] Verify the SDK exports `from styrmin_sdk import StyrminClient; client.users; client.groups` work in a fresh interpreter; add a smoke-test script under `python_sdk/examples/users_groups.py` matching the quickstart § E example.
- [ ] T081 [P] [US6] Update `python_sdk/AGENTS.md` (if it lists resources) with the new namespaces. (If the file already auto-enumerates, this is a no-op.)

**Checkpoint**: SDK is publishable; the lifecycle script in quickstart.md § E runs.

---

## Phase 10: User Story 7 — Operator documentation (Priority: P2)

**Goal**: `dev/guides/users-and-groups.md` walks a new operator through roles, bootstrap, admin UI usage.

### Implementation

- [ ] T082 [US7] Create `dev/guides/users-and-groups.md` covering: (a) the three roles (`READ_ONLY`, `READ_WRITE`, `ADMIN`) and "effective role" via group membership; (b) default-admin bootstrap (`STYRMIN_ADMIN_USERNAME` / `STYRMIN_ADMIN_PASSWORD` env vars; generated-password log line behavior); (c) admin UI walkthrough (mirror quickstart § A–D); (d) what to do when locked out (re-bootstrap via env var; no recovery flow in v1); (e) the SDK equivalent (quickstart § E); (f) "hide-not-disable" rationale and how to inspect via `effectiveRole`. Cross-link from `AGENTS.md` Navigation table if applicable.

**Checkpoint**: A new operator can self-serve without reading source (SC-008).

---

## Phase 11: User Story 29 mini — Deployment driver attribution (Priority: P1)

**Goal**: Expose `Deployment.createdByUsername: String` (nullable) so the `UiScenarioDriver` can assert on attribution in tests. Per FR-028.

### Implementation

- [ ] T083 [P] [US2] Add a `createdByUsername: str | None` field to the `Deployment` GraphQL type (look up the resolver in `backend/styrmin_backend/api/definitions/deployment/`; resolver projects `deployment.created_by.username` when the FK is non-null, else `None`). NOT admin-gated — driver-visible.
- [ ] T084 [US2] Regenerate `schema.graphql`.
- [ ] T085 [P] [US2] Propagation test `test_deployment_created_by_username_propagation` in `backend/tests/functional/test_deployments.py` (or the closest existing file): create a deployment as a non-admin authenticated user; assert `Deployment.createdByUsername == user.username`. Hard-delete the user via admin; assert the field becomes `None` (audits the SET NULL behaviour). For this test, ensure the user has no remaining FK references before the delete — temporarily delete the deployment row in the test, or rely on the existing `ondelete=SET NULL` if it is configured on the audit FK.

---

## Phase 12: Polish & Cross-Cutting Concerns

- [ ] T086 [P] Update `CLAUDE.md` "Active Technologies" and "Recent Changes" blocks to add `011-admin-user-group-mgmt`: Python 3.14+ + Strawberry + SQLModel + Loguru (backend); TypeScript + React + TanStack Router + TanStack Query (frontend); no schema changes. Append a Recent-Changes bullet.
- [ ] T087 [P] Run `uv run invoke validate-graphql` and confirm every new `.graphql` operation file passes schema validation.
- [ ] T088 [P] Run `uv run invoke format lint` and `cd frontend && pnpm lint` — must be green.
- [ ] T089 Run the full backend test suite: `uv run invoke test`. All new unit / functional / propagation / concurrency / atomic / N+1 / role-gating / audit-log tests must pass.
- [ ] T090 Run the full frontend test suite: `cd frontend && pnpm test`. All new Vitest cases must pass.
- [ ] T091 Run quickstart.md § A–E manually against `uv run invoke dev` and confirm every step works as written. Note any drift; update quickstart.md if any step is inaccurate.
- [ ] T092 Re-run `backend/tests/e2e/test_auth_lifecycle.py` after all other phases land to confirm no regression.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Independent.
- **Foundational (Phase 2)**: Depends on Setup. **Blocks all user stories.**
- **US1 / US2 / US3 / US4 / US5 / US6 / US7 / US8 / US11**: All depend on Phase 2.
  - **US1 is the MVP**: deliver it first to make the rest of the work visible.
  - **US2 and US3 can run in parallel** (different files, distinct backend service modules, distinct frontend pages).
  - **US4 depends on US1** because Profile is reached via the header menu (US1 T023 wires it).
  - **US5 depends on US1** because `IfRole` consumes `useAuth()` and admin-only nav assumes header chrome from US1.
  - **US6 (SDK polish) consumes US2 + US3** (resources + tests live there).
  - **US7 (docs) consumes US1–US5**.
  - **US8 (E2E) consumes US1–US5 and the seeded admin from #179**.
  - **US11 (createdByUsername) is logically a sub-task of US2** but is independent — runs in parallel.
- **Polish (Phase 12)**: depends on every user story.

### Within Each User Story

- Backend service functions before resolvers.
- Resolvers before SDK / frontend consumers.
- Tests (per Constitution §V) accompany each layer — write them in the same task or the immediately following task.

### Parallel Opportunities

- T004–T011 (foundational backend) all `[P]` — different files, no inter-dependency until T012 (schema regen) gathers them.
- T013–T019 (foundational frontend) all `[P]` after T013 lands.
- US2 backend (T029–T038) and US3 backend (T050–T054) run in parallel between two developers.
- US2 frontend (T044–T049) and US3 frontend (T060–T063) run in parallel after their respective backend resolvers exist.
- US5 button-wrapping (T067–T072) is naturally parallel — six independent file groups.

---

## Parallel Example: After Phase 2 Foundation Lands

```bash
# Developer A: US1 (MVP)
T020, T021 (tests) → T022, T023 (page + menu) → T024–T027 (route + wiring) → T028 (manual verify)

# Developer B: US2 (admin manages users)
T029 (service) || T039 (sdk graphql) → T030, T031 (resolvers) → T032 (regen) → T033–T038 (tests) || T040 (sdk resource) → T041 (client) → T042 (regen sdk) → T043 (sdk test) → T044 (frontend graphql) → T045–T048 (pages) → T049 (nav)

# Developer C: US3 (admin manages groups) — same pattern as Developer B
T050 || T055 → T051, T052 → T053 → T054 → T056 → T057 → T058 → T059 → T060 → T061–T062 → T063

# Developer D: US5 (role gating) — after US1 T017 (IfRole) lands
T067, T068, T069, T070, T071, T072 (all parallel) → T073 (role-gating test)
```

---

## Implementation Strategy

### MVP First (US1 only)

1. Phase 1 (Setup) + Phase 2 (Foundational).
2. Phase 3 (US1).
3. **STOP and validate**: the browser experience now has a real login flow, an authenticated header, and an UNAUTHENTICATED→/login redirect. This alone is a visible improvement even if no admin tooling exists yet (admins keep using SDK).

### Incremental Delivery

1. MVP (US1).
2. US2 (admin user management) → demo: full user lifecycle in browser.
3. US3 (admin group management) → demo: full group lifecycle.
4. US4 (profile) + US5 (role gating) → demo: complete UX.
5. US11 (createdByUsername) — can land at any point.
6. US6 (SDK polish) — most of it lands in US2/US3.
7. US7 (docs).
8. US8 (E2E) — must land before merge.

### Definition of Done (per Constitution §V + spec.md SC-001 … SC-008)

- ✅ Phase 12 polish gates pass: format / lint / backend tests / frontend tests / E2E lifecycle.
- ✅ Quickstart § A–E runs as written.
- ✅ `schema.graphql` is regenerated and committed.
- ✅ SDK `_generated/` is regenerated and committed.
- ✅ `dev/guides/users-and-groups.md` exists.
- ✅ The auth-lifecycle E2E passes in both api-mode and ui-mode in CI.
- ✅ All propagation tests for every new GraphQL field / mutation pass.

---

## Notes

- `[P]` markers reflect "this task touches different files and has no incomplete-task dependencies *at the time it can start*".
- Audit-log lines (FR-030) and password masking (FR-029) are checked by specific tests (T038, T036) — they are part of definition-of-done.
- Concurrency safety on the last-admin guard (FR-010) is covered by T035; do NOT skip it.
- Every commit during implementation should still pass `uv run invoke format lint` per Constitution §VI.
- No DB schema changes are introduced; if a task seems to require one, STOP and revisit — the foundation from #179 has every required column.
