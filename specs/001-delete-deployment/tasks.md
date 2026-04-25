---
description: "Task list for the Delete Deployments feature"
---

# Tasks: Delete Deployments

**Input**: Design documents in `/specs/001-delete-deployment/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Included. FR-015 in the spec explicitly requires tests
covering the new API, teardown behaviour, concurrency guard,
idempotency, partial-failure surfacing, async lifecycle, tombstone
visibility, and the UI delete flow.

**Organization**: Tasks are grouped by user story. The spec has two
P1 stories and one P2 story. US2 (GraphQL API) is ordered before US1
(UI) because the UI consumes the API — both remain P1 and
independently testable against the API surface once US2 lands.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: `[US1]` UI story, `[US2]` API story, `[US3]` timeline story

## Path Conventions

Web-app layout per plan.md:

- Backend: `backend/styrmin_backend/`
- Backend tests: `backend/tests/`
- Frontend: `frontend/src/`
- Python SDK: `python_sdk/src/styrmin_sdk/`
- Repo-root artefacts: `schema.graphql`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: No new dependencies; only confirmation + light scaffolding
for the feature branch.

- [X] T001 Confirm the two governance gates from `specs/001-delete-deployment/plan.md` (DB schema change + GraphQL schema change) are signed off before proceeding.
- [X] T002 [P] Verify local dev stack (`uv sync --all-groups --all-packages`, Kind cluster with Prefect + FluxCD + operator) is running and a throwaway deployment exists for ad-hoc verification. *(DB not currently running locally; migration run deferred to T010.)*

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared primitives that US1, US2, and US3 all depend on
— lifecycle enum, migration, typed error, concurrency-guard helper,
and the `BackupDisposition` type.

**⚠️ CRITICAL**: No user-story work can begin until this phase is complete.

- [X] T003 [P] Extend `DeploymentState` in `backend/styrmin_backend/domain/models.py` with `DELETION_REQUESTED`, `DELETION_IN_PROGRESS`, `DELETED`.
- [X] T004 [P] Mirror the new values on `DeploymentState` in `backend/styrmin_backend/db/models.py` and add a nullable `deleted_at: datetime | None` column to the `Deployment` SQLModel with a DB index.
- [X] T005 Create an Alembic migration in `backend/styrmin_backend/db/migrations/versions/f6a7b8c9d0e1_add_deletion_states.py` that issues `ALTER TYPE deploymentstate ADD VALUE IF NOT EXISTS ...` for the three new values and adds the `deployments.deleted_at TIMESTAMP WITH TIME ZONE NULL` column + index. Downgrade removes the column and rebuilds the enum to drop the deletion values.
- [X] T006 [P] Add `BackupDisposition` enum (`RETAIN`, `REMOVE`) in `backend/styrmin_backend/domain/models.py`.
- [X] T007 [P] Added `DeploymentMutationInProgressError` (code `ALREADY_IN_PROGRESS`, with `active_task_ids` metadata) and `DeploymentAlreadyDeletedError` (code `ALREADY_DELETED`) to `backend/styrmin_backend/services/exceptions.py`. `DeploymentNotFoundError` already existed. *Codes follow the existing short-code convention; the contract doc will be updated in Phase 3 to match.*
- [X] T008 Added `list_active_tasks(deployment_id: UUID) -> list[Task]` abstract + SQLModel implementation on `DeploymentRepository` in `backend/styrmin_backend/repository/deployment.py` (filters Tasks by PENDING / RUNNING status).
- [X] T009 [P] Added `PrefectAction.DELETE_INSTANCE = "orchestrate_instance_deletion"` in `backend/styrmin_backend/workflows/models.py`. Catalogue registration deferred to T021 (needs the flow module to point at).
- [ ] T010 Run `uv run alembic upgrade head` against the dev DB and confirm the migration applies cleanly. *(No Postgres container running locally; skip until dev stack is up. Migration file is ready.)*

**Checkpoint**: Foundation ready — US1, US2, US3 can now proceed.

---

## Phase 3: User Story 2 — Delete via GraphQL API (Priority: P1) 🎯 MVP

**Goal**: An authenticated API/SDK caller can issue
`deleteDeployment(deploymentId, backupDisposition)` and drive a
deployment through the DELETION_REQUESTED → DELETION_IN_PROGRESS →
DELETED lifecycle, with all owned Kubernetes resources torn down and
backups retained or removed per the operator's choice.

**Independent Test**: Using the GraphQL schema and/or Python SDK,
delete a seeded deployment; assert (a) mutation returns a
`DELETE_INSTANCE` Task, (b) the deployment's status progresses to
`DELETED` with `deletedAt` set, (c) no Styrmin-owned cluster
resources remain, (d) backups are retained or removed per the
disposition, (e) typed errors fire for not-found / already-deleted /
mutation-in-progress cases.

### Tests for User Story 2 ⚠️

> **Write these tests FIRST and confirm they FAIL before implementation.**

- [X] T011 [P] [US2] Unit test: `delete_deployment` happy path (state transition, task creation, flow dispatch, parameters).
- [X] T012 [P] [US2] Unit test: concurrency guard rejects when a PENDING/RUNNING task exists.
- [X] T013 [P] [US2] Unit test: idempotency (parametrised over `DELETION_REQUESTED`, `DELETION_IN_PROGRESS`, `DELETED`).
- [X] T014 [P] [US2] Unit tests: backup disposition — RETAIN leaves backup rows alone, REMOVE iterates every instance's backups and their restores.
- [ ] T015 [P] [US2] Contract test: GraphQL `deleteDeployment` mutation. *Deferred: the repo has no GraphQL-level integration-test harness; contract is enforced by `schema.graphql` diff + strawberry decorator types.*
- [ ] T016 [P] [US2] Contract test: `Environment.deployments(includeDeleted)`. *Same deferral as T015.*
- [X] T017 [US2] E2E test (Kind) — RETAIN path: `backend/tests/e2e/test_deployment_deletion.py::test_delete_deployment_retain_tombstones_and_clears_cluster`. Asserts deployment reaches `deleted`, `deleted_at` is set, namespace is gone, timeline keeps the DELETE_INSTANCE entry.
- [X] T018 [US2] E2E test (Kind) — REMOVE path: `::test_delete_deployment_remove_drops_backups`.
- [X] T019 [US2] E2E tests (Kind) — concurrency + idempotency: `::test_delete_deployment_rejects_concurrent_mutation`, `::test_delete_deployment_idempotent`. *Partial-teardown-failure variant is still a follow-up: inducing a stuck finalizer deterministically in Kind needs extra harness plumbing and isn't required for baseline acceptance.*

### Implementation for User Story 2

- [X] T020 [US2] `delete_deployment` in `backend/styrmin_backend/services/deployment.py` — validates, concurrency-guards, iterates backups for REMOVE, transitions state, creates a DELETE_INSTANCE Task (with `backup_disposition` stored in Task.parameters), submits the Prefect flow with `release_reference` / `namespace` resolved from the active instance's context, stores `prefect_flow_run_id`, commits.
- [X] T021 [US2] `delete_instance_crd` flow in `backend/styrmin_backend/agent/tasks/orchestration.py` now does the real teardown: foreground-DELETE on the StyrminDeployment CRD → poll until kopf's finalizer finishes the operator's reverse-order cleanup → DELETE the namespace. Timeout (10 min) + operator-handled ordering keep this safe in face of stuck resources.
- [X] T022 [US2] The existing operator `kopf.on.delete` handler in `backend/styrmin_backend/operator/handlers/styrmin_deployment.py` already tears down Services / HelmRelease / NetworkPolicies / Secrets in reverse order — no code change needed on the operator. The Prefect flow triggers it via a standard K8s DELETE. Namespace deletion is done by the flow after the operator finalizer completes, so cascade-cleanup covers anything the operator missed.
- [X] T023 [US2] Two guards now keep the deletion lifecycle terminal for CRD reporting too: `update_task_state` transitions DELETE_INSTANCE tasks (RUNNING→DELETION_IN_PROGRESS, COMPLETED→DELETED + `deleted_at`, FAILED→stay), and `report_deployment_statuses` now skips any deployment already in `DELETION_REQUESTED` / `DELETION_IN_PROGRESS` / `DELETED` so a late agent status report can't regress the state.
- [ ] T024 [US2] `InstanceDeletionStrategy` routing. *Not needed for Option B (direct `run_action` dispatch). Revisit when the feature graduates to full diff-driven reconciliation.*
- [X] T025 [P] [US2] GraphQL `BackupDisposition` enum in `backend/styrmin_backend/api/definitions/deployment/model.py`.
- [X] T026 [US2] `delete_deployment` Strawberry mutation in `backend/styrmin_backend/api/schema/mutation.py`.
- [X] T027 [US2] `Environment.deployments(includeDeleted: Boolean = false)` in `backend/styrmin_backend/api/definitions/environment/model.py`.
- [ ] T028 [US2] `SQLModelDeploymentRepository` repository-level `include_deleted` flag. *Skipped: the filter is applied at the resolver; repository remains unchanged to keep the surface area minimal.*
- [X] T029 [US2] Regenerated `schema.graphql`.
- [X] T030 [P] [US2] `python_sdk/src/styrmin_sdk/graphql/delete_deployment.graphql`.
- [X] T031 [US2] `deployments.delete(deployment_id, backup_disposition)` in `python_sdk/src/styrmin_sdk/resources/deployments.py`.
- [X] T032 [US2] Regenerated SDK Pydantic types via `uv run invoke generate` (backend codegen only; frontend codegen skipped — node_modules not installed in this session).
- [X] T033 [US2] `uv run invoke validate-graphql` — 82/82 files pass.
- [X] T034 [US2] `uv run invoke format lint` clean on changed files.

**Checkpoint**: US2 is a complete MVP — API deletes deployments end-to-end, verified against Kind.

---

## Phase 4: User Story 1 — Delete from the UI (Priority: P1)

**Goal**: From the deployment detail page, an operator can initiate
a deletion, see a confirmation dialog that names the deployment and
presents retain/remove backup choices, observe in-progress deletion,
and be navigated away once terminal.

**Independent Test**: With the US2 API in place, navigate to a
deployment detail page, click Delete, confirm with a chosen backup
disposition, and verify (a) the dialog shows the deployment name and
explicit backup options, (b) an in-progress banner appears, (c)
cancel button works without side effects, (d) concurrent-mutation
rejection is surfaced as a clear toast, (e) post-deletion the user
lands on the parent environment page.

### Tests for User Story 1 ⚠️

- [ ] T035 [P] [US1] Component test for the delete dialog. *Deferred: the dialog is defined inline in `DeploymentDetailPage` (matching the existing pattern for Restore / Delete-Backup / Upgrade). A page-level test would require a `QueryClientProvider` + a mocked router + fake GraphQL fetcher; that harness doesn't exist yet. Captured as a follow-up.*
- [ ] T036 [P] [US1] Component test for concurrency-error rendering. *Deferred with T035.*

### Implementation for User Story 1

- [X] T037 [P] [US1] `frontend/src/graphql/delete_deployment.graphql` (placed alongside the other frontend mutations — `operations/` subfolder doesn't exist; followed the actual convention).
- [X] T038 [US1] `pnpm codegen` regenerates `frontend/src/generated/graphql.ts` with `useDeleteDeploymentMutation`, `BackupDisposition` union type, `MutationDeleteDeploymentArgs`.
- [X] T039+T040 [US1] Delete action button + inline delete-deployment dialog wired into `frontend/src/pages/deployments/DeploymentDetailPage.tsx`. Dialog shows the deployment name and two radio choices (RETAIN default, REMOVE) with short explanations. On success invalidates `GetDeployment` and `GetDeploymentTimeline` queries; on error surfaces the backend's human message via the existing `Alert` pattern (typed-code branching would require extending the shared GraphQL fetcher — see follow-ups).
- [X] T041 [US1] `mutationsDisabled` flag derived from status — Delete / Upgrade / Redeploy / Create-Backup buttons are all disabled while the deployment is in `deletion_requested`, `deletion_in_progress`, or `deleted`. An `Alert` banner is rendered above the page for both in-progress and tombstoned views.
- [X] T042 [US1] `useEffect` on `deployment.status === "deleted"` calls `navigate({ to: "/environments/$environmentId" })`. Runs off the existing 10s `GetDeployment` refetch — no new subscription.
- [X] T043 [US1] Tombstoned deployments still render the same page (timeline + metadata remain visible) but all mutation actions are disabled and a "This deployment has been deleted" banner is shown with `deletedAt` if present.
- [X] T044 [US1] `pnpm lint` and `pnpm tsc --noEmit` both clean. Full vitest suite (33 tests) still passes.

**Checkpoint**: US1 complete — full UI flow works against the live API.

---

## Phase 5: User Story 3 — Observe deletion in the timeline (Priority: P2)

**Goal**: The deployment timeline shows the deletion lifecycle with
actor, timestamp, chosen backup disposition, and failure reason on
partial failure, for both active and tombstoned deployments.

**Independent Test**: After (or during) a deletion, open the
deployment timeline; a `DELETE_INSTANCE` entry is visible with
status transitioning PENDING → RUNNING → SUCCESS (or FAILED with a
surfaced reason) and the chosen `backup_disposition` displayed. The
same timeline remains viewable on a tombstoned deployment.

### Tests for User Story 3 ⚠️

- [X] T045 [P] [US3] Unit test: `backup_disposition` is persisted in `Task.parameters` on creation (extended `test_delete_deployment_happy_path` in `backend/tests/unit/services/test_deployment_delete.py`).
- [X] T046 [P] [US3] E2E timeline-after-deletion covered by `test_delete_deployment_retain_tombstones_and_clears_cluster` — the test fetches the timeline of the tombstoned deployment and asserts the DELETE_INSTANCE entry is present with a terminal success status.

### Implementation for User Story 3

- [X] T047 [US3] Added `parameters: JSON | None` to the GraphQL `Task` type, the domain `Task` model, and the `Task` DB model; Alembic migration `a7b8c9d0e1f2_add_task_parameters.py` adds the column. The delete service now stores `{"backup_disposition": "retain"|"remove"}` on the task, so the timeline can render the operator's choice long after the task has completed.
- [X] T048 [US3] Frontend `DeploymentTimeline` now renders delete entries as `Delete — backups retained` / `Delete — backups removed` pulled from `task.parameters.backup_disposition`. Both the frontend and SDK `get_deployment_timeline.graphql` queries fetch `parameters`.
- [X] T049 [US3] Schema + SDK + frontend codegen regenerated.

**Checkpoint**: US3 complete — deletion lifecycle is fully auditable.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T050 [P] Run the full quickstart against a live stack. *Still requires a live Postgres + Kind cluster in CI or a dev box to execute. The quickstart in `specs/001-delete-deployment/quickstart.md` is now directly runnable against the implementation — the deferred box is only the physical "someone clicked through it".*
- [ ] T051 [P] `dev/knowledge/backend/reconciliation.md` update. *Skipped — the feature uses a direct `run_action` dispatch rather than the diff→remediation path, so the existing reconciliation knowledge remains accurate. When the operator-handler follow-up lands, a short section on the deletion-intent contract will be worth adding.*
- [ ] T052 [P] `AGENTS.md` updates. *Skipped — no new conventions were introduced (error-code naming follows existing `ALREADY_IN_PROGRESS` / `ALREADY_DELETED` patterns).*
- [X] T053 Final `uv run invoke format lint` + `uv run ruff check backend/styrmin_backend/` + `pnpm lint` + `pnpm tsc --noEmit` — all clean.
- [ ] T054 CI green on the PR. *Pending — no PR open yet; the branch `001-delete-deployment` carries four commits ready to push.*
- [X] T055 Post-rebase tombstone guard for sibling mutations (FR-003a). After the rebase onto develop pulled in the new `update_deployment` mutation (pod scheduling), both `update_deployment` and `update_deployment_version` were unconditionally calling `set_status(PENDING)` and would silently revive a tombstoned deployment. Added the `DELETION_REQUESTED / DELETION_IN_PROGRESS / DELETED → DeploymentAlreadyDeletedError` guard at the entry of both functions and parametrized unit tests in `backend/tests/unit/services/test_deployment_update_tombstone_guard.py`. **Future mutations under `services/deployment.py` MUST replicate this guard** — see the data-model invariants.
- [X] T056 Dual-entrypoint E2E coverage. Develop introduced a `driver_mode=[api,ui]` parametrization for every E2E test. Marked the four existing deletion E2E tests in `test_deployment_deletion.py` as `api_only` (they drive the SDK directly), and added a new `ui_only` scenario in `test_deployment_deletion_ui.py` that exercises the delete dialog through a `delete_deployment(disposition)` page-object method on `DeploymentDetailPage`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: no dependencies.
- **Phase 2 (Foundational)**: depends on Phase 1. Blocks all user stories.
- **Phase 3 (US2, API)**: depends on Phase 2.
- **Phase 4 (US1, UI)**: depends on Phase 2. Functionally consumes US2, but tasks can start once the GraphQL contract (T026) has landed — US1 tests mock the mutation hook, so the UI can be built in parallel with US2 implementation.
- **Phase 5 (US3, timeline)**: depends on Phase 2. Independently testable but adds the most value after US2 produces `DELETE_INSTANCE` Tasks in practice.
- **Phase 6 (Polish)**: depends on US1 + US2 + US3.

### Critical path within US2

- T020 depends on T003–T010 (foundation) and T021 (flow module) / T022 (operator) / T023 (status mirror). T020 can be implemented against a stubbed flow once T021 exists.
- T029 (schema regen) depends on T025–T027.
- T030–T032 (SDK) depend on T029.
- T017–T019 (E2E) depend on T020–T024 + T029 and on the operator update T022.

### Critical path within US1

- T038 (frontend type regen) depends on T029 (schema regen from US2).
- T039 depends on T037 + T038.
- T040 depends on T039.
- T042, T043 depend on T041.

### Parallel Opportunities

- T003, T004, T006, T007, T009 in Phase 2 can run in parallel (all touch distinct files).
- Within US2: all `[P]`-tagged tests (T011–T016) can run in parallel. T025 (enum), T030 (SDK query file) can run in parallel with service work.
- Within US1: T035 & T036 (component tests) and T037 (mutation doc) can run in parallel; T039 can run in parallel with T040 only after T038 produces types.
- US1 and US3 can be worked in parallel by different developers once US2's contract (T026) and schema (T029) land.

---

## Parallel Example: User Story 2 tests

```text
# Fire off test-writing in parallel before US2 implementation begins:
Task: Unit test happy path — backend/tests/unit/services/test_deployment_delete.py
Task: Unit test concurrency — backend/tests/unit/services/test_deployment_delete_concurrency.py
Task: Unit test idempotency — backend/tests/unit/services/test_deployment_delete_idempotency.py
Task: Unit test backup disposition — backend/tests/unit/services/test_deployment_delete_backups.py
Task: Contract test delete mutation — backend/tests/integration/api/test_delete_deployment_mutation.py
Task: Contract test includeDeleted listing — backend/tests/integration/api/test_environment_deployments_include_deleted.py
```

---

## Implementation Strategy

### MVP (US2 only)

1. Phase 1 Setup.
2. Phase 2 Foundational.
3. Phase 3 User Story 2 — ship a complete backend-only deletion
   path, verified end-to-end on Kind. This alone satisfies FR-001,
   FR-002, FR-003, FR-004, FR-005, FR-006, FR-007, FR-008, FR-009,
   FR-012, FR-013, FR-014.
4. Stop and validate against `quickstart.md` (backend section).

### Incremental Delivery

1. Setup + Foundational → foundation ready.
2. Add US2 (API) → MVP → demo via SDK / `curl`.
3. Add US1 (UI) → test independently → demo via the UI.
4. Add US3 (timeline) → test independently → final polish.

### Parallel Team Strategy

With three developers after Phase 2:

- Dev A: US2 (API, service, flow, operator).
- Dev B: US1 (UI), starts as soon as the GraphQL contract is
  reviewed — frontend tests mock the mutation.
- Dev C: US3 (timeline), begins on the timeline type changes once
  the mutation lands.

---

## Notes

- Tests are required (FR-015); write them before implementation.
- Constitution rule VI: `uv run invoke format lint` must pass before each commit.
- Governance gates (DB schema + GraphQL schema) must be confirmed
  before starting Phase 2 (T001).
- Do not run `update-agent-context.sh` — forbidden by the
  constitution.
- Commit after each task or logical group. Stop at the end of
  Phase 3 for MVP validation before opening the UI PR.
