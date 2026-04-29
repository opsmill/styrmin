# Tasks: Migrate from React Router to TanStack Router

**Input**: Design documents from `/specs/001-tanstack-router-migration/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Not explicitly requested in the feature specification. Test tasks are limited to updating existing test infrastructure (US3).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Swap routing dependencies and create the new route infrastructure skeleton

- [X] T001 Swap routing dependencies: run `pnpm remove react-router` and `pnpm add @tanstack/react-router` in `frontend/`
- [X] T002 Create `frontend/src/routes/` directory for TanStack Router route definitions

**Checkpoint**: Dependencies swapped, route directory exists. TypeScript will have errors until routes and imports are migrated.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Create the core route tree, router instance, and type registration that ALL user stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T003 Create root route with AppShell layout and notFoundComponent in `frontend/src/routes/__root.tsx` (per R-004, R-010)
- [X] T004 [P] Create index route (`/`) for EnvironmentListPage in `frontend/src/routes/index.tsx`
- [X] T005 [P] Create environment detail route (`/environments/$environmentId`) in `frontend/src/routes/environmentDetail.tsx`
- [X] T006 [P] Create deploy form route (`/environments/$environmentId/deploy`) in `frontend/src/routes/deployForm.tsx`
- [X] T007 [P] Create deployment detail route (`/environments/$environmentId/deployments/$deploymentId`) in `frontend/src/routes/deploymentDetail.tsx`
- [X] T008 [P] Create backup storage location list route (`/backup-storage-locations`) in `frontend/src/routes/backupStorageLocationList.tsx`
- [X] T009 [P] Create backup storage location detail route (`/backup-storage-locations/$id`) in `frontend/src/routes/backupStorageLocationDetail.tsx`
- [X] T010 [P] Create driver list route (`/drivers`) in `frontend/src/routes/driverList.tsx`
- [X] T011 [P] Create add driver route (`/drivers/add`) in `frontend/src/routes/addDriver.tsx`
- [X] T012 [P] Create driver detail route (`/drivers/$driverId`) in `frontend/src/routes/driverDetail.tsx`
- [X] T013 [P] Create settings route (`/settings`) in `frontend/src/routes/settings.tsx`
- [X] T014 [P] Create cluster detail route (`/settings/clusters/$clusterId`) in `frontend/src/routes/clusterDetail.tsx`
- [X] T015 Assemble route tree with all 11 child routes in `frontend/src/routeTree.ts`
- [X] T016 Create router instance with type registration (`declare module`) in `frontend/src/router.ts` (per R-007)

**Checkpoint**: Route tree and router instance exist with full type registration. All 11 routes defined with lazy-loaded components.

---

## Phase 3: User Story 2 — Equivalent Route Structure and Behavior (Priority: P1) 🎯 MVP

**Goal**: All 11 routes resolve to the same pages with the same URL patterns; AppShell layout wraps all pages; lazy loading preserved.

**Independent Test**: Navigate to every route in the browser and confirm each page loads correctly with AppShell layout.

### Implementation for User Story 2

- [X] T017 [US2] Replace `BrowserRouter`/`Routes`/`Route` with `RouterProvider` in `frontend/src/App.tsx`
- [X] T018 [US2] Update AppShell: replace `Outlet`, `Link`, `useLocation` imports from `react-router` with TanStack Router equivalents (`Outlet`, `Link`, `useRouterState`) in `frontend/src/components/AppShell.tsx` (per R-004, R-009)
- [X] T019 [US2] Update `Link` import in `frontend/src/components/PageLayout.tsx`

**Checkpoint**: Application boots with TanStack Router. All routes render correct pages under AppShell layout. Active link styling works via `activeProps` or `useRouterState`.

---

## Phase 4: User Story 1 — Type-Safe Route Navigation (Priority: P1)

**Goal**: All route parameters are fully typed at compile time; `Link` and `useNavigate` reject invalid routes at compile time.

**Independent Test**: Verify that `useParams` returns typed (non-optional) params, and that an invalid route path in `Link` or `navigate` causes a TypeScript compile error.

### Implementation for User Story 1

- [X] T020 [P] [US1] Migrate `useParams`, `useNavigate`, `Link` to TanStack Router in `frontend/src/pages/environments/EnvironmentDetailPage.tsx`
- [X] T021 [P] [US1] Migrate `Link` to TanStack Router in `frontend/src/pages/environments/EnvironmentListPage.tsx`
- [X] T022 [P] [US1] Migrate `useParams`, `useNavigate`, `Link` to TanStack Router in `frontend/src/pages/deployments/DeployFormPage.tsx`
- [X] T023 [P] [US1] Migrate `useParams`, `useNavigate` to TanStack Router in `frontend/src/pages/deployments/DeploymentDetailPage.tsx`
- [X] T024 [P] [US1] Migrate `useNavigate`, `Link` to TanStack Router in `frontend/src/pages/drivers/DriverListPage.tsx`
- [X] T025 [P] [US1] Migrate `useParams` to TanStack Router in `frontend/src/pages/drivers/DriverDetailPage.tsx`
- [X] T026 [P] [US1] Migrate `useNavigate` to TanStack Router in `frontend/src/pages/drivers/AddDriverPage.tsx`
- [X] T027 [P] [US1] Migrate `Link` to TanStack Router in `frontend/src/pages/backup-storage-locations/BackupStorageLocationListPage.tsx`
- [X] T028 [P] [US1] Migrate `useParams`, `useNavigate` to TanStack Router in `frontend/src/pages/backup-storage-locations/BackupStorageLocationDetailPage.tsx`
- [X] T029 [P] [US1] Migrate `Link` to TanStack Router in `frontend/src/pages/settings/SettingsPage.tsx`
- [X] T030 [P] [US1] Migrate `useParams`, `Link` to TanStack Router in `frontend/src/pages/settings/ClusterDetailPage.tsx`

**Checkpoint**: All page components use TanStack Router hooks. `useParams` returns typed params without manual assertions. `pnpm build` passes with zero TypeScript errors (SC-002, SC-004, SC-005).

---

## Phase 5: User Story 3 — Test Infrastructure Compatibility (Priority: P2)

**Goal**: Test-compatible router wrapper replaces `MemoryRouter`; all existing tests pass.

**Independent Test**: Run `pnpm test` in `frontend/` and confirm all tests pass.

### Implementation for User Story 3

- [X] T031 [US3] Replace `MemoryRouter` with `createMemoryHistory` + `createRouter` + `RouterProvider` in `frontend/src/test/utils.tsx` (per R-006, contracts/test-utilities.ts)
- [X] T032 [US3] Run full test suite (`pnpm test`) and fix any test failures caused by the router migration

**Checkpoint**: All existing frontend tests pass with the new router test utilities (SC-003).

---

## Phase 6: User Story 4 — Clean Dependency Removal (Priority: P3)

**Goal**: `react-router` is fully removed from dependencies; zero import references remain.

**Independent Test**: Confirm `react-router` is absent from `package.json` and `grep -r "from ['\"]react-router" frontend/src/` returns zero results.

### Implementation for User Story 4

- [X] T033 [US4] Verify `react-router` is absent from `frontend/package.json` dependencies (should already be removed in T001; confirm no residual references)
- [X] T034 [US4] Search entire `frontend/src/` for any remaining `react-router` imports and remove them: `grep -r "from ['\"]react-router" frontend/src/`

**Checkpoint**: Zero `react-router` references in codebase. `package.json` contains only `@tanstack/react-router` (FR-008).

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final validation across all success criteria

- [X] T035 Run `pnpm build` and verify zero TypeScript errors (SC-002)
- [X] T036 Run `pnpm test` and verify all tests pass (SC-003)
- [X] T037 Compare production bundle sizes before/after migration — must be within 5% tolerance (SC-006)
- [X] T038 Run `pnpm lint` and fix any linting issues
- [X] T039 Manual smoke test: navigate all 11 routes via browser, verify correct page + layout (SC-001, SC-007)
- [X] T040 Run quickstart.md validation steps (verify commands from quickstart.md section 9)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US2 (Phase 3)**: Depends on Phase 2 — App.tsx and AppShell must be migrated first for routes to work
- **US1 (Phase 4)**: Depends on Phase 3 — page component hooks need the router to be active
- **US3 (Phase 5)**: Depends on Phase 2 — can run in parallel with US1/US2 if needed
- **US4 (Phase 6)**: Depends on Phases 3 + 4 — all imports must be migrated before verifying zero references
- **Polish (Phase 7)**: Depends on all user stories being complete

### User Story Dependencies

- **US2 (P1)**: Start after Foundational. No dependency on other stories. Makes routes work.
- **US1 (P1)**: Start after US2. Depends on router being active (US2). Adds type safety to page components.
- **US3 (P2)**: Start after Foundational. Independent of US1/US2 (only touches test utilities). Can run in parallel with US1/US2.
- **US4 (P3)**: Start after US1 + US2 + US3 complete. Verifies clean removal.

### Within Each User Story

- US2: App.tsx first (T017), then AppShell (T018) and PageLayout (T019) in parallel
- US1: All 11 page component tasks (T020–T030) are parallelizable — they touch different files
- US3: Test utility update (T031) first, then fix failures (T032)
- US4: Both tasks sequential (verify then search)

### Parallel Opportunities

- **Phase 2**: T004–T014 (all 11 route definitions) can run in parallel — different files, no dependencies
- **Phase 4**: T020–T030 (all 11 page component migrations) can run in parallel — different files, no dependencies
- **Cross-phase**: US3 (Phase 5) can run in parallel with US2 (Phase 3) and US1 (Phase 4) since test utilities are independent files

---

## Parallel Example: User Story 1

```bash
# Launch all page component migrations together (all [P]):
Task: "Migrate useParams, useNavigate, Link in frontend/src/pages/environments/EnvironmentDetailPage.tsx"
Task: "Migrate Link in frontend/src/pages/environments/EnvironmentListPage.tsx"
Task: "Migrate useParams, useNavigate, Link in frontend/src/pages/deployments/DeployFormPage.tsx"
Task: "Migrate useParams, useNavigate in frontend/src/pages/deployments/DeploymentDetailPage.tsx"
Task: "Migrate useNavigate, Link in frontend/src/pages/drivers/DriverListPage.tsx"
Task: "Migrate useParams in frontend/src/pages/drivers/DriverDetailPage.tsx"
Task: "Migrate useNavigate in frontend/src/pages/drivers/AddDriverPage.tsx"
Task: "Migrate Link in frontend/src/pages/backup-storage-locations/BackupStorageLocationListPage.tsx"
Task: "Migrate useParams, useNavigate in frontend/src/pages/backup-storage-locations/BackupStorageLocationDetailPage.tsx"
Task: "Migrate Link in frontend/src/pages/settings/SettingsPage.tsx"
Task: "Migrate useParams, Link in frontend/src/pages/settings/ClusterDetailPage.tsx"
```

## Parallel Example: Foundational Route Definitions

```bash
# Launch all route file creations together (all [P]):
Task: "Create index route in frontend/src/routes/index.tsx"
Task: "Create environment detail route in frontend/src/routes/environmentDetail.tsx"
Task: "Create deploy form route in frontend/src/routes/deployForm.tsx"
Task: "Create deployment detail route in frontend/src/routes/deploymentDetail.tsx"
Task: "Create backup storage location list route in frontend/src/routes/backupStorageLocationList.tsx"
Task: "Create backup storage location detail route in frontend/src/routes/backupStorageLocationDetail.tsx"
Task: "Create driver list route in frontend/src/routes/driverList.tsx"
Task: "Create add driver route in frontend/src/routes/addDriver.tsx"
Task: "Create driver detail route in frontend/src/routes/driverDetail.tsx"
Task: "Create settings route in frontend/src/routes/settings.tsx"
Task: "Create cluster detail route in frontend/src/routes/clusterDetail.tsx"
```

---

## Implementation Strategy

### MVP First (US2 — Equivalent Route Structure)

1. Complete Phase 1: Setup (dependency swap)
2. Complete Phase 2: Foundational (route tree + router instance)
3. Complete Phase 3: US2 (App.tsx + AppShell migration)
4. **STOP and VALIDATE**: All 11 routes load correctly in browser
5. Application is functional (routes work, even if some pages still use React Router hooks temporarily)

### Incremental Delivery

1. Setup + Foundational → Route infrastructure ready
2. Add US2 → Routes work, app boots → **MVP!**
3. Add US1 → All page components fully type-safe → Deploy/Demo
4. Add US3 → Test infrastructure updated, CI green → Deploy/Demo
5. Add US4 → Clean dependency removal verified → Final validation
6. Polish → Bundle size check, lint, smoke test → **Done**

### Key Reference Documents

| Task Phase | Primary Reference |
|------------|-------------------|
| Route definitions (Phase 2) | `contracts/route-tree.ts`, `data-model.md` |
| Import migration (Phases 3–4) | `contracts/import-migration.md` |
| Hook migration patterns | `research.md` (R-003, R-004, R-005) |
| Test utilities (Phase 5) | `contracts/test-utilities.ts`, `research.md` (R-006) |
| Lazy loading pattern | `research.md` (R-002) |
| Active link styling | `research.md` (R-009) |

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- US1 and US2 are both P1 but US2 is sequenced first because the router must be active before page components can use its hooks
- US3 can technically run in parallel with US1/US2 since it only touches `src/test/utils.tsx`
- All route definitions use `lazyRouteComponent` for lazy loading (per R-002)
- Route parameter syntax: `$paramName` replaces `:paramName` (per R-003)
- Commit after each phase or logical group of tasks
