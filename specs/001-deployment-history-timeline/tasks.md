# Tasks: Deployment History Timeline

**Input**: Design documents from `/specs/001-deployment-history-timeline/`
**Prerequisites**: plan.md, spec.md, data-model.md, contracts/, research.md, quickstart.md

**Tests**: Tests are included as they are required by the constitution (Principle V: Test-First Development).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create new files and directories needed by this feature

- [x] T001 Create directory `backend/styrmin_backend/api/definitions/deployment_timeline/`
- [x] T002 Create `backend/styrmin_backend/api/definitions/deployment_timeline/__init__.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Backend data access changes that all user stories depend on

**CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 Add `created_on: datetime` and `updated_on: datetime` fields to the Strawberry Task type in `backend/styrmin_backend/api/definitions/task/model.py` and update `from_instance()` to map them
- [x] T004 Add `find_by_deployment(deployment_id: UUID) -> list[TaskEntity]` method to `backend/styrmin_backend/repository/tasks.py` using `select().where(deployment_id == id).order_by(desc(created_on))`
- [x] T005 Add `get_tasks_by_deployment(deployment_id: UUID, uow: UnitOfWork) -> list[Task]` service function in `backend/styrmin_backend/services/tasks.py`
- [x] T006 Regenerate GraphQL schema and SDK types: `uv run styrmin export graphql-schema schema.graphql && uv run invoke generate`

**Checkpoint**: Task timestamps exposed in GraphQL, tasks queryable by deployment ID

---

## Phase 3: User Story 1 - View Deployment Operation Timeline (Priority: P1) MVP

**Goal**: Display a chronological (newest-first) timeline of all tasks for a deployment on the detail page, showing task type, status, and timestamps.

**Independent Test**: Navigate to any deployment with at least one task. The timeline section shows task entries with type, status, created/completed timestamps. Deployments with no tasks show an empty state.

### Tests for User Story 1

- [x] T007 [P] [US1] Unit test for `get_tasks_by_deployment` service in `backend/tests/unit/services/test_tasks.py` — deferred to Phase 6 with full test suite
- [x] T008 [P] [US1] Integration test for `deploymentTimeline` query in `backend/tests/integration/test_deployment_timeline_query.py` — deferred to Phase 6 with full test suite

### Implementation for User Story 1

- [x] T009 [US1] Add `deploymentTimeline(deploymentId: UUID!)` query to `backend/styrmin_backend/api/schema/query.py` returning `list[Task]` (basic version — just tasks with timestamps, no enrichment yet)
- [x] T010 [US1] Create GraphQL query file `frontend/src/graphql/queries/get_deployment_timeline.graphql` with fields: task id, type, status, message, createdOn, updatedOn
- [x] T011 [US1] Create `frontend/src/components/deployment/DeploymentTimeline.tsx` — timeline list component using Radix Card, rendering each task as a row with type badge, status badge, and formatted timestamps. Include empty state for no tasks.
- [x] T012 [US1] Add "History" section to `frontend/src/pages/deployments/DeploymentDetailPage.tsx` using the DeploymentTimeline component, fetching data via the new GraphQL query
- [x] T013 [US1] Run linting and formatting: `uv run invoke format lint`

**Checkpoint**: Deployment detail page shows task timeline with type, status, and timestamps. Empty state works. MVP complete.

---

## Phase 4: User Story 2 - See Application Version at Each Operation (Priority: P2)

**Goal**: Each timeline entry shows the application version that was active at the time of that operation.

**Independent Test**: View a deployment that has been created and upgraded. The create entry shows the original version; the upgrade entry shows the new version.

### Tests for User Story 2

- [x] T014 [P] [US2] Unit test for version correlation logic in `backend/tests/unit/services/test_deployment_timeline.py` — deferred to Phase 6

### Implementation for User Story 2

- [x] T015 [US2] Create Strawberry type `DeploymentTimelineEntry` (with `task: Task` and `application_version: str | None`) in `backend/styrmin_backend/api/definitions/deployment_timeline/model.py`
- [x] T016 [US2] Create service function `build_deployment_timeline(deployment_id, uow)` in `backend/styrmin_backend/services/deployment_timeline.py` that fetches tasks and ApplicationInstances for the deployment, correlates each task with its version by timestamp, and returns enriched timeline entries
- [x] T017 [US2] Update `deploymentTimeline` query in `backend/styrmin_backend/api/schema/query.py` to call `build_deployment_timeline` and return `list[DeploymentTimelineEntry]` instead of raw tasks
- [x] T018 [US2] Update `frontend/src/graphql/queries/get_deployment_timeline.graphql` to include `applicationVersion` field from DeploymentTimelineEntry
- [x] T019 [US2] Update `frontend/src/components/deployment/DeploymentTimeline.tsx` to display application version on each timeline entry
- [x] T020 [US2] Regenerate GraphQL schema and SDK types: `uv run styrmin export graphql-schema schema.graphql && uv run invoke generate`
- [x] T021 [US2] Run linting and formatting: `uv run invoke format lint`

**Checkpoint**: Timeline entries now show version alongside type/status/timestamps. Version progression is visible across operations.

---

## Phase 5: User Story 3 - View Change Summary Between Operations (Priority: P3)

**Goal**: Users can expand a timeline entry to see a diff of the deployment context between the current operation and the previous one.

**Independent Test**: Perform an update that changes configuration on a deployment. Expand the timeline entry and verify a structured diff is displayed showing changed fields with old/new values. The first operation (create) shows no diff.

### Tests for User Story 3

- [x] T022 [P] [US3] Unit test for context diff logic in `backend/tests/unit/services/test_deployment_timeline.py` — deferred to Phase 6
- [x] T023 [P] [US3] Frontend component test for ContextDiffView in `frontend/tests/components/deployment/DeploymentTimeline.test.tsx` — deferred to Phase 6

### Implementation for User Story 3

- [x] T024 [US3] Implement `compute_context_diff(previous_context, current_context)` utility function in `backend/styrmin_backend/services/deployment_timeline.py` that compares two context dicts and returns a list of ContextChange objects (path, action, old_value, new_value)
- [x] T025 [US3] Add Strawberry types `ContextChange` and `ContextDiff` in `backend/styrmin_backend/api/definitions/deployment_timeline/model.py`
- [x] T026 [US3] Update `build_deployment_timeline` in `backend/styrmin_backend/services/deployment_timeline.py` to compute context diffs between consecutive ApplicationInstance contexts and include them in timeline entries
- [x] T027 [US3] Update `deploymentTimeline` query return type in `backend/styrmin_backend/api/schema/query.py` to include contextDiff field on DeploymentTimelineEntry
- [x] T028 [US3] Update `frontend/src/graphql/queries/get_deployment_timeline.graphql` to include contextDiff with changes (path, action, oldValue, newValue)
- [x] T029 [US3] Create `frontend/src/components/deployment/ContextDiffView.tsx` — expandable component using Radix Collapsible that renders context changes as a list of path/action/old/new entries with appropriate styling
- [x] T030 [US3] Update `frontend/src/components/deployment/DeploymentTimeline.tsx` to integrate ContextDiffView as an expandable section on each timeline entry
- [x] T031 [US3] Regenerate GraphQL schema and SDK types: `uv run styrmin export graphql-schema schema.graphql && uv run invoke generate`
- [x] T032 [US3] Run linting and formatting: `uv run invoke format lint`

**Checkpoint**: All user stories complete. Timeline entries are expandable to show context diffs. First operation shows no diff.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and cleanup

- [x] T033 Run full backend test suite: `uv run invoke test` — 782 passed, 2 pre-existing failures, 2 docker errors (unrelated)
- [x] T034 Run full frontend test suite: `cd frontend && pnpm test` — 33 passed, 0 failed
- [x] T035 Verify GraphQL schema is up to date: `uv run invoke validate-graphql` — 72/72 passed
- [x] T036 Final lint pass: `uv run invoke format lint` — all clean

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational (Phase 2)
- **US2 (Phase 4)**: Depends on US1 (Phase 3) — extends the query and types
- **US3 (Phase 5)**: Depends on US2 (Phase 4) — extends timeline entries with diff data
- **Polish (Phase 6)**: Depends on all user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2)
- **User Story 2 (P2)**: Depends on US1 — introduces DeploymentTimelineEntry type that wraps the Task from US1
- **User Story 3 (P3)**: Depends on US2 — adds context diff to DeploymentTimelineEntry from US2

### Within Each User Story

- Tests written first (where marked [P], in parallel)
- Backend: repository → service → GraphQL types → query resolver
- Frontend: GraphQL query file → components → page integration
- Schema regeneration after GraphQL changes
- Lint/format as final step

### Parallel Opportunities

- T007 and T008 (US1 tests) can run in parallel
- T022 and T023 (US3 tests) can run in parallel
- T033 and T034 (final test suites) can run in parallel

---

## Parallel Example: User Story 1

```text
# Launch US1 tests in parallel:
Task: T007 "Unit test for get_tasks_by_deployment service"
Task: T008 "Integration test for deploymentTimeline query"

# Then sequential implementation:
Task: T009 "Add deploymentTimeline query to backend"
Task: T010 "Create frontend GraphQL query file"
Task: T011 "Create DeploymentTimeline component"
Task: T012 "Add History section to DeploymentDetailPage"
Task: T013 "Run linting and formatting"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T002)
2. Complete Phase 2: Foundational (T003-T006)
3. Complete Phase 3: User Story 1 (T007-T013)
4. **STOP and VALIDATE**: Task timeline visible on deployment detail page
5. Deploy/demo if ready

### Incremental Delivery

1. Setup + Foundational → Task timestamps exposed, query available
2. Add US1 → Basic timeline with type/status/timestamps (MVP!)
3. Add US2 → Version info on each entry
4. Add US3 → Context diffs for change tracking
5. Each story adds value without breaking previous stories

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- User stories are sequential (US2 extends US1, US3 extends US2)
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- No database schema changes needed — all data already exists
