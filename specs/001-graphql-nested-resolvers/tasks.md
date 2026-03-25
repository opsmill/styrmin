# Tasks: Add Nested Object Resolvers to GraphQL Schema

**Input**: Design documents from `/specs/001-graphql-nested-resolvers/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Tests are included as specified in plan.md (V. Test-First Development) and spec.md constitution check.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: No new project setup needed — this feature modifies existing files only. This phase covers research verification and pattern confirmation.

- [x] T001 Verify existing resolver patterns in backend/styrmin_backend/api/definitions/deployment/model.py (confirm async UoW pattern)
- [x] T002 Verify existing sync resolver pattern in backend/styrmin_backend/api/definitions/application_driver/model.py (confirm eager-loaded relationship pattern)
- [x] T003 [P] Verify UoW repository availability for all needed repositories (environments, application_driver_versions, deployments, application_instances, backups)

**Checkpoint**: Patterns confirmed — implementation can begin

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: No foundational infrastructure needed — all repositories, UoW, and `from_instance()` methods already exist. No blocking prerequisites.

**⚠️ CRITICAL**: Skipped — proceed directly to user story phases.

---

## Phase 3: User Story 1 - Fetch Deployment with Related Entities (Priority: P1) 🎯 MVP

**Goal**: Add `environment` and `applicationDriverVersion` nested resolvers to the Deployment type so clients can fetch deployment details with related entities in a single query.

**Independent Test**: Query a deployment with nested `environment` and `applicationDriverVersion` fields and verify the related objects are returned inline. Verify existing `environmentId` and `applicationDriverVersionId` fields still work.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T004 [P] [US1] Write functional test for Deployment.environment resolver in backend/tests/functional/test_api.py — query deployment with nested `environment` field, verify environment object returned
- [x] T005 [P] [US1] Write functional test for Deployment.applicationDriverVersion resolver in backend/tests/functional/test_api.py — query deployment with nested `applicationDriverVersion` field, verify ADV object returned
- [x] T006 [P] [US1] Write functional test for backward compatibility in backend/tests/functional/test_api.py — query deployment with only `environmentId` field, verify it still works unchanged

### Implementation for User Story 1

- [x] T007 [P] [US1] Add async `environment` resolver to Deployment type in backend/styrmin_backend/api/definitions/deployment/model.py — use UoW pattern, non-nullable, raise ValueError on integrity violation (FR-001, FR-013)
- [x] T008 [P] [US1] Add async `application_driver_version` resolver to Deployment type in backend/styrmin_backend/api/definitions/deployment/model.py — use UoW pattern, non-nullable, raise ValueError on integrity violation (FR-002, FR-013)
- [x] T009 [US1] Run tests for US1 resolvers and verify they pass

**Checkpoint**: Deployment nested resolvers functional — clients can query deployment → environment and deployment → applicationDriverVersion

---

## Phase 4: User Story 2 - Traverse the Application Driver Version Chain (Priority: P2)

**Goal**: Add `applicationDriver` resolver on ApplicationDriverVersion and `applicationDriverVersion` resolver on ApplicationInstance so clients can traverse the full driver hierarchy.

**Independent Test**: Query an ApplicationDriverVersion with nested `applicationDriver` field and an ApplicationInstance with nested `applicationDriverVersion` field, verify both return correct related objects.

### Tests for User Story 2

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T010 [P] [US2] Write functional test for ApplicationDriverVersion.applicationDriver resolver in backend/tests/functional/test_api.py — verify parent driver object returned (sync resolver)
- [x] T011 [P] [US2] Write functional test for ApplicationInstance.applicationDriverVersion resolver in backend/tests/functional/test_api.py — verify ADV object returned

### Implementation for User Story 2

- [x] T012 [P] [US2] Add sync `application_driver` resolver to ApplicationDriverVersion type in backend/styrmin_backend/api/definitions/application_driver/model.py — use self.instance.application_driver (already eager-loaded), non-nullable (FR-003)
- [x] T013 [P] [US2] Add async `application_driver_version` resolver to ApplicationInstance type in backend/styrmin_backend/api/definitions/deployment/model.py — use UoW pattern, non-nullable, raise ValueError on integrity violation (FR-004, FR-013)
- [x] T014 [US2] Run tests for US2 resolvers and verify they pass

**Checkpoint**: Driver hierarchy traversable — clients can query ADV → ApplicationDriver and ApplicationInstance → ADV

---

## Phase 5: User Story 3 - Navigate from Tasks, Backups, and Restores to Parent Entities (Priority: P3)

**Goal**: Add nested parent resolvers on Task, BackupSchedule, Backup, and Restore types so clients can traverse from operational entities to their parent entities.

**Independent Test**: Query each entity type (Task, BackupSchedule, Backup, Restore) with its new nested parent field and verify the correct parent object is returned. Test nullable case for Task.deployment.

### Tests for User Story 3

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T015 [P] [US3] Write functional test for Task.deployment resolver in backend/tests/functional/test_api.py — verify deployment object returned, and verify null returned when deployment_id is null (FR-005, FR-010)
- [x] T016 [P] [US3] Write functional test for BackupSchedule.deployment resolver in backend/tests/functional/test_api.py — verify deployment object returned (FR-006)
- [x] T017 [P] [US3] Write functional test for Backup.instance resolver in backend/tests/functional/test_api.py — verify ApplicationInstance object returned (FR-007)
- [x] T018 [P] [US3] Write functional test for Restore.backup resolver in backend/tests/functional/test_api.py — verify Backup object returned (FR-008)

### Implementation for User Story 3

- [x] T019 [P] [US3] Add async `deployment` resolver to Task type in backend/styrmin_backend/api/definitions/task/model.py — use UoW pattern, nullable (return None if deployment_id is None), FR-005/FR-010
- [x] T020 [P] [US3] Add async `deployment` resolver to BackupSchedule type in backend/styrmin_backend/api/definitions/backup/schedule.py — use UoW pattern, non-nullable, raise ValueError on integrity violation (FR-006, FR-013)
- [x] T021 [P] [US3] Add async `instance` resolver to Backup type in backend/styrmin_backend/api/definitions/backup/backup.py — use UoW pattern, non-nullable, rename existing `instance` Private field to avoid conflict, raise ValueError on integrity violation (FR-007, FR-013)
- [x] T022 [P] [US3] Add async `backup` resolver to Restore type in backend/styrmin_backend/api/definitions/backup/restore.py — use UoW pattern, non-nullable, rename existing `instance` Private field to avoid conflict, raise ValueError on integrity violation (FR-008, FR-013)
- [x] T023 [US3] Run tests for US3 resolvers and verify they pass

**Checkpoint**: All 8 nested resolvers functional — operational entities can traverse to their parents

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Schema regeneration, linting, and full test validation

- [x] T024 Regenerate GraphQL schema via `uv run styrmin export graphql-schema schema.graphql` (FR-011)
- [x] T025 Regenerate SDK types via `uv run invoke generate` (FR-011)
- [x] T026 Run `uv run invoke format lint` to format and lint all modified files
- [x] T027 Run full test suite via `uv run invoke test` to verify no regressions (FR-009, SC-005)
- [x] T028 Run quickstart.md validation — manually verify example queries from quickstart.md work against the updated schema

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — pattern verification only
- **Foundational (Phase 2)**: Skipped — no new infrastructure needed
- **User Story 1 (Phase 3)**: Depends on Phase 1 completion
- **User Story 2 (Phase 4)**: Depends on Phase 1 completion — independent of US1
- **User Story 3 (Phase 5)**: Depends on Phase 1 completion — independent of US1 and US2
- **Polish (Phase 6)**: Depends on ALL user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: No dependencies on other stories. Modifies `deployment/model.py`
- **User Story 2 (P2)**: No dependencies on other stories. Modifies `application_driver/model.py` and `deployment/model.py` (different type than US1)
- **User Story 3 (P3)**: No dependencies on other stories. Modifies `task/model.py`, `backup/schedule.py`, `backup/backup.py`, `backup/restore.py`

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Implementation tasks marked [P] within a story can run in parallel (different files)
- Run tests after implementation to verify they pass

### Parallel Opportunities

- **Phase 1**: T001, T002, T003 — T002 and T003 are parallel
- **Phase 3 (US1)**: T004, T005, T006 tests in parallel; T007, T008 implementation in parallel
- **Phase 4 (US2)**: T010, T011 tests in parallel; T012, T013 implementation in parallel
- **Phase 5 (US3)**: T015–T018 tests in parallel; T019–T022 implementation in parallel (all different files)
- **Cross-story**: US1, US2, US3 can all proceed in parallel after Phase 1 (different files)

---

## Parallel Example: User Story 1

```bash
# Launch all tests for User Story 1 together:
Task: "Write functional test for Deployment.environment resolver in backend/tests/functional/test_api.py"
Task: "Write functional test for Deployment.applicationDriverVersion resolver in backend/tests/functional/test_api.py"
Task: "Write functional test for backward compatibility in backend/tests/functional/test_api.py"

# Launch both implementation tasks together (same file but different methods):
Task: "Add async environment resolver to Deployment type in backend/styrmin_backend/api/definitions/deployment/model.py"
Task: "Add async application_driver_version resolver to Deployment type in backend/styrmin_backend/api/definitions/deployment/model.py"
```

## Parallel Example: User Story 3

```bash
# Launch all four test tasks together (same test file but different test functions):
Task: "Write functional test for Task.deployment resolver"
Task: "Write functional test for BackupSchedule.deployment resolver"
Task: "Write functional test for Backup.instance resolver"
Task: "Write functional test for Restore.backup resolver"

# Launch all four implementation tasks together (different files):
Task: "Add async deployment resolver to Task type in task/model.py"
Task: "Add async deployment resolver to BackupSchedule type in backup/schedule.py"
Task: "Add async instance resolver to Backup type in backup/backup.py"
Task: "Add async backup resolver to Restore type in backup/restore.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (pattern verification)
2. Complete Phase 3: User Story 1 (Deployment → Environment, Deployment → ADV)
3. **STOP and VALIDATE**: Test US1 independently
4. Run Phase 6 (schema regeneration + lint) for MVP deploy

### Incremental Delivery

1. Complete Phase 1 → Patterns verified
2. Add User Story 1 → Test independently → Deploy/Demo (MVP!)
3. Add User Story 2 → Test independently → Deploy/Demo
4. Add User Story 3 → Test independently → Deploy/Demo
5. Complete Phase 6 → Full polish and validation

### Parallel Team Strategy

With multiple developers:

1. Team completes Phase 1 (pattern verification)
2. Once Phase 1 is done:
   - Developer A: User Story 1 (deployment/model.py)
   - Developer B: User Story 2 (application_driver/model.py + deployment/model.py ApplicationInstance)
   - Developer C: User Story 3 (task/model.py, backup/*.py)
3. Stories complete and integrate independently
4. Final Phase 6 after all stories merge

---

## Notes

- [P] tasks = different files or independent methods, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story is independently completable and testable
- All resolvers follow existing codebase patterns (async UoW or sync eager-load)
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
