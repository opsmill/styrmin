# Tasks: Leverage Generated Typed Bindings in SDK

**Input**: Design documents from `/specs/003-sdk-typed-bindings/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Existing tests will be updated as part of implementation (no separate TDD phase).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: Ensure generated types are current and understand the baseline

- [x] T001 Regenerate SDK types to ensure they are current by running `uv run invoke generate`
- [x] T002 Run existing test suite to establish green baseline with `uv run invoke test`

**Checkpoint**: All existing tests pass, generated types are up to date

---

## Phase 2: Foundational (Models Facade)

**Purpose**: Replace `models/__init__.py` with generated type re-exports. This MUST be complete before resource migration since resources import from `models/`.

- [x] T003 Rewrite `python_sdk/src/styrmin_sdk/models/__init__.py` to re-export generated types as aliases (Cluster, Backup, Restore, BackupSchedule, Deployment, ApplicationInstance, Component, Environment, ClusterRef, Task, BackupStorageLocation, ApplicationDriverVersion, HelmChart, Action, ComponentConfig) and keep hand-written imports for ApplicationDriver, ApplicationDriverVersionSummary, Context
- [x] T004 Trim `python_sdk/src/styrmin_sdk/models/driver.py` to keep only ApplicationDriver and ApplicationDriverVersionSummary classes; remove ApplicationDriverVersion, HelmChart, Action, ComponentConfig
- [x] T005 Verify `python_sdk/src/styrmin_sdk/__init__.py` still correctly re-exports all model names from models/ (no changes expected — it imports from models/)
- [x] T006 Run `uv run invoke format lint` to verify formatting after models changes

**Checkpoint**: `from styrmin_sdk import Cluster` resolves to the generated type. Foundation ready for resource migration.

---

## Phase 3: User Story 1 - Type-Safe SDK Operations (Priority: P1) MVP

**Goal**: All resource methods use generated outer wrapper types for response validation instead of hand-written models, eliminating manual dict key access.

**Independent Test**: Call any SDK resource method and confirm the response is produced via generated type validation, with no `result["data"]["key"]` access in the resource layer.

### Implementation for User Story 1

- [ ] T007 [US1] Migrate ClusterResource in `python_sdk/src/styrmin_sdk/resources/clusters.py` — replace `Cluster.model_validate(result["data"]["createCluster"])` pattern with `CreateCluster.model_validate(result["data"]).create_cluster` for create/get/list methods; delete remains unchanged
- [ ] T008 [P] [US1] Migrate BackupResource in `python_sdk/src/styrmin_sdk/resources/backups.py` — replace hand-written model validation with generated outer types (CreateBackup, GetBackup, ListBackups, CreateRestore, GetRestore, ListRestores) for all backup and restore methods; delete methods unchanged
- [ ] T009 [P] [US1] Migrate DeploymentResource in `python_sdk/src/styrmin_sdk/resources/deployments.py` — replace Task/Deployment model validation with generated outer types (Deploy, GetDeployment, UpdateDeployment, UpdateDeploymentVersion, StartComponents, StopComponents, RunJob); get_context method uses REST and Context model so remains unchanged
- [ ] T010 [P] [US1] Migrate EnvironmentResource in `python_sdk/src/styrmin_sdk/resources/environments.py` — replace Environment model validation with generated outer types (CreateEnvironment, GetEnvironment, ListEnvironments); delete unchanged
- [ ] T011 [P] [US1] Migrate DriverResource in `python_sdk/src/styrmin_sdk/resources/drivers.py` — replace ApplicationDriverVersion model validation with generated outer types (LoadRemoteApplicationDriverVersion, LoadLocalApplicationDriverVersion)
- [ ] T012 [P] [US1] Migrate ScheduleResource in `python_sdk/src/styrmin_sdk/resources/schedules.py` — replace BackupSchedule model validation with generated outer types (CreateBackupSchedule, GetBackupSchedule, ListBackupSchedules, UpdateBackupSchedule); delete unchanged
- [ ] T013 [P] [US1] Migrate TaskResource in `python_sdk/src/styrmin_sdk/resources/tasks.py` — replace Task model validation with generated outer types (GetTask, ListTasks)
- [ ] T014 [P] [US1] Migrate BackupStorageLocationResource in `python_sdk/src/styrmin_sdk/resources/backup_storage_locations.py` — replace BackupStorageLocation model validation with generated outer types (CreateBackupStorageLocation, GetBackupStorageLocation, ListBackupStorageLocations, UpdateBackupStorageLocation); delete/assign/unassign unchanged
- [ ] T015 [US1] Update test fixtures and assertions in `python_sdk/tests/test_clusters.py` to account for generated types (response objects are now generated inner types, not hand-written models)
- [ ] T016 [P] [US1] Update test fixtures and assertions in `python_sdk/tests/test_backups.py` for generated types
- [ ] T017 [P] [US1] Update test fixtures and assertions in `python_sdk/tests/test_deployments.py` for generated types (note: Task.type_ rename)
- [ ] T018 [US1] Run full test suite with `uv run invoke test` and fix any failures
- [ ] T019 [US1] Run `uv run invoke format lint` and fix any issues

**Checkpoint**: All resource methods use generated outer wrapper types. All tests pass. No hand-written model validation in resource layer (except Context in get_context).

---

## Phase 4: User Story 2 - Consistent Error Handling (Priority: P2)

**Goal**: Verify that the existing structured error handling (ResourceNotFoundError, ResourceAlreadyExistsError, OperationFailedError) works identically after the model replacement.

**Independent Test**: Trigger known error conditions and verify the same exception types are raised.

### Implementation for User Story 2

- [x] T020 [US2] Verify error handling path in `python_sdk/src/styrmin_sdk/resources/_base.py` — confirm `_check_graphql_errors` still receives the raw result dict and operates correctly since Transport execution is unchanged
- [x] T021 [US2] Review and run error-case tests in `python_sdk/tests/test_clusters.py`, `python_sdk/tests/test_backups.py`, `python_sdk/tests/test_deployments.py` — confirm ResourceNotFoundError, ResourceAlreadyExistsError, OperationFailedError are raised correctly with generated types
- [x] T022 [US2] Run `uv run invoke test` to confirm all error-handling tests pass

**Checkpoint**: Error handling is verified unchanged. All error-case tests pass with same exception types and messages.

---

## Phase 5: User Story 3 - Reduced Model Maintenance Burden (Priority: P3)

**Goal**: Remove hand-written model files that are now replaced by generated type re-exports, reducing duplication to zero.

**Independent Test**: Confirm no hand-written model classes remain that duplicate generated types. Only ApplicationDriver, ApplicationDriverVersionSummary, Context remain.

### Implementation for User Story 3

- [x] T023 [P] [US3] Delete `python_sdk/src/styrmin_sdk/models/cluster.py`
- [x] T024 [P] [US3] Delete `python_sdk/src/styrmin_sdk/models/backup.py`
- [x] T025 [P] [US3] Delete `python_sdk/src/styrmin_sdk/models/deployment.py`
- [x] T026 [P] [US3] Delete `python_sdk/src/styrmin_sdk/models/environment.py`
- [x] T027 [P] [US3] Delete `python_sdk/src/styrmin_sdk/models/task.py`
- [x] T028 [P] [US3] Delete `python_sdk/src/styrmin_sdk/models/backup_storage_location.py`
- [x] T029 [US3] Verify `python_sdk/src/styrmin_sdk/models/__init__.py` has no remaining imports from deleted files
- [x] T030 [US3] Run `uv run invoke test` to confirm all tests still pass after model file deletion
- [x] T031 [US3] Run `uv run invoke format lint` to confirm clean state

**Checkpoint**: Only context.py and driver.py (trimmed) remain in models/. All tests pass.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final cleanup, documentation, and validation

- [x] T032 [P] Verify `from styrmin_sdk import Cluster, Deployment, Task` etc. all resolve correctly by checking `python_sdk/src/styrmin_sdk/__init__.py` imports
- [x] T033 [P] Grep codebase for any remaining references to deleted model files or hand-written model classes
- [x] T034 Run full validation: `uv run invoke test && uv run invoke format lint`
- [x] T035 Document Task.type → Task.type_ breaking change in a CHANGELOG or migration note

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 — core migration work
- **US2 (Phase 4)**: Depends on Phase 3 — verifies error handling after migration
- **US3 (Phase 5)**: Depends on Phase 3 — cleanup of replaced model files
- **Polish (Phase 6)**: Depends on Phases 3-5

### User Story Dependencies

- **User Story 1 (P1)**: Depends on Foundational (Phase 2) — can start after models facade is in place
- **User Story 2 (P2)**: Depends on US1 completion — error handling verification requires migrated resources
- **User Story 3 (P3)**: Depends on US1 completion — cannot delete model files until resources no longer import them directly. Can run in parallel with US2.

### Within User Story 1

- T007 (ClusterResource) should be done first as the reference implementation
- T008-T014 can all run in parallel after T007 establishes the pattern
- T015-T017 (tests) can run in parallel after corresponding resources are migrated
- T018-T019 (validation) run last

### Parallel Opportunities

- T008-T014: All 7 remaining resource migrations can run in parallel (different files)
- T015-T017: All test updates can run in parallel (different files)
- T023-T028: All model file deletions can run in parallel
- US2 and US3 can run in parallel after US1

---

## Parallel Example: User Story 1 Resource Migration

```text
# After T007 (ClusterResource) establishes the pattern, launch all remaining resources:
Task T008: "Migrate BackupResource in python_sdk/src/styrmin_sdk/resources/backups.py"
Task T009: "Migrate DeploymentResource in python_sdk/src/styrmin_sdk/resources/deployments.py"
Task T010: "Migrate EnvironmentResource in python_sdk/src/styrmin_sdk/resources/environments.py"
Task T011: "Migrate DriverResource in python_sdk/src/styrmin_sdk/resources/drivers.py"
Task T012: "Migrate ScheduleResource in python_sdk/src/styrmin_sdk/resources/schedules.py"
Task T013: "Migrate TaskResource in python_sdk/src/styrmin_sdk/resources/tasks.py"
Task T014: "Migrate BackupStorageLocationResource in python_sdk/src/styrmin_sdk/resources/backup_storage_locations.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (verify baseline)
2. Complete Phase 2: Foundational (models facade)
3. Complete Phase 3: User Story 1 (migrate all resources)
4. **STOP and VALIDATE**: All tests pass, all resources use generated types
5. This alone delivers the full type-safety benefit

### Incremental Delivery

1. Setup + Foundational → Models facade in place
2. Add US1 → All resources migrated → Full type safety (MVP!)
3. Add US2 → Error handling verified → Confidence in backward compat
4. Add US3 → Dead model files removed → Clean codebase
5. Polish → Documentation, final validation

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Transport, _queries.py, _base.py, client.py, exceptions.py are UNCHANGED
- The only breaking change is Task.type → Task.type_ — document it
- Delete operations, assign, and unassign need no model validation changes
- get_context (REST endpoint) keeps hand-written Context model
