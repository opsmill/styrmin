# Tasks: Environment-Level Backup and Restore

**Input**: Design documents from `/specs/001-env-backup-restore/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Included — spec requires unit tests for service/repository, integration tests for GraphQL, and E2E tests (FR-015, US5).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup

**Purpose**: No project scaffolding needed — existing repo structure. This phase ensures the spec artifacts are reviewed and the branch is ready.

- [ ] T001 Verify existing backup/restore models and services in backend/styrmin_backend/db/models.py, backend/styrmin_backend/services/backup/service.py, and backend/styrmin_backend/workflows/ to confirm integration points

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Database models, enums, repositories, and UnitOfWork registration that ALL user stories depend on.

**CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T002 Add `EnvironmentBackupStatus` and `EnvironmentRestoreStatus` enums to backend/styrmin_backend/db/models.py (PENDING, IN_PROGRESS, COMPLETED, PARTIALLY_FAILED, FAILED)
- [ ] T003 Add `EnvironmentBackup` model to backend/styrmin_backend/db/models.py (extends StyrminModel; fields: name, status, started_at, completed_at, error_message, metadata_, max_concurrency, timeout, environment_id FK; relationships: environment, backups, restores)
- [ ] T004 Add `EnvironmentRestore` model to backend/styrmin_backend/db/models.py (extends StyrminModel; fields: name, status, started_at, completed_at, error_message, metadata_, environment_backup_id FK; relationships: environment_backup, restores)
- [ ] T005 Add nullable `environment_backup_id` FK column and `environment_backup` relationship to existing `Backup` model in backend/styrmin_backend/db/models.py (cascade="all, delete-orphan" on EnvironmentBackup.backups side)
- [ ] T006 Add nullable `environment_restore_id` FK column and `environment_restore` relationship to existing `Restore` model in backend/styrmin_backend/db/models.py (cascade="all, delete-orphan" on EnvironmentRestore.restores side)
- [ ] T007 [P] Create `EnvironmentBackupRepository` (protocol + SQLModel implementation) in backend/styrmin_backend/repository/environment_backup.py following existing repository patterns
- [ ] T008 [P] Create `EnvironmentRestoreRepository` (protocol + SQLModel implementation) in backend/styrmin_backend/repository/environment_restore.py following existing repository patterns
- [ ] T009 Register `environment_backups` and `environment_restores` repositories in `UnitOfWork` in backend/styrmin_backend/services/unit_of_work.py

**Checkpoint**: Foundation ready — models exist, repos registered, user story implementation can begin.

---

## Phase 3: User Story 1 — Create Environment Backup (Priority: P1) MVP

**Goal**: Platform operators can back up an entire environment with a single operation. A single EnvironmentBackup record is created, constituent Backup records are created for each active instance, and a Prefect workflow orchestrates concurrent execution.

**Independent Test**: Create an environment backup for an environment with multiple deployments. Verify EnvironmentBackup record created with PENDING status, constituent Backup records created per active instance, and status transitions to COMPLETED when all constituents complete.

### Tests for User Story 1

- [ ] T010 [P] [US1] Unit test for `create_environment_backup` service function in backend/tests/unit/services/backup/test_environment_backup.py — test record creation, validation (no BSL, no active instances, skipped instances), and constituent backup linkage
- [ ] T011 [P] [US1] Unit test for `update_environment_backup_status` in backend/tests/unit/services/backup/test_environment_backup.py — test status aggregation logic (all complete, partial fail, all fail, timeout)

### Implementation for User Story 1

- [ ] T012 [US1] Implement `create_environment_backup()` service function in backend/styrmin_backend/services/backup/environment.py — validate environment has BSL (FR-012), find active instances, skip instances with in-progress backups (FR-011), create EnvironmentBackup + constituent Backup records, dispatch orchestration workflow
- [ ] T013 [US1] Implement `update_environment_backup_status()` service function in backend/styrmin_backend/services/backup/environment.py — recompute parent status from constituent statuses (FR-003), update started_at/completed_at/error_message/metadata
- [ ] T014 [US1] Add `EXECUTE_ENV_BACKUP` to `PrefectAction` enum in backend/styrmin_backend/workflows/models.py
- [ ] T015 [US1] Create `execute_environment_backup_workflow` Prefect flow in backend/styrmin_backend/workflows/templates/environment_backup.py — load EnvironmentBackup, mark IN_PROGRESS, dispatch constituent EXECUTE_BACKUP actions with asyncio.Semaphore for concurrency limiting (FR-017), track completions, update parent status, handle overall timeout (FR-018)
- [ ] T016 [US1] Register `EXECUTE_ENV_BACKUP` workflow in backend/styrmin_backend/workflows/catalogue.py
- [ ] T017 [P] [US1] Create `EnvironmentBackupType` Strawberry GraphQL type in backend/styrmin_backend/api/definitions/backup/environment_backup.py — include computed fields (backupCount, completedCount, failedCount) and resolvers for environment, backups, restores
- [ ] T018 [P] [US1] Add `EnvironmentBackupNotFoundError`, `EnvironmentBackupValidationError`, `EnvironmentBackupOperationInProgressError` ServiceError subclasses to backend/styrmin_backend/services/exceptions.py (with error_code and default_message)
- [ ] T019 [US1] Add `create_environment_backup` mutation to backend/styrmin_backend/api/schema/mutation.py (args: environmentId, name, maxConcurrency, timeout) returning EnvironmentBackupType — errors raised as ServiceError exceptions
- [ ] T020 [P] [US1] Create SDK mutation file python_sdk/src/styrmin_sdk/graphql/create_environment_backup.graphql per contracts/sdk_operations.graphql
- [ ] T020a [US1] Create `EnvironmentBackupResource` class in python_sdk/src/styrmin_sdk/resources/environment_backups.py — methods: `create(environment_id, name?, max_concurrency?, timeout?)`, `get(id)`, `list(environment_id, status?)`, `delete(id)`, `wait_for_completion(id, max_wait, interval)` following existing resource patterns (e.g., `BackupResource`)
- [ ] T020b [US1] Register `environment_backups` attribute on `StyrminClient` in python_sdk/src/styrmin_sdk/client.py — instantiate `EnvironmentBackupResource(transport)` in `__init__`
- [ ] T021 [P] [US1] Add `styrmin env backup create` CLI command in appropriate CLI module — calls CreateEnvironmentBackup mutation via styrmin-sdk, accepts environment name/ID, optional --name, --max-concurrency, --timeout flags

**Checkpoint**: User Story 1 complete — operators can create environment backups via GraphQL API and CLI. Status updates flow through the Prefect workflow.

---

## Phase 4: User Story 2 — Restore Environment from Backup (Priority: P2)

**Goal**: Platform operators can restore an entire environment from a completed or partially-completed EnvironmentBackup. Individual restore operations are created for each successfully completed constituent backup.

**Independent Test**: Given a completed EnvironmentBackup with N constituent backups, initiate a restore. Verify EnvironmentRestore record created, N constituent Restore records created targeting original namespaces, and status transitions correctly.

### Tests for User Story 2

- [ ] T022 [P] [US2] Unit test for `create_environment_restore` service function in backend/tests/unit/services/backup/test_environment_restore.py — test validation (reject FAILED backup, reject concurrent restore from same backup), constituent restore creation for COMPLETED-only backups
- [ ] T023 [P] [US2] Unit test for `update_environment_restore_status` in backend/tests/unit/services/backup/test_environment_restore.py — test status aggregation logic

### Implementation for User Story 2

- [ ] T024 [US2] Implement `create_environment_restore()` service function in backend/styrmin_backend/services/backup/environment.py — validate source EnvironmentBackup status (COMPLETED or PARTIALLY_FAILED only), check no concurrent restore in progress, create EnvironmentRestore + constituent Restore records for COMPLETED backups only, dispatch orchestration workflow
- [ ] T025 [US2] Implement `update_environment_restore_status()` service function in backend/styrmin_backend/services/backup/environment.py — recompute parent status from constituent restore statuses (FR-006)
- [ ] T026 [US2] Add `EXECUTE_ENV_RESTORE` to `PrefectAction` enum in backend/styrmin_backend/workflows/models.py
- [ ] T027 [US2] Create `execute_environment_restore_workflow` Prefect flow in backend/styrmin_backend/workflows/templates/environment_backup.py — load EnvironmentRestore, mark IN_PROGRESS, dispatch constituent EXECUTE_RESTORE actions with concurrency limiting, track completions, update parent status
- [ ] T028 [US2] Register `EXECUTE_ENV_RESTORE` workflow in backend/styrmin_backend/workflows/catalogue.py
- [ ] T029 [P] [US2] Create `EnvironmentRestoreType` Strawberry GraphQL type in backend/styrmin_backend/api/definitions/backup/environment_restore.py — include computed fields (restoreCount, completedCount, failedCount) and resolvers
- [ ] T030 [P] [US2] Add `EnvironmentRestoreNotFoundError` ServiceError subclass to backend/styrmin_backend/services/exceptions.py (if not already covered by T018 exceptions)
- [ ] T031 [US2] Add `create_environment_restore` mutation to backend/styrmin_backend/api/schema/mutation.py (arg: environmentBackupId) returning EnvironmentRestoreType — errors raised as ServiceError exceptions
- [ ] T032 [P] [US2] Create SDK mutation file python_sdk/src/styrmin_sdk/graphql/create_environment_restore.graphql per contracts/sdk_operations.graphql
- [ ] T032a [US2] Create `EnvironmentRestoreResource` class in python_sdk/src/styrmin_sdk/resources/environment_restores.py — methods: `create(environment_backup_id)`, `get(id)`, `list(environment_backup_id, status?)`, `wait_for_completion(id, max_wait, interval)` following existing resource patterns
- [ ] T032b [US2] Register `environment_restores` attribute on `StyrminClient` in python_sdk/src/styrmin_sdk/client.py — instantiate `EnvironmentRestoreResource(transport)` in `__init__`
- [ ] T033 [P] [US2] Add `styrmin env restore create` CLI command — calls CreateEnvironmentRestore mutation via styrmin-sdk, accepts environment backup name/ID

**Checkpoint**: User Story 2 complete — operators can restore an entire environment from a backup via GraphQL API and CLI.

---

## Phase 5: User Story 3 — View Environment Backup Status and History (Priority: P3)

**Goal**: Platform operators can list environment backups for an environment, view details of a specific backup (including constituent statuses), and view restore history. Exposed via GraphQL queries, CLI, SDK, and frontend UI.

**Independent Test**: Query environment backup list for an environment with multiple backups. Verify all records returned with correct status, counts, and timestamps. Query a specific backup and verify constituent backup details are included.

### Tests for User Story 3

- [ ] T034 [P] [US3] Integration test for `environmentBackups` and `environmentBackup` GraphQL queries in backend/tests/integration/test_environment_backup_queries.py — test list with status filter, get by ID with constituents, empty list case
- [ ] T034a [P] [US1] Integration test for `createEnvironmentBackup` mutation in backend/tests/integration/test_environment_backup_mutations.py — test successful creation, validation errors (no BSL, no active instances), error union type responses
- [ ] T034b [P] [US2] Integration test for `createEnvironmentRestore` mutation in backend/tests/integration/test_environment_backup_mutations.py — test successful restore creation, reject FAILED backup, reject concurrent restore, error union type responses
- [ ] T034c [P] [US4] Integration test for `deleteEnvironmentBackup` mutation in backend/tests/integration/test_environment_backup_mutations.py — test successful cascade delete, reject when operations in progress, error union type responses

### Implementation for User Story 3

- [ ] T035 [P] [US3] Implement `get_environment_backup()`, `get_environment_backups()` service functions in backend/styrmin_backend/services/backup/environment.py — support optional status filter (FR-007, FR-008)
- [ ] T036 [P] [US3] Implement `get_environment_restore()`, `get_environment_restores()` service functions in backend/styrmin_backend/services/backup/environment.py — support optional status filter
- [ ] T037 [US3] Add `environment_backup`, `environment_backups`, `environment_restore`, `environment_restores` queries to backend/styrmin_backend/api/schema/query.py
- [ ] T038 [P] [US3] Create SDK query files in python_sdk/src/styrmin_sdk/graphql/: get_environment_backup.graphql, list_environment_backups.graphql, get_environment_restore.graphql, list_environment_restores.graphql per contracts/sdk_operations.graphql
- [ ] T039 [P] [US3] Add `styrmin env backup list` and `styrmin env backup get` CLI commands — list backups for an environment (with optional --status filter), show details of a specific backup
- [ ] T040 [P] [US3] Add `styrmin env restore list` and `styrmin env restore get` CLI commands — list restores for a backup, show details of a specific restore
- [ ] T041 [US3] Create frontend GraphQL operation files in frontend/src/graphql/: list_environment_backups.graphql, get_environment_backup.graphql per contracts/sdk_operations.graphql
- [ ] T042 [US3] Add "Backups" section to Environment detail page in frontend/src/pages/environments/EnvironmentDetailPage.tsx — list environment backups with status badges, backup counts, timestamps; detail view showing constituent backup statuses; auto-refresh via refetchInterval polling pattern
- [ ] T043 [US3] Add "Create Backup" button and dialog to Environment detail page in frontend/src/pages/environments/EnvironmentDetailPage.tsx — calls createEnvironmentBackup mutation with optional name, max concurrency, timeout inputs
- [ ] T044 [US3] Add "Restore from Backup" button and confirmation dialog per environment backup row in frontend/src/pages/environments/EnvironmentDetailPage.tsx — calls createEnvironmentRestore mutation, shows restore status

**Checkpoint**: User Story 3 complete — operators can view backup/restore status and history via all interfaces (GraphQL, CLI, Frontend).

---

## Phase 6: User Story 4 — Delete Environment Backup (Priority: P4)

**Goal**: Platform operators can delete an environment backup. Deletion cascades to remove all constituent backups and their associated restores. Deletion is rejected if any operation is in progress.

**Independent Test**: Delete a completed environment backup. Verify parent record, all constituent backups, and all restores are removed. Attempt to delete a backup with in-progress operations and verify rejection.

### Tests for User Story 4

- [ ] T045 [P] [US4] Unit test for `delete_environment_backup` service function in backend/tests/unit/services/backup/test_environment_backup.py — test successful cascade delete, rejection when operations in progress (FR-010)

### Implementation for User Story 4

- [ ] T046 [US4] Implement `delete_environment_backup()` service function in backend/styrmin_backend/services/backup/environment.py — check no in-progress constituent backups or restores (FR-010), then delete EnvironmentBackup (cascade handles constituents via SQLAlchemy)
- [ ] T047 [US4] Add `delete_environment_backup` mutation to backend/styrmin_backend/api/schema/mutation.py (arg: environmentBackupId) returning Boolean — raises EnvironmentBackupOperationInProgressError or EnvironmentBackupNotFoundError as ServiceError exceptions
- [ ] T048 [P] [US4] Create SDK mutation file python_sdk/src/styrmin_sdk/graphql/delete_environment_backup.graphql per contracts/sdk_operations.graphql
- [ ] T049 [P] [US4] Add `styrmin env backup delete` CLI command — calls DeleteEnvironmentBackup mutation, accepts backup name/ID
- [ ] T050 [US4] Add delete button with confirmation dialog per environment backup row in frontend/src/pages/environments/EnvironmentDetailPage.tsx — calls deleteEnvironmentBackup mutation, refreshes list on success

**Checkpoint**: User Story 4 complete — operators can clean up old environment backups via all interfaces.

---

## Phase 7: User Story 5 — End-to-End Backup and Restore Verification (Priority: P5)

**Goal**: E2E tests verify the complete environment backup and restore lifecycle through the styrmin SDK, ensuring all components work together correctly (FR-015). Tests MUST use `StyrminClient` (matching existing E2E patterns), never raw GraphQL calls.

**Independent Test**: Run the E2E test suite against a test environment with multiple deployments. Verify create → monitor → restore → delete lifecycle works end-to-end via the SDK.

- [ ] T051 [US5] Create E2E test for full environment backup lifecycle in backend/tests/e2e/test_env_backup_restore.py — use `client.environment_backups.create(environment_id, ...)` to create environment backup, verify constituent backups created via `client.environment_backups.get(id)`, poll with `client.environment_backups.wait_for_completion(id)` until COMPLETED status, verify backup counts and metadata
- [ ] T052 [US5] Add E2E test for environment restore lifecycle in backend/tests/e2e/test_env_backup_restore.py — use `client.environment_restores.create(environment_backup_id)` to restore from completed backup, verify constituent restores via `client.environment_restores.get(id)`, poll with `client.environment_restores.wait_for_completion(id)` until COMPLETED, verify restore counts
- [ ] T053 [US5] Add E2E test for partial failure scenario in backend/tests/e2e/test_env_backup_restore.py — simulate one constituent backup failure, verify PARTIALLY_FAILED status via `client.environment_backups.get(id)`, verify error details captured, verify restore only includes successful backups
- [ ] T054 [US5] Add E2E test for cleanup in backend/tests/e2e/test_env_backup_restore.py — use `client.environment_backups.delete(id)` to delete environment backup, verify cascade removes all constituent backups and restores

**Checkpoint**: User Story 5 complete — full lifecycle validated end-to-end.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Schema regeneration, SDK type generation, formatting, and final validation.

- [ ] T055 Regenerate GraphQL schema: `uv run styrmin export graphql-schema schema.graphql`
- [ ] T056 Regenerate SDK types: `uv run invoke generate`
- [ ] T057 Validate GraphQL operations: `uv run invoke validate-graphql`
- [ ] T058 Run formatters and linters: `uv run invoke format lint`
- [ ] T059 Run backend test suite: `uv run invoke test`
- [ ] T060 Run frontend tests: `cd frontend && pnpm test`
- [ ] T061 Run quickstart.md validation — walk through all verification steps in specs/001-env-backup-restore/quickstart.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 — no dependencies on other stories
- **US2 (Phase 4)**: Depends on Phase 2 — logically depends on US1 (needs completed EnvironmentBackup to restore from), but can be implemented in parallel with US1 since tests can create fixture data
- **US3 (Phase 5)**: Depends on Phase 2 — can be implemented in parallel with US1/US2 for query-side work; frontend depends on mutations from US1/US2 being available
- **US4 (Phase 6)**: Depends on Phase 2 — can be implemented in parallel with US1/US2/US3
- **US5 (Phase 7)**: Depends on US1, US2, US3, US4 all being complete (E2E exercises full lifecycle)
- **Polish (Phase 8)**: Depends on all user stories being complete

### User Story Dependencies

- **US1 → US2**: Restore requires a completed EnvironmentBackup (logical dependency for runtime, not for implementation)
- **US1 → US3**: List/detail queries return data created by US1
- **US1 → US4**: Delete operates on EnvironmentBackup records created by US1
- **US3 → Frontend**: Frontend UI in US3 uses mutations from US1, US2, US4
- **US5**: Depends on ALL prior stories (E2E exercises the full lifecycle)

### Within Each User Story

- Tests written first (should fail before implementation)
- Models/enums before services
- Services before workflows
- Workflows before GraphQL schema
- GraphQL types before mutations/queries
- Backend complete before SDK operations
- SDK operations before CLI commands
- Backend + SDK complete before frontend

### Parallel Opportunities

- **Phase 2**: T007 and T008 (repositories) can run in parallel
- **Phase 3**: T010 + T011 (tests), T017 + T018 (GraphQL types), T020 + T021 (SDK + CLI) can run in parallel
- **Phase 4**: T022 + T023 (tests), T029 + T030 (GraphQL types), T032 + T033 (SDK + CLI) can run in parallel
- **Phase 5**: T034 (test), T035 + T036 (services), T038 + T039 + T040 (SDK + CLI) can run in parallel
- **Phase 6**: T045 (test), T048 + T049 (SDK + CLI) can run in parallel
- **Cross-story**: US1, US2, US3, US4 backend service/repository work can largely proceed in parallel since they operate on separate service functions

---

## Parallel Example: User Story 1

```bash
# Launch tests in parallel:
Task T010: "Unit test for create_environment_backup in backend/tests/unit/services/backup/test_environment_backup.py"
Task T011: "Unit test for update_environment_backup_status in backend/tests/unit/services/backup/test_environment_backup.py"

# Launch GraphQL types in parallel (after services):
Task T017: "EnvironmentBackupType in backend/styrmin_backend/api/definitions/backup/environment_backup.py"
Task T018: "Error union types in backend/styrmin_backend/api/definitions/backup/environment_backup.py"

# Launch SDK + CLI in parallel (after GraphQL):
Task T020: "SDK mutation file python_sdk/src/styrmin_sdk/graphql/create_environment_backup.graphql"
Task T021: "CLI command styrmin env backup create"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (review existing code)
2. Complete Phase 2: Foundational (models, repos, UoW)
3. Complete Phase 3: User Story 1 (create environment backup)
4. **STOP and VALIDATE**: Test environment backup creation end-to-end
5. Run `uv run invoke format lint` and `uv run invoke test`

### Incremental Delivery

1. Setup + Foundational → Models and repos ready
2. US1: Create backup → MVP! Single most valuable operation
3. US2: Restore from backup → Completes the backup/restore lifecycle
4. US3: View status/history → Adds visibility via all interfaces (including frontend)
5. US4: Delete backup → Adds cleanup capability
6. US5: E2E tests → Validates full lifecycle
7. Polish → Schema regen, formatting, final validation

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: US1 (create backup) + US2 (restore)
   - Developer B: US3 (queries, CLI, frontend) + US4 (delete)
3. Once US1-US4 complete:
   - Developer A or B: US5 (E2E tests)
4. Final: Polish phase together

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- [Story] label maps task to specific user story for traceability
- Schema regeneration (T055-T057) must happen after ALL GraphQL schema changes are committed
- Existing Backup/Restore behavior must remain unchanged (SC-004) — only nullable FK columns added
- Frontend follows existing DeploymentDetailPage backup section patterns (research.md Task 7)
- CLI commands are thin clients over GraphQL via styrmin-sdk (research.md Task 8)
