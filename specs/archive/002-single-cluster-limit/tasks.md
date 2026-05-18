# Tasks: Enforce Single-Cluster Limit

**Input**: Design documents from `/specs/002-single-cluster-limit/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Required per constitution (Principle V: Test-First Development) and spec acceptance criteria.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Foundational (Blocking Prerequisites)

**Purpose**: Add the shared error type needed by the backend enforcement logic

**⚠️ CRITICAL**: US1 implementation cannot begin until this phase is complete

- [x] T001 Add `ClusterLimitReachedError` exception class with error code `"CLUSTER_LIMIT_REACHED"` and message `"Only one cluster is allowed. Delete the existing cluster before creating a new one."` in `backend/styrmin_backend/services/exceptions.py`

**Checkpoint**: Error type available for use in service layer

---

## Phase 2: User Story 1 - Prevent Creating a Second Cluster via API (Priority: P1) 🎯 MVP

**Goal**: The API rejects `createCluster` when a cluster already exists and defaults the cluster name to "default" when not specified.

**Independent Test**: Send a `createCluster` mutation when a cluster exists — should return `CLUSTER_LIMIT_REACHED` error. Send `createCluster` without a name — should create cluster named "default".

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T002 [P] [US1] Add test `test_create_cluster_raises_error_when_cluster_exists` that creates a cluster, then asserts a second `create_cluster` call raises `ClusterLimitReachedError` in `backend/tests/unit/services/test_cluster_services.py`
- [x] T003 [P] [US1] Add test `test_create_cluster_uses_default_name` that calls `create_cluster` without specifying a name and asserts the created cluster has name `"default"` in `backend/tests/unit/services/test_cluster_services.py`
- [x] T004 [P] [US1] Add test `test_create_cluster_after_delete_succeeds` that creates a cluster, deletes it, then creates another and asserts success in `backend/tests/unit/services/test_cluster_services.py`

### Implementation for User Story 1

- [x] T005 [US1] Modify `create_cluster` in `backend/styrmin_backend/services/clusters.py`: make `name` parameter optional with default `"default"`, add existence check using `uow.clusters.get_all()` before the existing name-uniqueness check — raise `ClusterLimitReachedError` if any cluster exists
- [x] T006 [US1] Update `create_cluster` mutation signature in `backend/styrmin_backend/api/schema/mutation.py`: change `name: str` to `name: str = "default"`
- [x] T007 [US1] Regenerate GraphQL schema by running `uv run styrmin export graphql-schema schema.graphql`
- [x] T008 [US1] Regenerate SDK types by running `uv run invoke generate`
- [x] T009 [US1] Run backend tests with `uv run invoke test` and verify all tests pass including new constraint tests

**Checkpoint**: Backend enforces single-cluster limit. API rejects second cluster creation with typed error. Default name "default" works. All backend tests pass.

---

## Phase 3: User Story 2 - Hide Cluster Creation in Frontend When Cluster Exists (Priority: P2)

**Goal**: The Settings page hides the "New Cluster" button when a cluster exists, displays the cluster in a single-item layout instead of a grid, and pre-fills the name field with "default" in the creation dialog.

**Independent Test**: Load Settings page with a cluster — "New Cluster" button should be hidden and cluster displays in single-item layout. Load with no cluster — button visible and name field pre-filled with "default".

### Implementation for User Story 2

- [x] T010 [P] [US2] Update `CreateClusterDialog` in `frontend/src/pages/settings/CreateClusterDialog.tsx`: set `defaultValues: { name: "default" }` in the `useForm` call so the name field is pre-filled
- [x] T011 [US2] Update `SettingsPage` in `frontend/src/pages/settings/SettingsPage.tsx`: conditionally hide `CreateClusterDialog` when `data.clusters.length > 0`, replace the multi-column grid with a single-item cluster display when a cluster exists, keep empty state with "New Cluster" button when no clusters exist

**Checkpoint**: Frontend reflects single-cluster semantics. Creation button hidden when cluster exists. Default name pre-filled in dialog.

---

## Phase 4: User Story 3 - Delete the Only Cluster (Priority: P3)

**Goal**: Verify that deleting the only cluster works correctly and the UI reverts to showing the creation option.

**Independent Test**: Delete the existing cluster — Settings page should show empty state with "New Cluster" button visible.

### Implementation for User Story 3

- [x] T012 [US3] Verify existing `delete_cluster` service in `backend/styrmin_backend/services/clusters.py` has no changes needed — deletion of the only cluster should already work. If the delete-then-create test (T004) passes, this is confirmed at the service level.

**Checkpoint**: Deletion flow works correctly. After deletion, cluster creation is re-enabled in both API and UI.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and formatting

- [x] T013 Run `uv run invoke format lint` to format and lint all backend code
- [x] T014 Run `cd frontend && pnpm lint` to lint frontend code
- [x] T015 Verify `schema.graphql` is up to date by running `uv run styrmin export graphql-schema schema.graphql` and confirming no diff
- [x] T016 Verify generated SDK types are up to date by running `uv run invoke generate` and confirming no diff

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 1)**: No dependencies — can start immediately
- **US1 (Phase 2)**: Depends on Phase 1 (error type)
- **US2 (Phase 3)**: Can start after Phase 1 (frontend is independent of backend service changes), but ideally after Phase 2 so regenerated types are available
- **US3 (Phase 4)**: Depends on Phase 2 (needs service changes in place to verify delete+create cycle)
- **Polish (Phase 5)**: Depends on all phases complete

### User Story Dependencies

- **US1 (P1)**: Depends on Foundational only — core backend enforcement
- **US2 (P2)**: Frontend-only changes can be developed in parallel with US1, but schema regeneration (T007-T008) should complete first for type consistency
- **US3 (P3)**: Verification task — depends on US1 being complete

### Within Each User Story

- Tests (T002-T004) MUST be written and FAIL before implementation (T005-T006)
- Service layer (T005) before GraphQL layer (T006)
- GraphQL change (T006) before schema regeneration (T007-T008)
- Schema regeneration (T007) before SDK regeneration (T008)

### Parallel Opportunities

- T002, T003, T004 can run in parallel (same file but independent test functions)
- T010 can run in parallel with any US1 task (different file, no dependency)
- T013 and T014 can run in parallel (backend vs frontend linting)

---

## Parallel Example: User Story 1

```text
# Write all US1 tests in parallel:
Task T002: "test_create_cluster_raises_error_when_cluster_exists"
Task T003: "test_create_cluster_uses_default_name"
Task T004: "test_create_cluster_after_delete_succeeds"

# Then implement sequentially:
Task T005: Service layer changes (depends on tests existing)
Task T006: GraphQL mutation change (depends on T005)
Task T007: Schema regeneration (depends on T006)
Task T008: SDK regeneration (depends on T007)
Task T009: Run tests (depends on T005-T008)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Add error type
2. Complete Phase 2: Backend enforcement + default name + tests
3. **STOP and VALIDATE**: Run `uv run invoke test` — all tests pass
4. Backend is now protected against multi-cluster creation

### Incremental Delivery

1. Phase 1 + Phase 2 → Backend enforcement complete (MVP)
2. Add Phase 3 → Frontend reflects single-cluster semantics
3. Add Phase 4 → Deletion flow verified end-to-end
4. Phase 5 → Final lint/format/validation pass

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Tests are required per constitution Principle V
- Schema regeneration (T007-T008) must happen after backend changes
- No database migrations needed — all changes are at service/API layer
- Commit after each phase checkpoint
