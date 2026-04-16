# Tasks: Agent Status Reporting

**Input**: Design documents from `/specs/001-agent-status-reporting/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/graphql-schema.md

**Tests**: Included per Constitution Principle V (Test-First Development).

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Exact file paths included in descriptions

---

## Phase 1: Setup

**Purpose**: No new project setup needed — this feature extends the existing backend.

- [x] T001 Review existing patterns in `backend/styrmin_backend/db/models.py`, `backend/styrmin_backend/repository/application_instance.py`, and `backend/styrmin_backend/api/definitions/deployment/model.py` to confirm conventions before implementation

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Database model, migration, repository, and Strawberry types that ALL user stories depend on.

**CRITICAL**: No user story work can begin until this phase is complete.

- [x] T002 Add `PodPhase` enum and `PodStatus` SQLModel to `backend/styrmin_backend/db/models.py` per data-model.md. Fields: deployment_id (FK), pod_name, namespace, phase (PodPhase enum), ready (bool), restart_count (int), container_statuses (JSON), node_name, started_at, last_polled_at. Add UniqueConstraint on (deployment_id, pod_name). Add `pod_statuses` relationship on Deployment with cascade delete-orphan.
- [x] T003 Generate Alembic migration for the new `podstatus` table in `backend/styrmin_backend/db/migrations/versions/`. Run `uv run alembic revision --autogenerate -m "add_pod_status"` and verify the generated migration.
- [x] T004 Create `backend/styrmin_backend/repository/pod_status.py` with abstract `PodStatusRepository(BaseRepository[PodStatus])` defining `find_by_deployment(deployment_id) -> list[PodStatus]`, `upsert(pod_status) -> PodStatus`, `delete_stale(deployment_id, active_pod_names) -> int`. Implement `SQLModelPodStatusRepository(BaseSQLModelRepository[PodStatus], PodStatusRepository)` following the pattern in `repository/application_instance.py`.
- [x] T005 Register `pod_statuses: PodStatusRepository` on abstract `UnitOfWork` class and instantiate `SQLModelPodStatusRepository` in `SqlModelUnitOfWork.__aenter__()` in `backend/styrmin_backend/services/unit_of_work.py`
- [x] T006 Create Strawberry GraphQL types in `backend/styrmin_backend/api/definitions/pod_status/model.py`: `PodPhaseType` (enum), `ContainerStatusType` (type with name, ready, state, restart_count, image, started_at), `PodStatusType` (type with all fields from data-model.md, `strawberry.Private[PodStatus]` for DB instance, `from_instance()` classmethod). Create `__init__.py` in the same directory.
- [x] T007 Create Strawberry input types in `backend/styrmin_backend/api/definitions/pod_status/model.py`: `PodStatusInput` (input with pod_name, namespace, phase, ready, restart_count, container_statuses, node_name, started_at), `DeploymentPodStatusReport` (input with deployment_id, pods list), `ReportPodStatusesResponse` (type with success, message, pods_updated, pods_removed).

**Checkpoint**: Data layer and type definitions ready. User story implementation can begin.

---

## Phase 3: User Story 2 — Agent Periodically Reports Status to Backend (Priority: P1)

**Goal**: The agent collects pod status from K8s and reports it to the backend via GraphQL mutation. This story is implemented first because it produces the data that US1 reads.

**Independent Test**: Run the agent against a cluster with managed namespaces; verify the backend database receives pod status records at the configured interval.

### Tests for User Story 2

- [x] T008 [P] [US2] Write unit tests for `upsert_pod_statuses` and `delete_stale_pod_statuses` service functions in `backend/tests/unit/test_pod_status_service.py`. Test: upsert creates new records, upsert updates existing records (matched on deployment_id + pod_name), stale pods are removed, empty pod list clears all records for a deployment.
- [ ] T009 [P] [US2] Write integration test for `reportPodStatuses` mutation in `backend/tests/integration/test_pod_status_api.py`. Test: mutation creates pod status records, mutation updates existing records on re-report, mutation removes pods no longer present, mutation returns correct counts (pods_updated, pods_removed).

### Implementation for User Story 2

- [x] T010 [US2] Create pod status service in `backend/styrmin_backend/services/pod_status.py` with: `upsert_pod_statuses(deployment_id, pods: list, uow) -> tuple[int, int]` (returns updated_count, removed_count) — upserts each pod by (deployment_id, pod_name) and deletes stale records. Follow the UnitOfWork pattern from `services/tasks.py`.
- [x] T011 [US2] Add `reportPodStatuses` mutation to `backend/styrmin_backend/api/schema/mutation.py`. Accept `reports: list[DeploymentPodStatusReport]`, call `upsert_pod_statuses` service for each report, return `ReportPodStatusesResponse` with aggregated counts. Follow the `callback()` mutation pattern.
- [x] T012 [US2] Create `.graphql` query file at `python_sdk/src/styrmin_sdk/graphql/report_pod_statuses.graphql` with the `ReportPodStatuses` mutation operation per contracts/graphql-schema.md.
- [x] T013 [US2] Add `list_pods(namespace, client)` function to `backend/styrmin_backend/agent/service/kubernetes/primitives.py` using `@inject` and `Depends(get_api_client)` pattern. Returns `V1PodList` via `CoreV1Api().list_namespaced_pod(namespace)`.
- [x] T014 [US2] Create status reporter module at `backend/styrmin_backend/agent/status/reporter.py` with: (a) `collect_pod_statuses(namespace) -> list[dict]` — calls `list_pods()`, extracts pod_name, phase, ready, restart_count, container_statuses, node_name, started_at from K8s response; (b) `report_statuses_to_backend(reports, graphql_url)` — sends `ReportPodStatuses` mutation via HTTP POST; (c) `run_status_reporter(graphql_url, interval)` — async loop that queries backend for active deployments, derives namespaces via `get_kubernetes_reference()`, collects pod statuses per namespace, batches reports, sends to backend. Respects `_shutdown` event for graceful exit.
- [x] T015 [US2] Add `STYRMIN_AGENT_STATUS_POLL_INTERVAL` config constant to `backend/styrmin_backend/agent/status/reporter.py` using `int(os.environ.get("STYRMIN_AGENT_STATUS_POLL_INTERVAL", "60"))` pattern per research.md R5.
- [x] T016 [US2] Integrate status reporter into agent entrypoint in `backend/styrmin_backend/entrypoint/combined.py`: import `run_status_reporter`, add it as a third task in `asyncio.gather()` alongside `kopf.operator()` and `run_prefect_worker()`. Pass the GraphQL URL and poll interval.
- [x] T017 [US2] Regenerate GraphQL schema: run `uv run styrmin export graphql-schema schema.graphql` and `uv run invoke generate` to update SDK types from the new mutation.
- [x] T018 [US2] Run `uv run invoke format lint` to verify all new code passes formatting and linting.

**Checkpoint**: Agent reports pod statuses to backend. Database contains pod status snapshots. Mutation is functional.

---

## Phase 4: User Story 1 — View Current Pod Health for a Deployment (Priority: P1)

**Goal**: Operators can query pod health for any deployment via the GraphQL API.

**Independent Test**: Query `podStatuses(deploymentId: ...)` after a poll cycle; verify returned data matches actual pod states.

### Tests for User Story 1

- [ ] T019 [P] [US1] Write integration test for `podStatuses` query and `Deployment.podStatuses` resolver in `backend/tests/integration/test_pod_status_api.py` (extend file from T009). Test: query returns pod statuses for a deployment, query returns empty list for deployment with no pods, `Deployment.podStatuses` resolver returns nested pod data.

### Implementation for User Story 1

- [x] T020 [US1] Add `get_pod_statuses(deployment_id, uow) -> list[PodStatus]` service function to `backend/styrmin_backend/services/pod_status.py` — fetches pod statuses via `uow.pod_statuses.find_by_deployment()`.
- [x] T021 [US1] Add `podStatuses(deploymentId: UUID)` query field to `backend/styrmin_backend/api/schema/query.py`. Resolve via `get_pod_statuses` service, return `list[PodStatusType]` using `from_instance()`.
- [x] T022 [US1] Add `pod_statuses` resolver field to Deployment Strawberry type in `backend/styrmin_backend/api/definitions/deployment/model.py`. Use `@strawberry.field` async resolver that calls `get_pod_statuses` service.
- [x] T023 [US1] Create `.graphql` query file at `python_sdk/src/styrmin_sdk/graphql/get_deployment_pod_statuses.graphql` with the `GetDeploymentPodStatuses` query per contracts/graphql-schema.md.
- [x] T024 [US1] Regenerate GraphQL schema and SDK types: `uv run styrmin export graphql-schema schema.graphql && uv run invoke generate`
- [x] T025 [US1] Run `uv run invoke format lint` to verify all new code passes.

**Checkpoint**: Operators can query pod health for any deployment. US1 acceptance scenarios are testable.

---

## Phase 5: User Story 3 — Filter Workload Status by Scope (Priority: P2)

**Goal**: Filter pod statuses by cluster, environment, or deployment.

**Independent Test**: Deploy apps across environments, query with different filter params, verify correct scoping.

### Tests for User Story 3

- [ ] T026 [P] [US3] Write integration tests for filtered `podStatuses` query in `backend/tests/integration/test_pod_status_api.py` (extend). Test: filter by environment_id returns only pods in that environment, filter by cluster_id returns only pods in that cluster, no filter raises validation error or returns empty.

### Implementation for User Story 3

- [x] T027 [US3] Extend `get_pod_statuses` in `backend/styrmin_backend/services/pod_status.py` to accept optional `environment_id` and `cluster_id` parameters. When environment_id is provided, join through Deployment -> Environment. When cluster_id is provided, join through Deployment -> Environment -> Cluster.
- [x] T028 [US3] Add `find_by_environment(environment_id)` and `find_by_cluster(cluster_id)` methods to `PodStatusRepository` and `SQLModelPodStatusRepository` in `backend/styrmin_backend/repository/pod_status.py`. Use joins to filter through the Deployment -> Environment -> Cluster chain.
- [x] T029 [US3] Update `podStatuses` query in `backend/styrmin_backend/api/schema/query.py` to accept optional `environmentId: UUID` and `clusterId: UUID` parameters. Route to the appropriate service method based on which filters are provided.
- [x] T030 [US3] Create `.graphql` query file at `python_sdk/src/styrmin_sdk/graphql/get_pod_statuses.graphql` with the `GetEnvironmentPodStatuses` query per contracts/graphql-schema.md.
- [x] T031 [US3] Regenerate GraphQL schema and SDK types: `uv run styrmin export graphql-schema schema.graphql && uv run invoke generate`
- [x] T032 [US3] Run `uv run invoke format lint` to verify all new code passes.

**Checkpoint**: Filtering by cluster, environment, and deployment all work. US3 acceptance scenarios are testable.

---

## Phase 6: User Story 4 — Configurable Polling Interval (Priority: P3)

**Goal**: Polling interval is configurable via environment variable with a sensible default.

**Independent Test**: Set `STYRMIN_AGENT_STATUS_POLL_INTERVAL` to different values, verify agent adjusts frequency.

### Implementation for User Story 4

- [x] T033 [US4] Verify `STYRMIN_AGENT_STATUS_POLL_INTERVAL` config (already added in T015) is correctly wired through `run_status_reporter()` in `backend/styrmin_backend/agent/status/reporter.py` and `combined.py`. Add a startup log message that prints the configured interval. Verify default of 60 seconds works when env var is not set.

**Checkpoint**: Polling interval is configurable. US4 acceptance scenarios are testable.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, cleanup, and schema regeneration.

- [ ] T034 Run full test suite with `uv run invoke test` to verify no regressions
- [x] T035 Run `uv run invoke format lint` on all modified files
- [x] T036 Validate all `.graphql` query files with `uv run invoke validate-graphql`
- [x] T037 Verify `schema.graphql` is up to date with `uv run styrmin export graphql-schema schema.graphql`
- [x] T038 Verify generated SDK types are up to date with `uv run invoke generate`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS all user stories
- **Phase 3 (US2)**: Depends on Phase 2 — produces data for US1
- **Phase 4 (US1)**: Depends on Phase 2 — can run in parallel with US2 (different files) but logically benefits from US2 data
- **Phase 5 (US3)**: Depends on Phase 4 (extends the query) — cannot run in parallel with US1
- **Phase 6 (US4)**: Depends on Phase 3 (config is part of reporter) — minimal work, already mostly done in T015
- **Phase 7 (Polish)**: Depends on all user stories being complete

### User Story Dependencies

- **US2 (P1 - Agent Reports)**: Depends only on Foundational. No dependencies on other stories.
- **US1 (P1 - View Pod Health)**: Depends only on Foundational. Can run in parallel with US2 (different files: query.py vs mutation.py, read service vs write service).
- **US3 (P2 - Filter by Scope)**: Depends on US1 (extends the query resolver and service).
- **US4 (P3 - Configurable Interval)**: Depends on US2 (config is part of the reporter module). Mostly complete after T015.

### Within Each User Story

- Tests written first (fail before implementation)
- Models/repository before services
- Services before API layer (mutations/queries)
- API layer before agent integration
- Schema regeneration after API changes

### Parallel Opportunities

- T002 model + T006/T007 Strawberry types can be written in parallel (different files)
- T008 + T009 tests can run in parallel
- T019 tests can run in parallel with US2 implementation
- US1 and US2 implementation can proceed in parallel after foundational phase (different files: query.py vs mutation.py, read service vs write service, SDK query files)

---

## Parallel Example: Foundational Phase

```text
# These can run in parallel (different files):
T002: Add PodStatus model to db/models.py
T006: Create Strawberry types in api/definitions/pod_status/model.py

# Then sequentially:
T003: Generate Alembic migration (depends on T002)
T004: Create repository (depends on T002)
T005: Register in UnitOfWork (depends on T004)
```

## Parallel Example: US1 + US2

```text
# After Foundational, these two stories can proceed in parallel:

# US2 track (write path):
T010: Service upsert function in services/pod_status.py
T011: Mutation in api/schema/mutation.py
T013: K8s list_pods primitive
T014: Status reporter module

# US1 track (read path):
T020: Service get function in services/pod_status.py (different function, same file — coordinate)
T021: Query in api/schema/query.py
T022: Deployment resolver in api/definitions/deployment/model.py
```

---

## Implementation Strategy

### MVP First (US2 + US1)

1. Complete Phase 1: Setup (review patterns)
2. Complete Phase 2: Foundational (model, migration, repository, types)
3. Complete Phase 3: US2 — Agent reports statuses to backend
4. Complete Phase 4: US1 — Query pod statuses via API
5. **STOP and VALIDATE**: End-to-end flow works (agent polls -> backend stores -> API returns)
6. Deploy/demo if ready

### Incremental Delivery

1. Foundational -> Data layer ready
2. US2 -> Agent reporting works -> Backend has data
3. US1 -> API queries work -> MVP complete
4. US3 -> Filtering by scope -> Power users happy
5. US4 -> Config validation -> Ops-friendly (mostly already done)

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story
- Constitution requires tests (Principle V) — included for all stories
- Schema regeneration (T017, T024, T031) must happen after API changes
- Format/lint (T018, T025, T032) should run after each story's implementation
- The `services/pod_status.py` file is shared between US1 (read) and US2 (write) — if implementing in parallel, coordinate on this file
