---
description: "Tasks for GraphQL ↔ Database Propagation Test Coverage"
---

# Tasks: GraphQL ↔ Database Propagation Test Coverage

**Input**: Design documents in `/specs/007-graphql-propagation-tests/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, coverage-matrix.md, contracts/propagation-test-contract.md, quickstart.md

**Tests**: This entire feature *is* tests. There are no production code tasks. Each "implementation" task adds a test module that must pass.

**Organization**: Tasks are grouped by user story (audit → write tests → read tests → recipe). User Stories 2 and 3 are further split per domain so they can be merged independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks).
- **[Story]**: US1 (audit), US2 (write propagation), US3 (read propagation), US4 (recipe).
- File paths are repository-relative and absolute under the worktree.

## Path Conventions

This is a backend-only feature. New files live under `backend/tests/functional/propagation/` with shared GraphQL strings appended to `backend/tests/functional/helpers.py`. No production code is touched.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Land the directory layout, conftest, and a single end-to-end smoke propagation test before broader work begins.

- [ ] T001 Create `backend/tests/functional/propagation/` directory and add empty `backend/tests/functional/propagation/__init__.py`.
- [ ] T002 Add `backend/tests/functional/propagation/conftest.py` with: (a) re-export of `session` and `client` fixtures from `backend/tests/functional/test_api.py` (or via pytest fixture scoping — verify which is needed by running a placeholder test), (b) new `prefect_manager_mock` fixture mirroring `backend/tests/unit/services/conftest.py:45–53` (override `get_manager.__wrapped__` with `Mock(spec=PrefectManager)`).
- [ ] T003 Append a `# --- Propagation tests ---` section to `backend/tests/functional/helpers.py` reserved for new GraphQL operation strings added by US2/US3 tasks.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Prove the conftest and propagation pattern actually work end-to-end before parallelizing the per-domain test files.

- [ ] T004 Add a smoke propagation test at `backend/tests/functional/propagation/test_smoke.py` covering `Mutation.createCluster` end-to-end: drive `client.post("/graphql", ...)`, then read the row back via `await session.get(Cluster, id)` and assert all scalar fields. This task is the canonical reference shape for every later test in US2/US3 and proves T001–T003 wired correctly.
- [ ] T005 Run `uv run pytest backend/tests/functional/propagation/test_smoke.py -v` and confirm green. If red, fix the conftest/fixtures before any US2/US3 task starts.
- [ ] T006 Run `uv run invoke format lint` and confirm clean.

**Checkpoint**: Conftest works, smoke test passes. US2 and US3 tasks may now proceed in parallel.

---

## Phase 3: User Story 1 — Audit current propagation coverage (Priority: P1) ✅ ALREADY COMPLETE

**Goal**: Produce the coverage matrix.

**Independent Test**: A reviewer reading `coverage-matrix.md` can spot-check 5 rows against `backend/styrmin_backend/api/schema/{query,mutation}.py` and the existing test files, and confirm each row's verdict.

**Status**: This phase was completed during `/speckit-plan`. The matrix at `specs/007-graphql-propagation-tests/coverage-matrix.md` is the artifact. Tasks below are verification only.

- [ ] T007 [US1] Verify `coverage-matrix.md` enumerates every query, mutation, output scalar, input field, and resolver argument under `backend/styrmin_backend/api/schema/`. Cross-check against the schema source. Spot-fix any missed rows.
- [ ] T008 [US1] Verify each `partial`/`gap` row has a `Planned test` column entry that maps to a US2 or US3 task below.

---

## Phase 4: User Story 2 — Write-path propagation tests (Priority: P1)

**Goal**: Every mutation and write argument under `mutation.py` has a propagation test that asserts DB-side state read-back.

**Independent Test**: For any task below, the new test passes via `uv run pytest <test_path> -v` and fails when the resolver→service wiring is removed (per quickstart.md step 8).

Tasks within this phase target distinct files. They can run in parallel once Phase 2 completes. Each task must satisfy `contracts/propagation-test-contract.md` C1–C10 and update the matching matrix rows.

### Cluster

- [ ] T009 [P] [US2] In `backend/tests/functional/propagation/test_cluster_propagation.py`, add `test_create_cluster_persists_name_and_config` and `test_delete_cluster_removes_row`. Append `create_cluster_query` extension and any missing strings to `backend/tests/functional/helpers.py` (reuse existing strings where possible).

### Environment

- [ ] T010 [P] [US2] In `backend/tests/functional/propagation/test_environment_propagation.py`, add `test_create_environment_persists_fields` (covers `clusterId` and `clusterName` lookup paths) and `test_delete_environment_removes_row` (covers all four lookup arg combinations: `environmentId`, `environmentName + clusterId`, `environmentName + clusterName`).

### Backup Storage Location

- [ ] T011 [P] [US2] In `backend/tests/functional/propagation/test_backup_storage_location_propagation.py`, add `test_create_bsl_persists_all_credentials` (asserts every input scalar lands on the BSL row).
- [ ] T012 [P] [US2] In the same file, add `test_update_bsl_persists_changes` covering each Optional argument independently (one parametrized test or one test per field) and `test_update_bsl_credentials_dispatches_sync` asserting `prefect_manager_mock.run_action` called with the new credentials when `accessKeyId`/`secretAccessKey` change.
- [ ] T013 [P] [US2] In the same file, add `test_delete_bsl_removes_row`.
- [ ] T014 [P] [US2] In the same file, add `test_assign_bsl_persists_link` (assert `Environment.backup_storage_location_id` updated after mutation; mock prefect dispatch) and `test_unassign_bsl_clears_link`.

### Application Driver

- [ ] T015 [P] [US2] In `backend/tests/functional/propagation/test_application_driver_propagation.py`, add `test_load_local_driver_persists_rows`. Patch `styrmin_backend.api.schema.mutation.load_application_driver_from_local_directory` (the import site) with an `AsyncMock` returning a fully-populated `ApplicationDriverVersion` model; assert the resulting `ApplicationDriver` and `ApplicationDriverVersion` rows in the DB.
- [ ] T016 [P] [US2] In the same file, add `test_load_remote_driver_persists_rows` patching `load_application_driver_from_git_repository` similarly; assert rows.

### Deployment

- [ ] T017 [P] [US2] In `backend/tests/functional/propagation/test_deployment_propagation.py`, add `test_deploy_persists_deployment_and_task`. Mock `prefect_manager` via the `prefect_manager_mock` fixture; seed an environment + driver version; drive `deploy(...)` with `config`, `parameters`, and a `serviceNameOverrides` list; assert `Deployment`, `ApplicationInstance`, `Task` rows landed in the DB and the override mapping is on the persisted service rows.
- [ ] T018 [P] [US2] In the same file, add `test_update_deployment_persists_changes` (mock prefect; assert `Deployment.config`, `Deployment.name`, `Deployment.parameters` updated).
- [ ] T019 [P] [US2] In the same file, add `test_update_deployment_version_persists_version` (mock prefect; assert version row write).
- [ ] T020 [P] [US2] In the same file, add `test_update_internal_deployment_raises` and `test_update_version_internal_deployment_raises` (negative-path: assert GraphQL error with the right `extensions.code`, no DB mutation).

### Components / Run Job

- [ ] T021 [P] [US2] In `backend/tests/functional/propagation/test_components_propagation.py`, add `test_stop_components_creates_task_with_components` and `test_start_components_creates_task_with_components`. Mock prefect; assert the persisted `Task` row carries the requested components list (via the action payload or task metadata, whichever is the established source of truth — verify by reading `backend/styrmin_backend/services/primitives.py` while writing the test).
- [ ] T022 [P] [US2] In `backend/tests/functional/propagation/test_run_job_propagation.py`, add `test_run_job_persists_job_task`. Mock prefect; assert the persisted `Task` (or related action) row carries `image`, `commands`, and `env`.

### Backup / Restore

- [ ] T023 [P] [US2] In `backend/tests/functional/propagation/test_backup_propagation.py`, add `test_create_backup_persists_row` (mock prefect dispatch; assert `Backup` row carries `instance_id`, optional `name`, status `PENDING`, `target_namespace`).
- [ ] T024 [P] [US2] In the same file, add `test_delete_backup_removes_row`.
- [ ] T025 [P] [US2] In `backend/tests/functional/propagation/test_restore_propagation.py`, add `test_create_restore_persists_row` (mock prefect; assert `Restore` row carries `backup_id`, `target_namespace`, `target_instance_id`).

### Backup Schedule

- [ ] T026 [P] [US2] In `backend/tests/functional/propagation/test_backup_schedule_propagation.py`, add `test_create_schedule_persists_all_fields`, `test_update_schedule_persists_changes` (one assertion per Optional field — split per-field if a single test grows past ~40 lines), and `test_delete_schedule_removes_row`.

### Pod Status / Deployment Status

- [ ] T027 [P] [US2] In `backend/tests/functional/propagation/test_pod_status_propagation.py`, add `test_report_pod_statuses_upserts_and_removes_stale`. Seed a stale pod row, drive the mutation with one new pod report, assert: new pod row has every input scalar populated; stale pod removed; response counts match.
- [ ] T028 [P] [US2] In `backend/tests/functional/propagation/test_deployment_status_propagation.py`, add `test_report_deployment_statuses_upserts_snapshot`. Drive the mutation with a `DeploymentStatusReportInput` carrying `conditions` and `managedResourceCounts`; assert the status snapshot row's every scalar matches and that `Deployment.state` was synced.

### Callback

- [ ] T029 [P] [US2] In `backend/tests/functional/propagation/test_callback_propagation.py`, add `test_callback_persists_task_state`. Seed a `Task`; drive `callback(taskId, stateName, stateMessage, stateType)`; assert `Task.state_name`/`state_message` updated in DB.

---

## Phase 5: User Story 3 — Read-path propagation tests (Priority: P2)

**Goal**: Every query and output field has a propagation test that seeds via the real repository and asserts the resolver projects every scalar correctly.

**Independent Test**: For any task, the new test passes and dropping a scalar from the GraphQL output type or its `from_instance(...)` mapping causes the assertion to fail.

Tasks target distinct files; can run in parallel after Phase 2 completes. Each task must satisfy contract C1–C10 and update the matching matrix rows.

### Cluster

- [ ] T030 [P] [US3] In `backend/tests/functional/propagation/test_cluster_propagation.py`, add `test_clusters_projects_seeded_rows`, `test_cluster_by_id_projects_all_fields` (every scalar of `Cluster`), and `test_cluster_by_name_returns_seeded_row` (covers the `clusterName` lookup path).

### Environment

- [ ] T031 [P] [US3] In `backend/tests/functional/propagation/test_environment_propagation.py`, add `test_environments_projects_seeded_rows`, `test_environment_by_each_lookup_arg` (parametrized over `environmentId`, `environmentName`, `environmentName + clusterId`, `environmentName + clusterName`), and `test_environment_projects_cluster_relation`.

### Backup Storage Location (read)

- [ ] T032 [P] [US3] In `backend/tests/functional/propagation/test_backup_storage_location_propagation.py`, add `test_list_bsls_projects_seeded` and `test_get_bsl_projects_all_fields`. Seed two environments referencing the BSL to cover the computed `environmentCount` field.

### Backup / Restore (read)

- [ ] T033 [P] [US3] In `backend/tests/functional/propagation/test_backup_propagation.py`, add `test_backup_projects_all_scalars` (every scalar of `Backup`), `test_backups_filters_by_status_and_instance` (seed two rows with different status, assert filter restricts), and `test_backup_projects_component_statuses` (seed component status rows linked to the backup).
- [ ] T034 [P] [US3] In `backend/tests/functional/propagation/test_restore_propagation.py`, add `test_restore_projects_all_scalars` and `test_restores_filters_by_status_and_backup`.

### Backup Schedule (read)

- [ ] T035 [P] [US3] In `backend/tests/functional/propagation/test_backup_schedule_propagation.py`, add `test_schedule_projects_all_scalars` and `test_schedules_filters_by_deployment` (seed schedules under two deployments, assert only matching set returned).

### Application Driver (read)

- [ ] T036 [P] [US3] In `backend/tests/functional/propagation/test_application_driver_propagation.py`, add `test_application_drivers_projects_seeded` and `test_application_driver_projects_all_scalars` covering `components`, `sourceType`, `sourceRepository`, `sourceBranch`, `sourcePath`, `defaultVersion`, `supportedVersions` on `ApplicationDriverVersion`.
- [ ] T037 [P] [US3] In the same file, add `test_driver_version_projects_nested_collections` covering the nested `services`, `parameters`, `componentConfigs`, `helmChart`, `actions` projections.

### Task

- [ ] T038 [P] [US3] In `backend/tests/functional/propagation/test_task_propagation.py`, add `test_task_projects_all_scalars` and `test_tasks_projects_seeded`.

### Pod Status (read)

- [ ] T039 [P] [US3] In `backend/tests/functional/propagation/test_pod_status_propagation.py`, add `test_pod_statuses_filters_by_each_arg` (parametrized over `deploymentId`, `environmentId`, `clusterId`; for each filter, seed two rows and assert only the matching one returns) and `test_pod_status_projects_all_scalars`.

### Deployment (read negatives)

- [ ] T040 [P] [US3] In `backend/tests/functional/propagation/test_deployment_propagation.py`, add `test_internal_deployment_returns_null` (seed an `internal=True` deployment, assert `Query.deployment` returns `null`).

### Deployment Timeline

- [ ] T041 [P] [US3] In `backend/tests/functional/propagation/test_deployment_timeline_propagation.py`, add `test_timeline_projects_tasks_with_versions`. Seed multiple tasks for a deployment with version metadata; assert ordering (newest-first) and the projected scalar fields of `DeploymentTimelineEntry`.

### Deployed Service (read)

- [ ] T042 [P] [US3] In `backend/tests/functional/propagation/test_service_propagation.py`, add `test_environment_services_projects_seeded`, `test_deployment_services_projects_seeded`, and `test_deployed_service_fqdns_via_query` (HTTP-driven equivalent of the existing `test_deployed_service_fqdn.py` unit, asserting the FQDN/URL fields are projected through the GraphQL transport).

---

## Phase 6: Polish & Cross-Cutting

**Purpose**: Verify, document, and close out the matrix.

- [ ] T043 Run `uv run invoke test` and confirm the full backend suite is green on the feature branch.
- [ ] T044 Run `uv run invoke format lint` and confirm clean.
- [ ] T045 [P] Spot-check 3 of the new tests (one US2, one US3, one negative-path) by temporarily removing the resolver→service wiring of the corresponding field; confirm the propagation test fails. Restore code. Document the 3 chosen tests in the PR description.
- [ ] T046 [P] Update `coverage-matrix.md`: for every row whose verdict was `gap` or `partial`, change to `covered` and update `Existing coverage` to point at the new test (`backend/tests/functional/propagation/<module>::<test>`).
- [ ] T047 If `dev/guides/graphql-propagation-tests.md` examples diverged from the new test pattern, update it to point at one of the new tests as the canonical example. Otherwise leave it alone.
- [ ] T048 Final pass: confirm no production code under `backend/styrmin_backend/` was modified by this feature (`git diff --stat develop... -- backend/styrmin_backend/` should be empty).

---

## Dependencies

- **Phase 1 (T001–T003)** must complete before Phase 2.
- **Phase 2 (T004–T006)** must complete before any task in Phase 4 or Phase 5 starts. The smoke test is the gate.
- **Phase 4 (T009–T029)** and **Phase 5 (T030–T042)** can run in parallel with each other after Phase 2.
- Within Phase 4 and Phase 5, all `[P]` tasks target different files and have no inter-task dependencies.
- **Phase 6 (T043–T048)** runs last and depends on all tests being committed.
- **Phase 3 (T007–T008)** is verification of the matrix already produced by `/speckit-plan`; can run any time after the matrix exists.

## Parallel Execution Examples

After T006 passes, fan out US2 across files:

```text
T009  test_cluster_propagation.py             (write)
T010  test_environment_propagation.py         (write)
T011, T012, T013, T014  test_backup_storage_location_propagation.py  (sequential within file; parallel across other files)
T015, T016  test_application_driver_propagation.py
T017, T018, T019, T020  test_deployment_propagation.py
T021, T022  test_components_propagation.py / test_run_job_propagation.py
T023, T024, T025  test_backup_propagation.py / test_restore_propagation.py
T026  test_backup_schedule_propagation.py
T027, T028  test_pod_status_propagation.py / test_deployment_status_propagation.py
T029  test_callback_propagation.py
```

US3 fans out the same way, sharing some files with US2 — within a single file, ordered tasks must be sequential; across files, all `[P]` tasks are independent.

## Implementation Strategy

1. **MVP**: Phase 1 + Phase 2 + the Cluster slice (T009 + T030). This proves the whole pipeline (conftest, helpers, write+read pattern) and is the smallest viable demo of Constitution §V coverage.
2. **Increment 1**: Add Environment, BSL, Backup Schedule (low Prefect surface).
3. **Increment 2**: Add Backup, Restore, Pod Status, Deployment Status (Prefect-mocked write paths).
4. **Increment 3**: Add Deployment, Components, Run Job, Application Driver loaders (heaviest mocking).
5. **Increment 4**: Add Deployment Timeline, Service, Task, Callback (read-mostly).
6. **Polish**: Phase 6.

Each increment should commit + run `uv run invoke test` to keep the suite green.

## Format validation

All tasks use `- [ ] T### [P?] [Story?] Description with file path`. Setup (T001–T003), Foundational (T004–T006), and Polish (T043–T048) tasks have no `[Story]` label per the template rule. US1 is verification (T007–T008) and is fully covered by the matrix produced in `/speckit-plan`.
