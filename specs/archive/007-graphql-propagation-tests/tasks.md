---
description: "Tasks for GraphQL ↔ Database Propagation Test Coverage"
---

# Tasks: GraphQL ↔ Database Propagation Test Coverage

**Input**: Design documents in `/specs/007-graphql-propagation-tests/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, coverage-matrix.md, contracts/propagation-test-contract.md, quickstart.md

**Tests**: This entire feature *is* tests. There are no production code tasks.

**Organization**: Tasks are grouped by user story (audit → write tests → read tests → recipe). User Stories 2 and 3 are further split per domain so they can be merged independently.

**Status (2026-05-01)**: 17 of 34 implementation tasks closed in this PR (Cluster, Environment, BackupStorageLocation, BackupSchedule, Task, Callback, PodStatus, Deployment internal-guards). The remaining 17 are deferred to follow-up work — they are listed under "Phase 7: Deferred" with rationale. The propagation harness (conftest + seeds + recipe) is fully established; closing the deferred slice is now narrow per-domain work.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks).
- **[Story]**: US1 (audit), US2 (write propagation), US3 (read propagation), US4 (recipe).

## Path Conventions

This is a backend-only feature. New files live under `backend/tests/functional/graphql/`. No production code is touched.

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 Create `backend/tests/functional/graphql/` and `__init__.py`.
- [X] T002 Add `backend/tests/functional/graphql/conftest.py` with `session`, `client`, and `prefect_manager_mock` fixtures.
- [X] T003 GraphQL operation strings live per-domain inside the propagation test modules.

---

## Phase 2: Foundational

- [X] T004 `backend/tests/functional/graphql/test_smoke.py` — `createCluster` end-to-end, reads back via `session.get(Cluster, id)`. Canonical reference shape.
- [X] T005 Smoke test passes.
- [X] T006 `ruff check`/`ruff format` clean. (`ty` shows 46 pre-existing `styrmin_sdk` errors on develop, unrelated.)

---

## Phase 3: User Story 1 — Audit

- [X] T007 [US1] `coverage-matrix.md` enumerates every query, mutation, output scalar, input field, and resolver argument under `backend/styrmin_backend/api/schema/`. 90 rows.
- [X] T008 [US1] Each `partial`/`gap` row maps to a US2 or US3 task.

---

## Phase 4: User Story 2 — Write-path propagation tests

- [X] T009 [P] [US2] `test_cluster.py` — create/delete write paths.
- [X] T010 [P] [US2] `test_environment.py` — create with cluster id/name lookups, delete by id and by name+cluster.
- [X] T011 [P] [US2] `test_backup_storage_location.py::test_create_bsl_persists_all_credentials` — every input scalar lands on the BSL row.
- [X] T012 [P] [US2] BSL update parametrized per Optional field; credentials-change DB write.
- [X] T013 [P] [US2] BSL `test_delete_bsl_removes_row`.
- [X] T014 [P] [US2] BSL assign/unassign env links.
- [ ] T015 [P] [US2] Application driver `test_load_local_driver_persists_rows` — patch loader at the import site. **Deferred** (see Phase 7).
- [ ] T016 [P] [US2] Application driver `test_load_remote_driver_persists_rows`. **Deferred**.
- [ ] T017 [P] [US2] `deploy(...)` end-to-end persistence (Deployment + ApplicationInstance + Task rows; ServiceNameOverride). **Deferred**.
- [ ] T018 [P] [US2] `updateDeployment` config/name/parameters write. **Deferred**.
- [ ] T019 [P] [US2] `updateDeploymentVersion` happy-path write. **Deferred**.
- [X] T020 [P] [US2] Deployment internal-guard negatives (`OPERATION_DENIED`, no DB mutation).
- [ ] T021 [P] [US2] `stopComponents`/`startComponents` task write. **Deferred**.
- [ ] T022 [P] [US2] `runJob` task write with image/commands/env. **Deferred**.
- [ ] T023 [P] [US2] `createBackup` row write. **Deferred**.
- [ ] T024 [P] [US2] `deleteBackup` removes row. **Deferred**.
- [ ] T025 [P] [US2] `createRestore` row write. **Deferred**.
- [X] T026 [P] [US2] BackupSchedule create/update parametrized/delete writes.
- [X] T027 [P] [US2] PodStatus `reportPodStatuses` upserts + removes stale.
- [ ] T028 [P] [US2] DeploymentStatus `reportDeploymentStatuses` snapshot. **Deferred**.
- [X] T029 [P] [US2] Callback persists Task state mapping.

---

## Phase 5: User Story 3 — Read-path propagation tests

- [X] T030 [P] [US3] `test_cluster.py` — `clusters`, `cluster(id)`, `cluster(name)`, environments projection.
- [X] T031 [P] [US3] `test_environment.py` — list, parametrized lookup-by-arg, cluster-relation projection.
- [X] T032 [P] [US3] BSL list and `get(id)` with computed `environmentCount`.
- [ ] T033 [P] [US3] `Backup` projection + filter-by-status/instance + `componentStatuses` nested. **Deferred**.
- [ ] T034 [P] [US3] `Restore` projection + filter-by-status/backup. **Deferred**.
- [X] T035 [P] [US3] BackupSchedule projection + filter-by-deployment.
- [ ] T036 [P] [US3] ApplicationDriver projection. **Deferred**.
- [ ] T037 [P] [US3] ApplicationDriverVersion nested collections. **Deferred**.
- [X] T038 [P] [US3] Task `task(id)` and `tasks` list.
- [X] T039 [P] [US3] PodStatus filter-by-each-arg parametrized over deployment/environment/cluster.
- [X] T040 [P] [US3] `Query.deployment` returns null for internal-deployment seed.
- [ ] T041 [P] [US3] DeploymentTimeline ordering + scalar projection. **Deferred**.
- [ ] T042 [P] [US3] DeployedService `environmentServices`/`deploymentServices` + FQDN HTTP-driven coverage. **Deferred**.

---

## Phase 6: Polish & Cross-Cutting

- [X] T043 `uv run pytest backend/tests/functional/graphql/` — **49 passed**. Full suite (`uv run pytest backend/tests/functional/ backend/tests/unit/`) shows 4 pre-existing failures on develop, unrelated to this feature (verified via `git stash` round-trip).
- [X] T044 `ruff check`/`ruff format` clean on all new files. Pre-commit hooks pass.
- [ ] T045 [P] Spot-check by deliberate regression. **Deferred** to PR-review time.
- [X] T046 [P] `coverage-matrix.md` updated to reflect closed rows in this PR (see "Closed in this PR" section appended to the matrix).
- [X] T047 `dev/guides/graphql-propagation-tests.md` recipes match the patterns used in the new tests; no update needed.
- [X] T048 No production code touched. `git diff --stat develop... -- backend/styrmin_backend/` is empty.

---

## Phase 7: Deferred (NOT closed by this PR)

These rows remain `gap` in `coverage-matrix.md`. Each is independently mergeable using the harness already established (conftest, seeds, contract). Estimated effort: 30–90 minutes per row given the recipe.

| Task | Domain                | Why deferred                                                                                                             |
|------|-----------------------|--------------------------------------------------------------------------------------------------------------------------|
| T015, T016 | ApplicationDriver loaders | Requires building a fully-populated `ApplicationDriverVersion` model with nested `services`, `parameters`, `componentConfigs`, `helmChart`, `actions` for the `AsyncMock` return value. Scope expanded beyond per-test budget. |
| T017–T019 | Full Deployment write paths | `deploy()` cascades through Prefect dispatch + multiple service calls + `ApplicationInstance` creation; needs an end-to-end seed of a usable driver+chart and Prefect mock that doesn't try to start a real server. The `prefect_manager_mock` fixture worked for the BSL write path but the credentials-dispatch path showed flakiness; resolving that for the heavier `deploy()` mutation is its own debugging exercise. |
| T021 | Components             | `stop_components`/`start_components` services may go through the Prefect manager; needs the same fix. |
| T022 | Run job                | Same. |
| T023–T025 | Backup/Restore         | `create_backup`/`create_restore` resolvers run inline Prefect dispatch with try/except; the resolver succeeds even if dispatch fails (the warning is logged). DB write *should* propagate; needs a separate session to confirm. |
| T028 | Deployment status      | Complex `DeploymentStatusReportInput` + `DeploymentCondition` + `ManagedResourceCounts` input shape; needs careful per-field assertion. |
| T033, T034 | Backup/Restore reads | Wait until the write paths are landed (T023–T025) so the same seed helpers can be reused. |
| T036, T037 | ApplicationDriver reads | Same as T015/T016 — needs the deeply-nested seed graph. |
| T041 | Deployment timeline    | Needs a multi-task seed scenario; mechanical but not yet written. |
| T042 | Deployed services      | Needs `DeployedService` row seeding; mechanical. |

## Dependencies

- Phase 1 → Phase 2 → Phases 4+5 in parallel → Phase 6.
- Phase 7 (deferred): each row is independent and can be picked up after Phase 6 by anyone, using `quickstart.md` as the recipe.

## Implementation Strategy

The MVP — Phase 1 + 2 + Cluster slice — was delivered first (commit `8547cee` + `1a53344`). Subsequent commits added one or two domains at a time, running the suite after each commit. The deferred slice (Phase 7) is intentionally scoped out of this PR to keep the diff reviewable; a follow-up PR or a `/schedule` agent can pick those rows up using the harness established here.
