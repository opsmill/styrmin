# Tasks: Replace urql with TanStack Query

**Input**: Design documents from `/specs/001-tanstack-query-migration/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Not explicitly requested — test tasks omitted. US5 covers test infrastructure updates.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Swap dependencies and create the foundational data fetching infrastructure

- [x] T001 Update `frontend/package.json`: add `@tanstack/react-query` and `@tanstack/react-query-devtools`, remove `urql` and `@urql/core`. Update devDependencies: add `@graphql-codegen/typescript-react-query`, remove `@graphql-codegen/typescript-urql`. Run `pnpm install`.
- [x] T002 [P] Create GraphQL fetcher function in `frontend/src/lib/graphql-fetcher.ts` — a `fetch`-based function that POSTs to `/graphql`, handles GraphQL errors, and returns typed data. See `contracts/graphql-fetcher.md` for the interface contract.
- [x] T003 [P] Create QueryClient configuration in `frontend/src/lib/query-client.ts` — export a `QueryClient` instance with defaults: `staleTime: 0`, `gcTime: 300_000`, `retry: 3` for queries, `retry: 0` for mutations, `refetchOnWindowFocus: true`. See `data-model.md` for attribute details.
- [x] T004 Update codegen configuration in `frontend/codegen.ts`: replace `typescript-urql` plugin with `typescript-react-query` plugin. Configure `reactQueryVersion: 5`, `fetcher` pointing to `../lib/graphql-fetcher#graphqlFetcher`, `exposeQueryKeys: true`. See `contracts/codegen-config.md` for full config.
- [x] T005 Regenerate typed hooks by running `pnpm codegen` (or `npx graphql-codegen`) in `frontend/`. Verify `frontend/src/generated/graphql.ts` contains TanStack Query hooks (useXxxQuery returning `UseQueryResult`, useXxxMutation returning `UseMutationResult`). Fix any codegen errors.
- [x] T006 Update provider in `frontend/src/App.tsx`: replace urql `Provider` import and `<Provider value={client}>` with `QueryClientProvider` import from `@tanstack/react-query` and `<QueryClientProvider client={queryClient}>`. Import `queryClient` from `@/lib/query-client`.

**Checkpoint**: TanStack Query is installed, configured, and providing context. Generated hooks exist. No pages updated yet — app will have import errors until Phase 2+3.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core cleanup that MUST complete before page migrations — remove old infrastructure files

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T007 Delete `frontend/src/lib/urql.ts` (urql client configuration). Remove any imports of this file from `frontend/src/App.tsx` if not already removed in T006.

**Checkpoint**: Old urql infrastructure removed. Page-level migrations can begin.

---

## Phase 3: User Story 1 — Core Data Fetching (Priority: P1) 🎯 MVP

**Goal**: All 14 GraphQL query hooks migrated across all page components. Users can browse every page with data loading correctly.

**Independent Test**: Navigate to every page in the application. Verify data loads, loading indicators appear, error states work, and conditional queries (`enabled`) execute correctly.

### Implementation for User Story 1

Migrate each page's query hook usage from urql destructuring pattern `const [{ data, fetching, error }, reexecute] = useXxxQuery(...)` to TanStack Query pattern `const { data, isLoading, error, refetch } = useXxxQuery(...)`. Replace `fetching` with `isLoading`, `reexecute()` with `refetch()`. See `contracts/hook-migration-map.md` for full pattern mapping.

- [x] T008 [P] [US1] Migrate query hooks in `frontend/src/pages/settings/SettingsPage.tsx`: update `useListClustersQuery` — destructure as object `{ data, isLoading, error }`, replace `fetching` → `isLoading`. Update any `CreateClusterDialog` child component if it receives query result props.
- [x] T009 [P] [US1] Migrate query hooks in `frontend/src/pages/settings/ClusterDetailPage.tsx`: update `useGetClusterQuery` usage — object destructuring, `fetching` → `isLoading`.
- [x] T010 [P] [US1] Migrate query hooks in `frontend/src/pages/environments/EnvironmentListPage.tsx`: update `useListEnvironmentsQuery` — object destructuring, `fetching` → `isLoading`.
- [x] T011 [P] [US1] Migrate query hooks in `frontend/src/pages/environments/EnvironmentDetailPage.tsx`: update `useGetEnvironmentQuery` and `useListBackupStorageLocationsQuery` — object destructuring, `fetching` → `isLoading`.
- [x] T012 [P] [US1] Migrate query hooks in `frontend/src/pages/deployments/DeployFormPage.tsx`: update `useListApplicationDriversQuery` — object destructuring, `fetching` → `isLoading`.
- [x] T013 [P] [US1] Migrate query hooks in `frontend/src/pages/deployments/DeploymentDetailPage.tsx`: update `useGetDeploymentQuery`, `useListBackupsQuery`, and `useListRestoresQuery`. **CRITICAL**: convert `pause: !instanceId` → `enabled: !!instanceId` and `pause: backup.status !== "completed"` → `enabled: backup.status === "completed"` (boolean inversion). Object destructuring, `fetching` → `isLoading`.
- [x] T014 [P] [US1] Migrate query hooks in `frontend/src/pages/drivers/DriverListPage.tsx`: update `useListDriversQuery` — object destructuring, `fetching` → `isLoading`.
- [x] T015 [P] [US1] Migrate query hooks in `frontend/src/pages/drivers/DriverDetailPage.tsx`: update `useGetDriverQuery` — object destructuring, `fetching` → `isLoading`.
- [x] T016 [P] [US1] Migrate query hooks in `frontend/src/pages/backup-storage-locations/BackupStorageLocationListPage.tsx`: update `useListBackupStorageLocationsQuery` — object destructuring, `fetching` → `isLoading`.
- [x] T017 [P] [US1] Migrate query hooks in `frontend/src/pages/backup-storage-locations/BackupStorageLocationDetailPage.tsx`: update `useGetBackupStorageLocationQuery` — object destructuring, `fetching` → `isLoading`.

**Checkpoint**: All pages load and display data correctly via TanStack Query. Conditional queries work. Mutations not yet migrated.

---

## Phase 4: User Story 2 — Mutations with Cache Invalidation (Priority: P1)

**Goal**: All 14 GraphQL mutation hooks migrated. Create/update/delete operations work and automatically invalidate related cached queries.

**Independent Test**: Perform every mutation operation (create cluster, create environment, deploy, create/delete backup, load driver, etc.). Verify the operation succeeds, the UI reflects the change, and the relevant list/detail page refreshes automatically without manual reload.

### Implementation for User Story 2

Migrate each page's mutation hook usage from urql pattern `const [result, execute] = useXxxMutation()` to TanStack Query pattern `const xxxMutation = useXxxMutation({ onSuccess: () => queryClient.invalidateQueries(...) })`. Replace `await execute(vars)` with `await xxxMutation.mutateAsync(vars)`. Add `onSuccess` callbacks per the cache invalidation map in `data-model.md`. Import `useQueryClient` where needed.

- [x] T018 [P] [US2] Migrate mutation hooks in `frontend/src/pages/settings/SettingsPage.tsx` (and `CreateClusterDialog` if separate): update `useCreateClusterMutation`. Add `onSuccess` to invalidate `ListClusters` query key. Replace `execute()` → `mutateAsync()`, `fetching` → `isPending`.
- [x] T019 [P] [US2] Migrate mutation hooks in `frontend/src/pages/environments/EnvironmentListPage.tsx` (and `CreateEnvironmentDialog`): update `useCreateEnvironmentMutation`. Add `onSuccess` to invalidate `ListEnvironments`. Replace `execute()` → `mutateAsync()`.
- [x] T020 [P] [US2] Migrate mutation hooks in `frontend/src/pages/environments/EnvironmentDetailPage.tsx`: update `useAssignBackupStorageLocationMutation` and `useUnassignBackupStorageLocationMutation`. Add `onSuccess` to invalidate `GetEnvironment`. Replace `execute()` → `mutateAsync()`.
- [x] T021 [P] [US2] Migrate mutation hooks in `frontend/src/pages/deployments/DeployFormPage.tsx`: update `useDeployMutation`. Add `onSuccess` to invalidate `GetEnvironment`. Replace `execute()` → `mutateAsync()`.
- [x] T022 [P] [US2] Migrate mutation hooks in `frontend/src/pages/deployments/DeploymentDetailPage.tsx`: update `useCreateBackupMutation`, `useDeleteBackupMutation`, `useCreateRestoreMutation`, and `useUpdateDeploymentVersionMutation`. Add `onSuccess` callbacks: CreateBackup/DeleteBackup → invalidate `ListBackups`, CreateRestore → invalidate `ListRestores`, UpdateDeploymentVersion → invalidate `GetDeployment`. Replace `execute()` → `mutateAsync()`.
- [x] T023 [P] [US2] Migrate mutation hooks in `frontend/src/pages/drivers/AddDriverPage.tsx`: update `useLoadLocalDriverMutation` and `useLoadRemoteDriverMutation`. Add `onSuccess` to invalidate `ListDrivers`. Replace `execute()` → `mutateAsync()`.
- [x] T024 [P] [US2] Migrate mutation hooks in `frontend/src/pages/backup-storage-locations/BackupStorageLocationListPage.tsx` (and `CreateBackupStorageLocationDialog`): update `useCreateBackupStorageLocationMutation`. Add `onSuccess` to invalidate `ListBackupStorageLocations`. Replace `execute()` → `mutateAsync()`.
- [x] T025 [P] [US2] Migrate mutation hooks in `frontend/src/pages/backup-storage-locations/BackupStorageLocationDetailPage.tsx`: update `useDeleteBackupStorageLocationMutation` and `useUpdateBackupStorageLocationMutation`. Add `onSuccess`: Delete → invalidate `ListBackupStorageLocations`, Update → invalidate `GetBackupStorageLocation`. Replace `execute()` → `mutateAsync()`.

**Checkpoint**: All mutations work. Cache invalidation triggers automatic data refresh. Full CRUD operations functional.

---

## Phase 5: User Story 3 — Automatic Data Refresh (Priority: P2)

**Goal**: Pages that previously used `useAutoRefresh` now use TanStack Query's `refetchInterval` for automatic periodic data refresh.

**Independent Test**: Navigate to list pages (clusters, environments, drivers, BSLs, deployments). Verify data automatically refreshes at ~10 second intervals. Verify refresh stops when navigating away.

### Implementation for User Story 3

Replace `useAutoRefresh({ onRefresh: () => reexecute(...), interval: 10_000 })` with `refetchInterval: 10_000` option on the relevant query hooks. Remove `useAutoRefresh` import from each page. If a page has a refresh toggle UI, manage it via component state controlling the `refetchInterval` value (set to `false` to disable). Use `dataUpdatedAt` from the query result to replace `lastRefreshedAt`.

- [x] T026 [US3] Identify all pages that import `useAutoRefresh` from `@/hooks/useAutoRefresh` by searching the codebase. Document the list of files that need updates.
- [x] T027 [P] [US3] Update each page that uses `useAutoRefresh`: add `refetchInterval: 10_000` to the primary query hook options, remove `useAutoRefresh` import and usage. If the page exposes a refresh toggle, use component state to set `refetchInterval` to `10_000` or `false`. If the page shows "last refreshed at", use `dataUpdatedAt` from the query result.
- [x] T028 [US3] Delete `frontend/src/hooks/useAutoRefresh.ts` after all usages are removed. Verify no remaining imports with a codebase search.

**Checkpoint**: Automatic data refresh works identically to before. No manual refresh hooks remain.

---

## Phase 6: User Story 4 — Developer Experience (DevTools) (Priority: P2)

**Goal**: TanStack Query DevTools available in development mode, excluded from production builds.

**Independent Test**: Run `pnpm dev`, open browser, verify DevTools panel is visible. Run `pnpm build`, verify DevTools are not in the production bundle.

### Implementation for User Story 4

- [x] T029 [US4] Add `ReactQueryDevtools` to `frontend/src/App.tsx`: import `ReactQueryDevtools` from `@tanstack/react-query-devtools`, render `<ReactQueryDevtools initialIsOpen={false} />` inside `QueryClientProvider`, conditionally rendered only when `import.meta.env.DEV` is true.

**Checkpoint**: DevTools visible in dev mode, excluded from prod.

---

## Phase 7: User Story 5 — Test Infrastructure (Priority: P2)

**Goal**: Test utility wrapper includes TanStack Query context. Existing tests pass.

**Independent Test**: Run `pnpm test` in `frontend/`. All existing tests pass. Write a minimal test using a query hook to verify the wrapper works.

### Implementation for User Story 5

- [x] T030 [US5] Update test utilities in `frontend/src/test/utils.tsx`: create a test-specific `QueryClient` with `retry: false` and `gcTime: Infinity` defaults. Wrap the existing render function's component tree with `QueryClientProvider`. Ensure each test call creates a fresh `QueryClient` to prevent cache pollution between tests.
- [x] T031 [US5] Run `pnpm test` in `frontend/` and fix any test failures caused by the migration. Failures are expected in tests that reference urql-specific patterns (e.g., `fetching` property). Update assertions to use TanStack Query equivalents (`isLoading`, `isPending`).

**Checkpoint**: All tests pass with TanStack Query context available.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Final cleanup, verification, and removal of all urql traces

- [x] T032 Search entire `frontend/` directory for any remaining references to `urql`, `@urql/core`, `Urql`, `CombinedError`, `reexecute`, `requestPolicy`, or `useAutoRefresh`. Remove or replace any found.
- [x] T033 Verify `frontend/package.json` has zero urql-related packages in dependencies or devDependencies. Run `pnpm install` to clean lockfile.
- [x] T034 Run `pnpm lint` and `pnpm format` in `frontend/` to ensure all code passes linting and formatting checks. Fix any issues.
- [x] T035 Run `pnpm build` in `frontend/` to verify the production build succeeds with no errors or warnings related to the migration.
- [x] T036 Run full quickstart validation from `specs/001-tanstack-query-migration/quickstart.md`: verify all pages load, mutations work, auto-refresh functions, DevTools appear in dev, tests pass, zero urql references remain.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 completion — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2. All T008–T017 can run in parallel (different files)
- **US2 (Phase 4)**: Depends on Phase 3 (query hooks must be migrated before mutation invalidation can target them). All T018–T025 can run in parallel
- **US3 (Phase 5)**: Depends on Phase 3 (query hooks must be migrated to accept `refetchInterval`). Can run in parallel with Phase 4
- **US4 (Phase 6)**: Depends on Phase 1 only. Can run in parallel with Phase 3+
- **US5 (Phase 7)**: Depends on Phase 1 only. Can run in parallel with Phase 3+, but should run after Phase 4 for full test coverage
- **Polish (Phase 8)**: Depends on ALL previous phases

### User Story Dependencies

- **US1 (P1)**: Depends on Foundational only — no other story dependencies
- **US2 (P1)**: Depends on US1 (invalidation targets query keys from US1)
- **US3 (P2)**: Depends on US1 (refetchInterval is a query hook option)
- **US4 (P2)**: Independent — only needs Setup phase
- **US5 (P2)**: Independent — only needs Setup phase

### Within Each User Story

- All page migration tasks within US1 are parallel (different files)
- All page mutation tasks within US2 are parallel (different files)
- US3 tasks are sequential (identify → update → delete hook)

### Parallel Opportunities

- T002 + T003 (fetcher and query client — different files)
- T008–T017 (all US1 query migrations — different page files)
- T018–T025 (all US2 mutation migrations — different page files)
- T029 can start as soon as Phase 1 completes (independent of page migrations)
- T030 can start as soon as Phase 1 completes (independent of page migrations)

---

## Parallel Example: User Story 1

```bash
# Launch all query migration tasks together (all different files):
Task: "T008 Migrate query hooks in SettingsPage.tsx"
Task: "T009 Migrate query hooks in ClusterDetailPage.tsx"
Task: "T010 Migrate query hooks in EnvironmentListPage.tsx"
Task: "T011 Migrate query hooks in EnvironmentDetailPage.tsx"
Task: "T012 Migrate query hooks in DeployFormPage.tsx"
Task: "T013 Migrate query hooks in DeploymentDetailPage.tsx"
Task: "T014 Migrate query hooks in DriverListPage.tsx"
Task: "T015 Migrate query hooks in DriverDetailPage.tsx"
Task: "T016 Migrate query hooks in BackupStorageLocationListPage.tsx"
Task: "T017 Migrate query hooks in BackupStorageLocationDetailPage.tsx"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T006)
2. Complete Phase 2: Foundational (T007)
3. Complete Phase 3: US1 query migrations (T008–T017)
4. **STOP and VALIDATE**: All pages load data correctly
5. This is a functional app — queries work, mutations are broken

### Incremental Delivery

1. Setup + Foundational → Infrastructure ready
2. Add US1 (queries) → Pages load data → Validate
3. Add US2 (mutations) → Full CRUD works → Validate (**functional parity with urql**)
4. Add US3 (auto-refresh) → Polling works → Validate
5. Add US4 (DevTools) → DX improvement → Validate
6. Add US5 (test infra) → Tests pass → Validate
7. Polish → Clean codebase, zero urql references → Final validation

### Parallel Team Strategy

With multiple developers after Phase 1+2 complete:

- **Developer A**: US1 (Phase 3) → US2 (Phase 4) → US3 (Phase 5)
- **Developer B**: US4 (Phase 6) + US5 (Phase 7)
- **Together**: Phase 8 (Polish)

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each phase completion
- Stop at any checkpoint to validate independently
- The generated file `frontend/src/generated/graphql.ts` is regenerated in T005 — do not manually edit
- All page migrations follow the same pattern from `contracts/hook-migration-map.md`
- Cache invalidation keys for mutations are defined in `data-model.md` (Cache Invalidation Map)
