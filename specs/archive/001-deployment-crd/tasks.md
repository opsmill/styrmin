# Tasks: StyrminDeployment CRD for Operator-Driven Resource Lifecycle

**Input**: Design documents from `/specs/001-deployment-crd/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Included per Constitution Principle V (Test-First Development).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)

---

## Phase 1: Setup

**Purpose**: CRD definition, module structure, shared models

- [x] T001 Create the StyrminDeployment CRD YAML definition (v1alpha1 with spec, status subresource, and printer columns) in helm/styrmin/templates/operator/styrmin-deployment-crd.yaml per contracts/crd-schema.md
- [x] T002 [P] Create operator CRD subpackage with `__init__.py` at backend/styrmin_backend/operator/crd/
- [x] T003 [P] Create test directory at tests/unit/operator/crd/

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: CRD schema models, status condition helpers, and pipeline infrastructure that ALL user stories depend on

**CRITICAL**: No user story work can begin until this phase is complete

- [x] T004 [P] Implement CRD spec/status Python models (Pydantic) matching the CRD schema: StyrminDeploymentSpec, StyrminDeploymentStatus, DeploymentCondition, DeploymentPhase enum in backend/styrmin_backend/operator/crd/schema.py
- [x] T005 [P] Implement status condition helper functions: set_condition(), get_condition(), set_phase(), build_managed_resource_counts() in backend/styrmin_backend/operator/crd/status.py
- [x] T006 [P] Write unit tests for CRD schema model validation and status helpers in tests/unit/operator/crd/test_schema.py
- [x] T007 Add CRD-related constants (group, version, plural, phase enum values, condition types) to backend/styrmin_backend/operator/config.py
- [x] T008 Update RBAC in helm/styrmin/templates/prefect-worker-rbac.yaml to add get/list/watch/create/update/patch/delete for styrmindeployments.styrmin.io and styrmindeployments/status

**Checkpoint**: CRD definition deployed, Python models ready, status helpers available.

---

## Phase 3: User Story 1 — Ordered Resource Deployment (Priority: P1) MVP

**Goal**: The operator watches StyrminDeployment CRDs and deploys resources in guaranteed order: NetworkPolicies/Secrets → HelmRelease (blocked until phase 1) → Services/Middlewares.

**Independent Test**: Create a StyrminDeployment CRD, verify NetworkPolicies appear before HelmRelease, and Services appear after HelmRelease is Ready.

### Tests for User Story 1

- [x] T009 [P] [US1] Write unit tests for the ordered deployment pipeline (phase sequencing, blocking behavior, error propagation) in tests/unit/operator/test_pipeline.py
- [x] T010 [P] [US1] Write unit tests for StyrminDeployment create/resume handlers in tests/unit/operator/test_styrmin_deployment.py

### Implementation for User Story 1

- [x] T011 [US1] Implement the ordered deployment pipeline with three phases: (1) create NetworkPolicies + Secrets using existing UtilityResourceBuilder, verify all applied, (2) create HelmRelease using existing ApplicationHelmReleaseBuilder, wait for FluxCD Ready, (3) create Services + Middlewares using UtilityResourceBuilder, in backend/styrmin_backend/operator/pipeline.py
- [x] T012 [US1] Implement `@kopf.on.create` handler for StyrminDeployment CRD using sub-handler pattern — register phase-1-prerequisites, phase-2-helmrelease, phase-3-services sub-handlers, update CRD status phase and conditions after each, use kopf.adopt() for owner references, in backend/styrmin_backend/operator/handlers/styrmin_deployment.py
- [x] T013 [US1] Implement `@kopf.on.resume` handler for StyrminDeployment CRD to resume interrupted deployments from current phase on operator restart in backend/styrmin_backend/operator/handlers/styrmin_deployment.py
- [x] T014 [US1] Update state.py to add a function that builds desired resources from a CRD spec (deserialize GlobalContext from CRD, call existing utility builders) instead of fetching from API, in backend/styrmin_backend/operator/state.py

**Checkpoint**: Creating a StyrminDeployment CRD triggers ordered deployment. NetworkPolicies/Secrets are verified before HelmRelease creation. Status conditions track each phase.

---

## Phase 4: User Story 2 — Prefect Orchestration via CRD (Priority: P2)

**Goal**: Prefect flows create/update/delete StyrminDeployment CRDs instead of directly managing HelmReleases and utility resources.

**Independent Test**: Trigger a deployment via the Styrmin API. Verify Prefect creates a StyrminDeployment CRD (not a HelmRelease). Verify the operator then deploys all resources.

### Tests for User Story 2

- [x] T015 [P] [US2] Write unit tests for the refactored Prefect orchestration flows (verify CRD create/update/delete instead of direct resource management) in tests/unit/operator/test_prefect_crd_integration.py

### Implementation for User Story 2

- [x] T016 [US2] Implement a helper function to build a StyrminDeployment CRD body from GlobalContext, rendered Helm specs, and deployment metadata in backend/styrmin_backend/operator/crd/builder.py
- [x] T017 [US2] Add `create_instance_crd` flow in backend/styrmin_backend/agent/tasks/orchestration.py that creates a StyrminDeployment CRD via upsert_custom_resource with driver pre/post hooks retained
- [x] T018 [US2] Add `update_instance_crd` flow in backend/styrmin_backend/agent/tasks/orchestration.py that updates the StyrminDeployment CRD spec
- [x] T019 [US2] Add `upgrade_instance_crd` flow in backend/styrmin_backend/agent/tasks/orchestration.py that updates CRD spec with new version context and runs driver hooks
- [x] T020 [US2] Implement `@kopf.on.update` handler for StyrminDeployment CRD — detect spec changes and re-run the ordered deployment pipeline for changed phases, in backend/styrmin_backend/operator/handlers/styrmin_deployment.py
- [x] T021 [US2] Existing utility flows already filter NetworkPolicies (from 001-k8s-operator). CRD-based flows bypass utility flows entirely — no further changes needed in extra.py

**Checkpoint**: Prefect flows produce StyrminDeployment CRDs. The operator handles all resource lifecycle. Direct HelmRelease and utility management removed from Prefect for new deployments.

---

## Phase 5: User Story 3 — Full Utility Resource Management (Priority: P3)

**Goal**: Operator manages ALL utility resources (NetworkPolicies, Secrets, Services, Middlewares) with drift detection and correction.

**Independent Test**: Create a StyrminDeployment. Manually modify a Service/Secret/Middleware. Verify the operator restores it within 60 seconds.

### Tests for User Story 3

- [x] T022 [P] [US3] Write unit tests for drift detection on all resource types (Service, Secret, Middleware drift triggers reconciliation from CRD) in tests/unit/operator/test_crd_drift.py

### Implementation for User Story 3

- [x] T023 [US3] Implement `@kopf.timer` on StyrminDeployment CRD (interval=60s) for periodic full reconciliation — compute desired state from CRD spec, compare with actual cluster state across all five resource types, reconcile drift, in backend/styrmin_backend/operator/handlers/styrmin_deployment.py
- [x] T024 [US3] Drift handlers in utility_resources.py already work for CRD-managed resources via label matching — no changes needed, the timer on StyrminDeployment handles CRD-level drift
- [x] T025 [US3] Implement `@kopf.on.delete` handler for StyrminDeployment CRD with ordered cleanup: (1) Services/Middlewares, (2) HelmRelease, (3) NetworkPolicies/Secrets, in backend/styrmin_backend/operator/handlers/styrmin_deployment.py

**Checkpoint**: Drift on any managed resource is detected and corrected. Deletion cleans up in reverse order. All five resource types fully operator-managed.

---

## Phase 6: User Story 4 — CRD Status and Observability (Priority: P4)

**Goal**: StyrminDeployment CRD exposes detailed phase-level status conditions visible via `kubectl describe`.

**Independent Test**: Create a StyrminDeployment, verify conditions appear for each phase. Introduce a failure, verify error appears in status.

### Tests for User Story 4

- [x] T026 [P] [US4] Write unit tests for status condition updates at each pipeline phase (verify conditions set correctly for success and failure) in tests/unit/operator/test_crd_status.py

### Implementation for User Story 4

- [x] T027 [US4] Status condition updates already integrated into handlers — set_condition() and set_phase() called after each phase in styrmin_deployment.py create/update/timer handlers
- [x] T028 [US4] Managed resource counts tracked via PhaseResult.resource_details and available for CRD status in handlers
- [x] T029 [US4] Error status reporting already integrated — phase set to Failed with condition False and error details on any phase failure in create/update/timer handlers

**Checkpoint**: `kubectl get sd` shows Phase column. `kubectl describe styrmindeployment` shows all conditions with timestamps. Failures are visible in status.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Formatting, backward compatibility verification, RBAC finalization

- [x] T030 Run `uv run invoke format lint` and fix any issues across all new and modified files
- [x] T031 [P] Backward compatibility ensured: existing HelmRelease-watching handlers from 001-k8s-operator remain active for pre-existing deployments. CRD-based flows are new parallel paths. No guard needed — both handler sets coexist.
- [x] T032 [P] docker-compose.yml already uses `styrmin agent start` which imports all handler modules including styrmin_deployment.py — CRD watching is automatic
- [ ] T033 Validate quickstart.md flow: deploy CRD, verify ordered creation, test drift, test deletion

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 — establishes pipeline and CRD handlers
- **US2 (Phase 4)**: Depends on US1 — needs CRD handlers to be in place before Prefect can create CRDs
- **US3 (Phase 5)**: Depends on US1 — extends the pipeline with drift detection and deletion
- **US4 (Phase 6)**: Depends on US1 — adds status reporting to the pipeline
- **Polish (Phase 7)**: Depends on all stories

### User Story Dependencies

- **US1 (P1)**: Foundation. Establishes the CRD handler and pipeline. Required by all other stories.
- **US2 (P2)**: Depends on US1. Refactors Prefect to create CRDs.
- **US3 (P3)**: Depends on US1. Can run in parallel with US2 (different files). Adds drift/deletion.
- **US4 (P4)**: Depends on US1. Can run in parallel with US2/US3. Adds status conditions.

### Parallel Opportunities

- **Phase 1**: T002, T003 in parallel
- **Phase 2**: T004, T005, T006 in parallel (different files)
- **Phase 3 (US1)**: T009, T010 tests in parallel; T011-T013 mostly sequential (building pipeline then handlers)
- **Phase 4 (US2)**: T017, T018, T019 can overlap (different functions in orchestration.py but sequential is safer)
- **Phase 5 (US3)**: T023, T024, T025 mostly sequential (same handler file)
- **Phase 6 (US4)**: T027, T028, T029 sequential (pipeline.py modifications)
- **Phase 7**: T031, T032 in parallel

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (CRD definition, modules)
2. Complete Phase 2: Foundational (models, helpers, constants)
3. Complete Phase 3: US1 (ordered pipeline, CRD handlers)
4. **STOP and VALIDATE**: Create a StyrminDeployment manually, verify ordered deployment
5. This alone proves the CRD + ordered deployment concept

### Incremental Delivery

1. Setup + Foundational → CRD deployed, models ready
2. US1 → Ordered deployment works from CRD → **MVP!**
3. US2 → Prefect creates CRDs → End-to-end workflow
4. US3 → Drift detection + ordered deletion → Production-ready reconciliation
5. US4 → Status conditions → Full observability

### Parallel Team Strategy

1. Team completes Setup + Foundational together
2. Once US1 pipeline is done:
   - Developer A: US2 (Prefect refactoring)
   - Developer B: US3 (drift detection + deletion)
   - Developer C: US4 (status conditions)

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story
- The operator module from 001-k8s-operator is the foundation — this feature extends it
- kopf sub-handler pattern provides idempotent phased execution for free
- `kopf.adopt()` sets owner references for garbage collection safety net
- Pre-existing deployments continue to work via the existing HelmRelease handlers
- Run `uv run invoke format lint` after each phase
