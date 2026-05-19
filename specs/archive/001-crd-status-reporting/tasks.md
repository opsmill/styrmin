# Tasks: CRD Status Reporting

**Input**: Design documents from `/specs/001-crd-status-reporting/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/graphql-schema.md

**Tests**: Included per Constitution Principle V (Test-First Development).

**Organization**: Tasks grouped by user story for independent implementation and testing.

**Dependency**: This feature requires `001-agent-status-reporting` to be merged first.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Exact file paths included in descriptions

---

## Phase 1: Setup

**Purpose**: Verify prerequisite feature is available and review patterns.

- [x] T001 Verify `001-agent-status-reporting` branch is merged and available. Confirm `backend/styrmin_backend/agent/status/reporter.py`, `backend/styrmin_backend/services/pod_status.py`, and `backend/styrmin_backend/repository/pod_status.py` exist.
- [x] T002 Review CRD status schema in `backend/styrmin_backend/operator/crd/status.py` and CRD config constants in `backend/styrmin_backend/operator/config.py` (CRD_GROUP, CRD_VERSION, CRD_PLURAL) to confirm conventions.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Database model, migration, repository, Strawberry types, and UoW registration that ALL user stories depend on.

**CRITICAL**: No user story work can begin until this phase is complete.

- [x] T003 Add `DeploymentCrdStatus` SQLModel to `backend/styrmin_backend/db/models.py` per data-model.md. Fields: deployment_id (FK with ondelete CASCADE, UNIQUE), phase (str), message (str, nullable), conditions (JSON, nullable), managed_resource_counts (JSON, nullable), last_polled_at (datetime). Add `crd_status` one-to-one relationship on Deployment with cascade delete-orphan using `uselist=False`.
- [x] T004 Create Alembic migration for `deploymentcrdstatus` table in `backend/styrmin_backend/db/migrations/versions/`. Include UniqueConstraint on deployment_id and ForeignKeyConstraint with `ondelete="CASCADE"`.
- [x] T005 Create `backend/styrmin_backend/repository/deployment_crd_status.py` with abstract `DeploymentCrdStatusRepository(BaseRepository[DeploymentCrdStatus])` defining `find_by_deployment(deployment_id) -> DeploymentCrdStatus | None` and `upsert(crd_status) -> DeploymentCrdStatus`. Implement `SQLModelDeploymentCrdStatusRepository`. Follow the pattern in `repository/pod_status.py`.
- [x] T006 Register `deployment_crd_statuses: DeploymentCrdStatusRepository` on abstract `UnitOfWork` class and instantiate `SQLModelDeploymentCrdStatusRepository` in `SqlModelUnitOfWork.__aenter__()` in `backend/styrmin_backend/services/unit_of_work.py`.
- [x] T007 [P] Create Strawberry types in `backend/styrmin_backend/api/definitions/deployment_crd_status/model.py`: `CrdConditionType` (type: str, status: str, reason: str|None, message: str|None, last_transition_time: datetime|None), `ManagedResourceCountsType` (network_policies: int, secrets: int, helm_releases: int, services: int, middlewares: int), `DeploymentCrdStatusType` (all fields, `from_instance()` classmethod). Create `__init__.py`.
- [x] T008 [P] Create Strawberry input types in `backend/styrmin_backend/api/definitions/deployment_crd_status/model.py`: `CrdConditionInput`, `ManagedResourceCountsInput`, `DeploymentCrdStatusReportInput`, `ReportCrdStatusesResponse`.

**Checkpoint**: Data layer and type definitions ready. User story implementation can begin.

---

## Phase 3: User Story 3 — Agent Periodically Collects CRD Status (Priority: P1)

**Goal**: The agent collects StyrminDeployment CRD status alongside pod statuses and reports it to the backend. Implemented first because it produces the data other stories consume.

**Independent Test**: Run agent against a cluster with StyrminDeployment CRDs; verify backend receives CRD status updates.

### Tests for User Story 3

- [x] T009 [P] [US3] Write unit tests for CRD status collection in `backend/tests/unit/services/test_deployment_crd_status_service.py`. Test: upsert creates new record, upsert updates existing record, missing CRD phase defaults to "Pending".

### Implementation for User Story 3

- [x] T010 [US3] Create CRD status service in `backend/styrmin_backend/services/deployment_crd_status.py` with: `report_crd_statuses(reports: list[dict], uow) -> tuple[int, int]` — upserts CRD status per deployment and updates Deployment.status based on CRD phase mapping (Pending/Creating* -> pending, Ready -> running, Failed -> failed, Deleting -> no change). Single UoW for the entire batch. Return (statuses_updated, deployments_updated).
- [x] T011 [US3] Add `reportCrdStatuses` mutation to `backend/styrmin_backend/api/schema/mutation.py`. Accept `reports: list[DeploymentCrdStatusReportInput]`, call `report_crd_statuses` service, return `ReportCrdStatusesResponse`. Follow the `report_pod_statuses` mutation pattern.
- [x] T012 [US3] Create `.graphql` query file at `python_sdk/src/styrmin_sdk/graphql/report_crd_statuses.graphql` with the `ReportCrdStatuses` mutation operation per contracts/graphql-schema.md.
- [x] T013 [US3] Extend `backend/styrmin_backend/agent/status/reporter.py` to collect CRD status: (a) Add `_collect_crd_status(namespace, crd_name)` function that calls `get_custom_resource()` with group=`styrmin.io`, version=`v1alpha1`, plural=`styrmindeployments`. Extract phase, message, conditions, managedResources from response. Return `None` on `CustomResourceNotFound`. Default missing status to phase="Pending". (b) In `_poll_once()`, after collecting pod statuses, also call `_collect_crd_status()` for each deployment. Build a separate `crd_reports` list. (c) Add `_report_crd_statuses_to_backend()` to send the CRD reports via the new mutation.
- [x] T014 [US3] Create `.graphql` query file for the agent at `backend/styrmin_backend/agent/status/queries/report_crd_statuses.graphql` with the mutation (if using `load_query` pattern, matching the existing `report_pod_statuses.graphql`).
- [x] T015 [US3] Regenerate GraphQL schema: `uv run styrmin export graphql-schema schema.graphql` and `uv run invoke generate`.
- [x] T016 [US3] Run `uv run invoke format lint` to verify all new code passes.

**Checkpoint**: Agent reports CRD statuses to backend. CRD status records exist in DB. Deployment status updated from CRD phase.

---

## Phase 4: User Story 2 — View CRD Phase and Conditions via API (Priority: P1)

**Goal**: Operators can query CRD status details for any deployment via the API.

**Independent Test**: Query deployment's `crdStatus` field; verify phase, conditions, and resource counts are returned.

### Tests for User Story 2

- [x] T017 [P] [US2] Write integration test for `Deployment.crdStatus` resolver in `backend/tests/integration/test_deployment_crd_status_api.py`. Test: resolver returns CRD status with phase and conditions, resolver returns null when no CRD status exists.

### Implementation for User Story 2

- [x] T018 [US2] Add `get_deployment_crd_status(deployment_id, uow) -> DeploymentCrdStatus | None` service function to `backend/styrmin_backend/services/deployment_crd_status.py`.
- [x] T019 [US2] Add `crd_status` resolver field to Deployment Strawberry type in `backend/styrmin_backend/api/definitions/deployment/model.py`. Use `@strawberry.field` async resolver that calls `get_deployment_crd_status` service. Return `DeploymentCrdStatusType | None`.
- [x] T020 [US2] Create `.graphql` query file at `python_sdk/src/styrmin_sdk/graphql/get_deployment_crd_status.graphql` with the `GetDeploymentCrdStatus` query per contracts/graphql-schema.md.
- [x] T021 [US2] Regenerate GraphQL schema and SDK types: `uv run styrmin export graphql-schema schema.graphql && uv run invoke generate`.
- [x] T022 [US2] Run `uv run invoke format lint` to verify all new code passes.

**Checkpoint**: Operators can query CRD status. US2 acceptance scenarios are testable.

---

## Phase 5: User Story 1 — Deployment Status Reflects CRD Phase (Priority: P1)

**Goal**: Deployment.status automatically updates based on CRD phase. This story is already implemented as part of US3 (the service in T010 handles the phase-to-status mapping). This phase validates the behavior end-to-end.

**Independent Test**: Deploy an app, watch Deployment.status change as CRD progresses through phases.

### Tests for User Story 1

- [x] T023 [US1] Write unit tests for CRD phase-to-Deployment status mapping in `backend/tests/unit/services/test_deployment_crd_status_service.py` (extend from T009). Test: phase "Ready" -> status "running", phase "Failed" -> status "failed", phase "CreatingHelmRelease" -> status "pending", phase "Deleting" -> status unchanged. Test that Deployment status is actually updated in the UoW.
- [x] T024 [US1] Write unit test for edge case: CRD reports "Ready" but Deployment was previously "failed" — Deployment status should update to "running" (CRD takes precedence).

**Checkpoint**: Deployment status sync is fully tested. US1 acceptance scenarios verified.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, cleanup, and schema regeneration.

- [x] T025 Update `backend/tests/unit/services/fakes.py` with `FakeDeploymentCrdStatusRepository` following the pattern of `FakePodStatusRepository`. Update `FakeUnitOfWork` to include `deployment_crd_statuses`.
- [x] T026 Run full test suite with `uv run invoke test` to verify no regressions.
- [x] T027 Run `uv run invoke format lint` on all modified files.
- [x] T028 Validate all `.graphql` query files with `uv run invoke validate-graphql`.
- [x] T029 Verify `schema.graphql` is up to date with `uv run styrmin export graphql-schema schema.graphql`.
- [x] T030 Verify generated SDK types are up to date with `uv run invoke generate`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS all user stories
- **Phase 3 (US3)**: Depends on Phase 2 — produces data for US1 and US2
- **Phase 4 (US2)**: Depends on Phase 2 — can run in parallel with US3 (different files)
- **Phase 5 (US1)**: Depends on Phase 3 (phase mapping is in the service) — validation/testing phase
- **Phase 6 (Polish)**: Depends on all user stories

### User Story Dependencies

- **US3 (Agent Collects CRD Status)**: Depends only on Foundational. Produces data for US1/US2.
- **US2 (View CRD Status via API)**: Depends only on Foundational. Can run in parallel with US3.
- **US1 (Deployment Status Reflects CRD Phase)**: Depends on US3 (mapping logic in the service). Primarily a testing/validation phase.

### Parallel Opportunities

- T003 model + T007/T008 Strawberry types can run in parallel (different files)
- US2 and US3 implementation can proceed in parallel after foundational phase
- T009 + T017 tests can run in parallel

---

## Implementation Strategy

### MVP First (US3 + US2)

1. Complete Phase 1: Setup (verify prerequisites)
2. Complete Phase 2: Foundational (model, migration, repository, types)
3. Complete Phase 3: US3 — Agent collects and reports CRD status, Deployment status synced
4. Complete Phase 4: US2 — CRD status queryable via API
5. Complete Phase 5: US1 — Validate phase-to-status mapping end-to-end
6. **STOP and VALIDATE**: Full flow works (agent polls CRD -> backend stores -> Deployment status updates -> API returns)

### Incremental Delivery

1. Foundational -> Data layer ready
2. US3 -> Agent collects CRD status, Deployment status syncs -> Core value delivered
3. US2 -> CRD details queryable -> Diagnostic capability added
4. US1 -> End-to-end validation -> Confidence in correctness

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story
- Constitution requires tests (Principle V)
- This feature is smaller than agent-status-reporting — fewer new files, more extension of existing patterns
- The CRD phase-to-Deployment status mapping is the key business logic (in the service at T010)
- Schema regeneration (T015, T021) must happen after API changes
- T025 (fakes update) should be done before running tests but is listed in Polish for clarity
