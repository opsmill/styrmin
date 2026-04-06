# Tasks: Kubernetes Operator for Deployment Reconciliation

**Input**: Design documents from `/specs/001-k8s-operator/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Included per Constitution Principle V (Test-First Development) — tests are required for all new functionality.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add kopf dependency, create operator and entrypoint module structures

- [x] T001 Add kopf dependency to pyproject.toml and run `uv sync --all-groups --all-packages`
- [x] T002 [P] Create operator module directory structure with `__init__.py` files at backend/styrmin_backend/operator/, backend/styrmin_backend/operator/handlers/
- [x] T003 [P] Create entrypoint module directory structure with `__init__.py` files at backend/styrmin_backend/entrypoint/
- [x] T004 [P] Create test directory structure at tests/unit/operator/, tests/integration/operator/

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core operator infrastructure that MUST be complete before any user story can be implemented

**CRITICAL**: No user story work can begin until this phase is complete

- [x] T005 [P] Implement operator configuration constants (label names, annotation keys, env vars, default intervals) in backend/styrmin_backend/operator/config.py
- [x] T006 [P] Implement desired state resolution client that calls `GET /deployments/{deployment_id}/context` and builds utility resource specs using existing `UtilityResourceBuilder` and `build_utility()` in backend/styrmin_backend/operator/state.py
- [x] T007 [P] Implement Kubernetes Event emission helper with `ReconcileSucceeded`, `DriftDetected`, `ReconcileFailed` event types per contracts/operator-events.md in backend/styrmin_backend/operator/events.py
- [x] T008 Add `styrmin.io/operator-managed: "true"` label and `styrmin.io/deployment-id` annotation to HelmRelease creation in backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py (the `ApplicationHelmReleaseBuilder`)
- [x] T009 Add `styrmin.io/deployment-in-progress: "true"` annotation set/remove lifecycle to Prefect orchestration flows — set before utility resource modification, remove after completion — in backend/styrmin_backend/agent/tasks/orchestration.py

**Checkpoint**: Foundation ready — operator config, state client, events helper, and label/annotation plumbing all in place. User story implementation can now begin.

---

## Phase 3: User Story 1 — Operator-Managed NetworkPolicy Lifecycle (Priority: P1) MVP

**Goal**: The kopf operator creates, reconciles, and deletes NetworkPolicies for new (operator-managed) deployments. Prefect no longer manages NetworkPolicies for these deployments.

**Independent Test**: Create a deployment via Prefect, verify the operator creates NetworkPolicies (not Prefect). Delete/modify a NetworkPolicy and verify the operator restores it.

### Tests for User Story 1

- [x] T010 [P] [US1] Write unit tests for core reconciler logic (desired vs actual comparison, apply/skip decisions, idempotency) in tests/unit/operator/test_reconciler.py
- [x] T011 [P] [US1] Write unit tests for HelmRelease create/delete handlers using kopf.testing (mock state client, verify NetworkPolicy creation/cleanup) in tests/unit/operator/test_handlers.py
- [x] T012 [P] [US1] Write unit tests for state client (mock httpx responses for context endpoint, verify utility resource spec building) in tests/unit/operator/test_state.py

### Implementation for User Story 1

- [x] T013 [US1] Implement core reconciler: accept desired resource list and actual resource list, compute diff, apply creates/updates/deletes using existing `apply_kubernetes_resource` primitives in backend/styrmin_backend/operator/reconciler.py
- [x] T014 [US1] Implement `@kopf.on.create` handler for HelmRelease with label `styrmin.io/operator-managed=true` — fetch GlobalContext via state client, build NetworkPolicy specs via `IngressUtility` + `UtilityResourceBuilder`, filter to NetworkPolicy kind only, call reconciler to create them in backend/styrmin_backend/operator/handlers/helmrelease.py
- [x] T015 [US1] Implement `@kopf.on.delete` handler for HelmRelease with label `styrmin.io/operator-managed=true` — list NetworkPolicies by `styrmin.io/release-reference` label, delete operator-created ones in backend/styrmin_backend/operator/handlers/helmrelease.py
- [x] T016 [US1] Implement `@kopf.on.update` and `@kopf.on.delete` handlers for NetworkPolicy with labels `app.kubernetes.io/managed-by=styrmin` and `styrmin.io/operator-managed=true` — on drift, look up parent HelmRelease by release-reference, fetch desired state, reconcile in backend/styrmin_backend/operator/handlers/utility_resources.py
- [x] T017 [US1] Modify Prefect utility flows to skip NetworkPolicy resources for operator-managed deployments: in `_apply_utility()` filter out NetworkPolicy kind from resources list when HelmRelease has `styrmin.io/operator-managed` label, in backend/styrmin_backend/agent/tasks/extra.py
- [x] T018 [US1] Write integration test: use kopf.testing runner to simulate HelmRelease creation, verify NetworkPolicies created; simulate NetworkPolicy deletion, verify re-creation in tests/integration/operator/test_reconciliation.py

**Checkpoint**: NetworkPolicy lifecycle is fully operator-managed for new deployments. Prefect no longer creates NetworkPolicies for operator-managed deployments. Drift on NetworkPolicies is automatically corrected.

---

## Phase 4: User Story 2 — Continuous Reconciliation of Other Utility Resources (Priority: P2)

**Goal**: The operator watches and reconciles Services, Secrets, and Traefik Middlewares that were created by Prefect, restoring them to desired state on drift.

**Independent Test**: Deploy an application, manually modify a Service's port configuration, verify the operator restores it.

### Tests for User Story 2

- [x] T019 [P] [US2] Write unit tests for Service/Secret/Middleware drift handlers (verify reconciliation triggered on update/delete, verify skip when deployment-in-progress) in tests/unit/operator/test_utility_handlers.py

### Implementation for User Story 2

- [x] T020 [P] [US2] Implement `@kopf.on.update` and `@kopf.on.delete` handlers for Service with label `app.kubernetes.io/managed-by=styrmin` — look up parent HelmRelease, check deployment-in-progress annotation, fetch desired state, reconcile in backend/styrmin_backend/operator/handlers/utility_resources.py
- [x] T021 [P] [US2] Implement `@kopf.on.update` and `@kopf.on.delete` handlers for Secret with label `app.kubernetes.io/managed-by=styrmin` in backend/styrmin_backend/operator/handlers/utility_resources.py
- [x] T022 [P] [US2] Implement `@kopf.on.update` and `@kopf.on.delete` handlers for Middleware CRD (`traefik.io/v1alpha1`) with label `app.kubernetes.io/managed-by=styrmin` in backend/styrmin_backend/operator/handlers/utility_resources.py
- [x] T023 [US2] Implement `@kopf.timer` on HelmRelease (interval=60s) for periodic full reconciliation — fetch all desired utility resources, compare with actual cluster state, reconcile any drift in backend/styrmin_backend/operator/handlers/helmrelease.py
- [x] T024 [US2] Add deployment-in-progress conflict avoidance check to reconciler — before reconciling, check parent HelmRelease for `styrmin.io/deployment-in-progress` annotation, skip if present in backend/styrmin_backend/operator/reconciler.py

**Checkpoint**: All utility resource types (NetworkPolicies, Services, Secrets, Middlewares) are reconciled. Periodic timer ensures convergence even if events are missed. Operator defers to active Prefect flows.

---

## Phase 5: User Story 3 — Combined Agent/Operator Process (Priority: P3)

**Goal**: The kopf operator and Prefect worker run together in a single container as a unified async process with graceful shutdown.

**Independent Test**: Start the combined process, verify both Prefect picks up work and kopf watches resources. Send SIGTERM, verify both stop cleanly.

### Tests for User Story 3

- [x] T025 [P] [US3] Write unit tests for combined entrypoint (verify asyncio.gather setup, shutdown event propagation, graceful termination) in tests/unit/operator/test_entrypoint.py

### Implementation for User Story 3

- [x] T026 [US3] Implement Prefect worker async wrapper: `BaseWorker` as context manager with anyio task group running `critical_service_loop` for polling and heartbeat, racing against a shared `asyncio.Event` for shutdown in backend/styrmin_backend/entrypoint/combined.py
- [x] T027 [US3] Implement `@kopf.on.startup` handler: configure peering settings (`settings.peering.name = "styrmin-operator"`, `settings.peering.mandatory = True`, `settings.peering.priority = 100`) in backend/styrmin_backend/entrypoint/combined.py
- [x] T028 [US3] Implement `@kopf.on.cleanup` handler: set shared `_shutdown` asyncio.Event to signal Prefect worker termination in backend/styrmin_backend/entrypoint/combined.py
- [x] T029 [US3] Implement `main()` async entrypoint: `asyncio.gather(kopf.operator(clusterwide=True), run_prefect_worker())` with CLI argument parsing for work-pool name in backend/styrmin_backend/entrypoint/combined.py
- [x] T030 [US3] Create `__main__.py` for `python -m styrmin_backend.entrypoint.combined` execution in backend/styrmin_backend/entrypoint/__main__.py

**Checkpoint**: The combined process starts both kopf and Prefect worker, handles SIGTERM gracefully with kopf cleanup bridging to Prefect shutdown, and supports leader election via peering.

---

## Phase 6: User Story 4 — Deployment Tracking and Status Reporting (Priority: P4)

**Goal**: The operator emits Kubernetes Events on HelmRelease resources to report reconciliation status (in-sync, drift detected, errors).

**Independent Test**: Deploy an application, verify ReconcileSucceeded event appears. Introduce drift, verify DriftDetected event. Simulate an error, verify ReconcileFailed event.

### Tests for User Story 4

- [x] T031 [P] [US4] Write unit tests for event emission integration (verify correct event type/reason/message emitted at each reconciliation outcome) in tests/unit/operator/test_events.py

### Implementation for User Story 4

- [x] T032 [US4] Integrate `ReconcileSucceeded` event emission into reconciler success path — emit after all resources confirmed in-sync in backend/styrmin_backend/operator/handlers/helmrelease.py
- [x] T033 [US4] Integrate `DriftDetected` event emission into drift handler paths — emit when handler detects resource modification or deletion in backend/styrmin_backend/operator/handlers/utility_resources.py
- [x] T034 [US4] Integrate `ReconcileFailed` event emission into error handling paths — emit on API errors, permission denied, or invalid specs with error details in message in backend/styrmin_backend/operator/handlers/helmrelease.py
- [x] T035 [US4] Add exponential backoff to reconciler error handling — avoid tight retry loops on persistent failures, log retry attempts in backend/styrmin_backend/operator/reconciler.py

**Checkpoint**: Platform operators can see reconciliation status via `kubectl describe helmrelease/<name>`. Events provide full audit trail of drift detection and correction.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Formatting, RBAC, Helm chart updates, and end-to-end validation

- [x] T036 Run `uv run invoke format lint` and fix any issues across all new and modified files
- [x] T037 [P] Update RBAC permissions in helm/styrmin/templates/prefect-worker-rbac.yaml — add get/list/watch for HelmReleases, NetworkPolicies, Services, Secrets, Middlewares, Events, and ClusterKopfPeering
- [x] T038 [P] Add ClusterKopfPeering CRD manifest and peering object to Helm chart templates in helm/styrmin/templates/operator/
- [x] T039 [P] Update docker-compose.yml to replace separate task-worker/k8s-agent services with combined agent-operator service
- [ ] T040 Validate quickstart.md flow end-to-end: start combined process, create deployment, verify NetworkPolicy creation, test drift correction, verify events

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **User Stories (Phase 3-6)**: All depend on Foundational phase completion
  - US1 (P1): Can start immediately after Phase 2
  - US2 (P2): Can start after Phase 2 — extends handlers from US1 but adds to different resource types
  - US3 (P3): Can start after Phase 2 — independent entrypoint work
  - US4 (P4): Can start after Phase 2 — adds event calls to reconciler. Benefits from US1 reconciler being complete
- **Polish (Phase 7)**: Depends on all desired user stories being complete

### User Story Dependencies

- **US1 (P1)**: Can start after Foundational — No dependencies on other stories. Establishes reconciler and HelmRelease handlers.
- **US2 (P2)**: Extends utility_resources.py from US1 and adds timer to helmrelease.py. Benefits from US1 reconciler but can implement independently.
- **US3 (P3)**: Independent entrypoint module — no dependency on US1/US2. Kopf startup/cleanup handlers added to helmrelease.py.
- **US4 (P4)**: Adds event emission calls into reconciler.py — benefits from US1 reconciler being in place. Can implement events.py usage independently.

### Within Each User Story

- Tests written first and verified to fail before implementation
- State/config infrastructure before handlers
- Handlers before integration points
- Core implementation before cross-component integration

### Parallel Opportunities

- **Phase 1**: T002, T003, T004 all run in parallel
- **Phase 2**: T005, T006, T007 run in parallel (different files); T008, T009 sequential (modify existing files)
- **Phase 3 (US1)**: T010, T011, T012 tests in parallel; T014-T016 are sequential (same/related files)
- **Phase 4 (US2)**: T020, T021, T022 handlers in parallel (different resource types, same file but different sections)
- **Phase 5 (US3)**: T026-T030 mostly sequential (building up combined.py and helmrelease.py)
- **Phase 7**: T037, T038, T039 all in parallel (different files)

---

## Parallel Example: User Story 1

```text
# Launch all tests together (write first, verify they fail):
Task T010: "Unit tests for reconciler in tests/unit/operator/test_reconciler.py"
Task T011: "Unit tests for handlers in tests/unit/operator/test_handlers.py"
Task T012: "Unit tests for state client in tests/unit/operator/test_state.py"

# Then implement — reconciler first, then handlers sequentially:
Task T013: "Core reconciler in backend/styrmin_backend/operator/reconciler.py"
Task T014: "HelmRelease create handler in backend/styrmin_backend/operator/handlers/helmrelease.py"
Task T015: "HelmRelease delete handler in backend/styrmin_backend/operator/handlers/helmrelease.py"
Task T016: "NetworkPolicy drift handlers in backend/styrmin_backend/operator/handlers/utility_resources.py"
Task T017: "Skip NetworkPolicy in Prefect flows in backend/styrmin_backend/agent/tasks/extra.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (add kopf, create module structure)
2. Complete Phase 2: Foundational (config, state client, events helper, labels)
3. Complete Phase 3: User Story 1 (NetworkPolicy lifecycle)
4. **STOP and VALIDATE**: Create a deployment, verify operator creates NetworkPolicies, delete one, verify it's recreated
5. Deploy/demo if ready — this alone delivers the primary value

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add US1 (NetworkPolicy lifecycle) → Test independently → **MVP!**
3. Add US2 (Other utility reconciliation) → Test independently → Full reconciliation coverage
4. Add US3 (Combined process) → Test independently → Single container deployment
5. Add US4 (Status reporting) → Test independently → Full observability
6. Each story adds value without breaking previous stories

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: User Story 1 (NetworkPolicy lifecycle) — **priority**
   - Developer B: User Story 3 (Combined entrypoint) — independent module
3. After US1 complete:
   - Developer A: User Story 2 (extends US1 patterns)
   - Developer B: User Story 4 (adds events to US1 reconciler)

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify tests fail before implementing (Constitution Principle V)
- Run `uv run invoke format lint` after each phase (Constitution Principle VI)
- The operator module reuses existing `UtilityResourceBuilder`, `IngressUtility`, `build_utility()`, and `apply_kubernetes_resource` — do not reimplement
- kopf handlers are decorated functions at module level — they register automatically when the module is imported
