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

- [ ] T011 [P] [US2] Unit test: service `delete_deployment` happy path — transitions state, creates DELETE_INSTANCE Task, submits Prefect flow, returns Task. `backend/tests/unit/services/test_deployment_delete.py`
- [ ] T012 [P] [US2] Unit test: concurrency guard rejects when a PENDING/RUNNING Task exists for the deployment. `backend/tests/unit/services/test_deployment_delete_concurrency.py`
- [ ] T013 [P] [US2] Unit test: idempotency — second call on a deployment already in DELETION_* / DELETED raises `DeploymentAlreadyDeletedError`. `backend/tests/unit/services/test_deployment_delete_idempotency.py`
- [ ] T014 [P] [US2] Unit test: `backup_disposition=REMOVE` enqueues backup removals; `RETAIN` keeps them and reassociates them to the tombstoned deployment. `backend/tests/unit/services/test_deployment_delete_backups.py`
- [ ] T015 [P] [US2] Contract test: GraphQL `deleteDeployment` mutation matches `specs/001-delete-deployment/contracts/delete_deployment.graphql` (shape, required args, typed error codes). `backend/tests/integration/api/test_delete_deployment_mutation.py`
- [ ] T016 [P] [US2] Contract test: `Environment.deployments(includeDeleted: Boolean = false)` — default excludes DELETED records, `true` includes them. `backend/tests/integration/api/test_environment_deployments_include_deleted.py`
- [ ] T017 [US2] E2E test (Kind): deploy a real application, call `deleteDeployment(..., RETAIN)`, poll until `DELETED`; assert no Styrmin-owned HelmReleases / driver CRs / utility resources / namespace labels remain, backups still listable from the tombstoned deployment. `backend/tests/e2e/test_deployment_deletion_retain.py`
- [ ] T018 [US2] E2E test (Kind): same flow with `REMOVE`; assert backups are gone and the deployment reaches `DELETED` only after backup removals succeed. `backend/tests/e2e/test_deployment_deletion_remove.py`
- [ ] T019 [US2] E2E test (Kind): partial teardown failure — force a resource to get stuck (e.g., a finalizer) and assert the Task is `FAILED` with a surfaced `failure_reason` and the deployment remains in `DELETION_IN_PROGRESS` until retry resolves it. `backend/tests/e2e/test_deployment_deletion_partial_failure.py`

### Implementation for User Story 2

- [ ] T020 [US2] Implement `async def delete_deployment(deployment_id: UUID, uow: UnitOfWork, backup_disposition: BackupDisposition) -> Task` in `backend/styrmin_backend/services/deployment.py` — validates existence, runs the concurrency guard via `uow.deployments.list_active_tasks()`, transitions deployment to `DELETION_REQUESTED`, creates a `DELETE_INSTANCE` Task recording `backup_disposition` in Task parameters, submits the Prefect flow via `PrefectManager.run_action(PrefectAction.DELETE_INSTANCE, ...)`, stores `prefect_flow_run_id` on the Task, and commits the UoW.
- [ ] T021 [US2] Add the Prefect flow module `backend/styrmin_backend/workflows/flows/delete_instance.py` — for `REMOVE`, iterates associated backups and invokes the existing backup-deletion service; then declares deletion intent on the `StyrminDeployment` CRD per ADR-008 and awaits terminal CRD status before marking the Task SUCCESS.
- [ ] T022 [US2] Wire the operator handler in `backend/styrmin_backend/operator/handlers/styrmin_deployment.py` to observe the new deletion intent and tear down owned driver CRs, HelmReleases, utility resources, and namespace labels (respecting FR-006: do not touch foreign objects). Report progress via the CRD status.
- [ ] T023 [US2] Extend the reconciliation loop / status mirror so that `Deployment.status` advances from `DELETION_IN_PROGRESS` to `DELETED` (setting `deleted_at`) once `DeploymentStatus.phase` reports terminal teardown success. Touchpoints: `backend/styrmin_backend/services/reconciliation/` and the status-mirror handler.
- [ ] T024 [US2] Ensure `InstanceDeletion` diff + `InstanceDeletionStrategy` in `backend/styrmin_backend/services/reconciliation/remediation.py` route through `PrefectAction.DELETE_INSTANCE` (confirm or wire).
- [ ] T025 [P] [US2] Add the GraphQL `BackupDisposition` enum in `backend/styrmin_backend/api/definitions/deployment/model.py` (or the definitions package appropriate for enums).
- [ ] T026 [US2] Add the `delete_deployment` Strawberry mutation in `backend/styrmin_backend/api/schema/mutation.py` — inputs `deployment_id: UUID`, `backup_disposition: BackupDisposition`; payload `Task`; raises the three typed errors from T007; follows the existing `update_deployment` mutation pattern.
- [ ] T027 [US2] Add `includeDeleted: bool = False` argument to the `Environment.deployments` resolver in `backend/styrmin_backend/api/definitions/environment/` (the resolver that lists deployments for an environment). Default filter excludes `DELETED`; flag flips the filter.
- [ ] T028 [US2] Update `SQLModelDeploymentRepository.find_internal_by_environment` in `backend/styrmin_backend/repository/deployment.py` to accept an `include_deleted: bool = False` argument.
- [ ] T029 [US2] Regenerate the GraphQL schema: `uv run styrmin export graphql-schema schema.graphql` (outputs to repo root `schema.graphql`).
- [ ] T030 [P] [US2] Add the SDK query document `python_sdk/src/styrmin_sdk/graphql/delete_deployment.graphql` matching the contract.
- [ ] T031 [US2] Add `async def delete(deployment_id: UUID, backup_disposition: BackupDisposition) -> Task` on the deployments SDK resource in `python_sdk/src/styrmin_sdk/resources/deployments.py`, loading the query via `load_query("delete_deployment")`.
- [ ] T032 [US2] Regenerate SDK Pydantic types: `uv run invoke generate`.
- [ ] T033 [US2] Run `uv run invoke validate-graphql` to confirm the new `.graphql` documents are schema-valid.
- [ ] T034 [US2] Run `uv run invoke format lint` and fix any issues.

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

- [ ] T035 [P] [US1] Component test for `DeleteDeploymentDialog` — shows deployment name, requires backup disposition choice, cancel is inert, confirm invokes mutation with chosen disposition. `frontend/src/pages/deployments/__tests__/DeleteDeploymentDialog.test.tsx`
- [ ] T036 [P] [US1] Component test: on mutation error with `extensions.code == "DEPLOYMENT_MUTATION_IN_PROGRESS"`, a toast is rendered and the dialog stays open. `frontend/src/pages/deployments/__tests__/DeleteDeploymentDialog.error.test.tsx`

### Implementation for User Story 1

- [ ] T037 [P] [US1] Add the frontend mutation document `frontend/src/graphql/operations/delete_deployment.graphql` mirroring the contract.
- [ ] T038 [US1] Regenerate frontend GraphQL types (GraphQL Codegen — follow the project's existing `pnpm` script, e.g. `pnpm generate`).
- [ ] T039 [P] [US1] Create `frontend/src/pages/deployments/DeleteDeploymentDialog.tsx` — Base-UI dialog with deployment-name confirmation and retain/remove backup radio options (required choice; no default). Disables Confirm while mutation is in flight.
- [ ] T040 [US1] Wire a **Delete** action into `frontend/src/pages/deployments/DeploymentDetailPage.tsx` alongside existing actions: state `deleteOpen`, `useDeleteDeploymentMutation`, `useNavigate`. On success, invalidate `GetDeployment` + `GetDeploymentTimeline` queries; on mutation-error surface a toast with the typed code.
- [ ] T041 [US1] Reflect `DELETION_REQUESTED` / `DELETION_IN_PROGRESS` states in the deployment detail page as a read-only "Deletion in progress" banner that hides mutation actions (upgrade, backup-create, etc.) — prevents operators from attempting other writes that would be rejected by the API anyway.
- [ ] T042 [US1] On the existing 10s `GetDeployment` refetch, when status transitions to `DELETED`, navigate to `/environments/$environmentId` using TanStack Router.
- [ ] T043 [US1] Ensure the deployment URL for a `DELETED` record renders a read-only tombstoned view (no actions, timeline still visible). Reuse the same page; gate actions behind the non-terminal-state check added in T041.
- [ ] T044 [US1] Run `pnpm lint` and `pnpm tsc --noEmit` and fix issues.

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

- [ ] T045 [P] [US3] Unit test: timeline service renders a `DELETE_INSTANCE` Task with its `backup_disposition` parameter and `failure_reason` (when FAILED). `backend/tests/unit/services/test_deployment_timeline_delete.py`
- [ ] T046 [P] [US3] E2E test: after deletion, fetch the timeline via SDK for the tombstoned deployment and assert the DELETE_INSTANCE entry is present with the chosen disposition and a terminal success status. `backend/tests/e2e/test_deployment_timeline_deletion.py`

### Implementation for User Story 3

- [ ] T047 [US3] Surface `backup_disposition` (and, on failure, `failure_reason`) on the `DeploymentTimelineEntry` Strawberry type in `backend/styrmin_backend/api/definitions/deployment_timeline/model.py`. Pull the disposition from the associated Task's parameters.
- [ ] T048 [US3] Render the `DELETE_INSTANCE` entry in the frontend timeline component with a dedicated label ("Deletion — backups retained/removed"), failure reason when present. Touch: the timeline component under `frontend/src/pages/deployments/` (existing timeline renderer).
- [ ] T049 [US3] Regenerate GraphQL schema + SDK types if T047 changed the schema: `uv run styrmin export graphql-schema schema.graphql && uv run invoke generate`.

**Checkpoint**: US3 complete — deletion lifecycle is fully auditable.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T050 [P] Run the full quickstart in `specs/001-delete-deployment/quickstart.md` against the dev stack (API smoke, UI flow, concurrency guard, REMOVE path, idempotency).
- [ ] T051 [P] Update `dev/knowledge/backend/reconciliation.md` (and any other relevant knowledge docs) to mention the deletion lifecycle and where it hooks in. Only if the existing docs reference delete in a stale way — otherwise skip.
- [ ] T052 [P] Update `backend/AGENTS.md` / `frontend/AGENTS.md` if new conventions were introduced (e.g., typed-error code naming). Likely skipped — confirm and note.
- [ ] T053 Final `uv run invoke format lint` + `pnpm lint` + `pnpm tsc --noEmit` pass.
- [ ] T054 Confirm CI (tests + lint + schema/SDK drift checks) is green on the PR.

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
