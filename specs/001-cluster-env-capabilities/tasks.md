# Tasks: Cluster & Environment Capability Declarations

**Input**: Design documents from `/specs/001-cluster-env-capabilities/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Tests are included per Constitution Principle V (Test-First Development).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: New files and shared infrastructure for capability support

- [x] T001 [P] Create capability Pydantic models (Capabilities, StorageCapabilityDetail, IngressCapabilityDetail, BackupCapabilityDetail) in backend/styrmin_backend/context/models/capabilities.py
- [x] T002 [P] Create capability derivation service with compute_cluster_capabilities() and compute_environment_capabilities() in backend/styrmin_backend/services/capabilities.py
- [x] T003 Add capabilities JSON column to Cluster model in backend/styrmin_backend/db/models.py
- [x] T004 Add capabilities JSON column to Environment model in backend/styrmin_backend/db/models.py

**Checkpoint**: Capability models and derivation logic exist, DB columns ready

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Wire capability computation into existing create/update flows

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T005 Integrate capability computation into create_cluster() in backend/styrmin_backend/services/clusters.py — call compute_cluster_capabilities() and persist result to cluster.capabilities before commit
- [x] T006 Integrate capability computation into create_environment() in backend/styrmin_backend/services/environments.py — call compute_environment_capabilities() and persist result to environment.capabilities before commit
- [x] T007 Integrate capability recomputation into assign_backup_storage_location() in backend/styrmin_backend/services/backup_storage_locations.py — recompute environment capabilities when BSL is assigned
- [x] T008 Integrate capability recomputation into unassign_backup_storage_location() in backend/styrmin_backend/services/backup_storage_locations.py — recompute environment capabilities when BSL is unassigned

**Checkpoint**: Foundation ready — capabilities are computed and persisted on every relevant mutation

---

## Phase 3: User Story 1 — Query Cluster Capabilities (Priority: P1) 🎯 MVP

**Goal**: Operators can query a single field on a cluster to see all its capabilities via GraphQL

**Independent Test**: Query a cluster's `capabilities` field and verify it returns the correct hierarchical structure based on the cluster's config

### Tests for User Story 1

- [x] T009 [P] [US1] Unit test for compute_cluster_capabilities() — test storage derivation from standard_storage config in backend/tests/unit/test_capabilities.py
- [x] T010 [P] [US1] Unit test for compute_cluster_capabilities() — test ingress derivation from ingress_class + fqdn_suffix in backend/tests/unit/test_capabilities.py
- [x] T011 [P] [US1] Unit test for compute_cluster_capabilities() — test empty/null config returns None in backend/tests/unit/test_capabilities.py
- [ ] T012 [US1] Integration test for GraphQL cluster capabilities query in backend/tests/integration/test_capabilities_graphql.py

### Implementation for User Story 1

- [x] T013 [US1] Add capabilities resolver field to Cluster Strawberry type in backend/styrmin_backend/api/definitions/cluster/model.py — expose persisted capabilities as JSON scalar
- [x] T014 [US1] Regenerate GraphQL schema with `uv run styrmin export graphql-schema schema.graphql`
- [x] T015 [US1] Regenerate SDK types with `uv run invoke generate`

**Checkpoint**: Cluster capabilities queryable via GraphQL. Tests pass.

---

## Phase 4: User Story 2 — Query Environment Capabilities (Priority: P1)

**Goal**: Operators can query a single field on an environment to see its environment-scoped capabilities (own config + filtered cluster capabilities)

**Independent Test**: Query an environment's `capabilities` field and verify it returns environment-scoped capabilities including backup status and filtered storage

### Tests for User Story 2

- [x] T016 [P] [US2] Unit test for compute_environment_capabilities() — test backup derivation from backup_storage_location in backend/tests/unit/test_capabilities.py
- [x] T017 [P] [US2] Unit test for compute_environment_capabilities() — test environment-scoped storage (only env's own config, not full cluster) in backend/tests/unit/test_capabilities.py
- [x] T018 [P] [US2] Unit test for compute_environment_capabilities() — test ingress derivation scoped to environment config in backend/tests/unit/test_capabilities.py
- [ ] T019 [US2] Integration test for GraphQL environment capabilities query in backend/tests/integration/test_capabilities_graphql.py

### Implementation for User Story 2

- [x] T020 [US2] Add capabilities resolver field to Environment Strawberry type in backend/styrmin_backend/api/definitions/environment/model.py — expose persisted capabilities as JSON scalar
- [x] T021 [US2] Regenerate GraphQL schema with `uv run styrmin export graphql-schema schema.graphql`
- [x] T022 [US2] Regenerate SDK types with `uv run invoke generate`

**Checkpoint**: Environment capabilities queryable via GraphQL. Environment-scoped view verified. Tests pass.

---

## Phase 5: User Story 3 — Access Capabilities in Template Rendering Context (Priority: P1)

**Goal**: Application Driver templates can access cluster and environment capabilities via `{{ cluster.capabilities.* }}` and `{{ environment.capabilities.* }}`

**Independent Test**: Render a driver template that references capabilities and verify the output contains correct capability data; verify SilentUndefined handles missing categories gracefully

### Tests for User Story 3

- [x] T023 [P] [US3] Unit test for ClusterContext with capabilities field — verify model_dump includes capabilities in backend/tests/unit/test_capabilities.py
- [x] T024 [P] [US3] Unit test for EnvironmentContext with capabilities field — verify model_dump includes capabilities in backend/tests/unit/test_capabilities.py
- [ ] T025 [US3] Integration test for context generation — verify generate_context_from_deployment() populates capabilities from persisted data in backend/tests/integration/test_capabilities_context.py
- [ ] T026 [US3] Integration test for Jinja2 template rendering — verify `{{ cluster.capabilities.storage }}` renders correctly and missing categories produce empty output in backend/tests/integration/test_capabilities_context.py

### Implementation for User Story 3

- [x] T027 [US3] Add capabilities field (dict[str, Any], default_factory=dict) to ClusterContext in backend/styrmin_backend/context/models/contexts.py
- [x] T028 [US3] Add capabilities field (dict[str, Any], default_factory=dict) to EnvironmentContext in backend/styrmin_backend/context/models/contexts.py
- [x] T029 [US3] Update generate_context_from_deployment() in backend/styrmin_backend/services/context.py — populate cluster.capabilities and environment.capabilities from persisted DB values when building GlobalContext

**Checkpoint**: Capabilities accessible in Jinja2 templates. SilentUndefined handles missing categories. Tests pass.

---

## Phase 6: User Story 4 — Programmatic Capability Checks in Automation (Priority: P2)

**Goal**: Application Drivers can programmatically check capabilities before attempting operations, failing gracefully with clear messages when prerequisites are missing

**Independent Test**: Simulate an automation workflow that checks for backup capability before proceeding, verify it correctly identifies missing prerequisites

### Tests for User Story 4

- [ ] T030 [US4] Integration test for capability-based prerequisite check — verify automation can query capabilities and determine if required capability exists in backend/tests/integration/test_capabilities_graphql.py

### Implementation for User Story 4

No additional implementation needed — US4 is satisfied by the combination of:
- GraphQL query from US1/US2 (query capabilities)
- Context access from US3 (check in templates)

Task T030 validates the end-to-end automation workflow using existing infrastructure.

**Checkpoint**: Automation can verify prerequisites via capability queries. Tests pass.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [x] T031 Run `uv run invoke format lint` to verify all code passes formatting and linting
- [x] T032 Run `uv run invoke test` to verify all existing tests still pass (no regressions)
- [x] T033 Validate quickstart.md examples match actual implementation — verify GraphQL queries and template examples work as documented

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on T001, T002, T003, T004 — BLOCKS all user stories
- **User Stories (Phase 3-6)**: All depend on Foundational phase completion
  - US1 and US2 can proceed in parallel (different GraphQL types, different files)
  - US3 depends on US1 and US2 (needs capabilities persisted to populate context)
  - US4 depends on US1, US2, and US3 (validates end-to-end workflow)
- **Polish (Phase 7)**: Depends on all user stories being complete

### User Story Dependencies

- **US1 (P1)**: Can start after Foundational — no dependencies on other stories
- **US2 (P1)**: Can start after Foundational — no dependencies on other stories
- **US3 (P1)**: Depends on US1 and US2 (capabilities must be queryable before adding to context)
- **US4 (P2)**: Depends on US1, US2, US3 (validates full workflow)

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Models/schema before services
- Services before endpoints/resolvers
- Schema regeneration after GraphQL changes

### Parallel Opportunities

- T001 and T002 can run in parallel (new files, no conflicts)
- T003 and T004 can run in parallel (different sections of same file — but safer sequential)
- T009, T010, T011 can run in parallel (same test file, different test functions)
- T016, T017, T018 can run in parallel (same test file, different test functions)
- T023 and T024 can run in parallel (same test file, different test functions)
- US1 and US2 can be worked on in parallel after Foundational phase

---

## Parallel Example: User Story 1

```text
# Launch all unit tests for US1 together:
Task: T009 "Unit test for storage derivation in backend/tests/unit/test_capabilities.py"
Task: T010 "Unit test for ingress derivation in backend/tests/unit/test_capabilities.py"
Task: T011 "Unit test for empty config in backend/tests/unit/test_capabilities.py"

# After tests written, implement GraphQL resolver:
Task: T013 "Add capabilities resolver to Cluster type"
```

## Parallel Example: US1 + US2 in Parallel

```text
# Developer A (US1):
Task: T013 "Add capabilities resolver to Cluster type"

# Developer B (US2):
Task: T020 "Add capabilities resolver to Environment type"

# Then combine schema regeneration:
Task: T014/T021 "Regenerate GraphQL schema (once, covering both changes)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T004)
2. Complete Phase 2: Foundational (T005-T008)
3. Complete Phase 3: User Story 1 (T009-T015)
4. **STOP and VALIDATE**: Query cluster capabilities via GraphQL
5. Deploy/demo if ready

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add US1 → Test cluster capabilities → Deploy/Demo (MVP!)
3. Add US2 → Test environment capabilities → Deploy/Demo
4. Add US3 → Test template rendering → Deploy/Demo
5. Add US4 → Validate automation workflow → Deploy/Demo
6. Each story adds value without breaking previous stories

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: US1 (Cluster GraphQL)
   - Developer B: US2 (Environment GraphQL)
3. After US1 + US2 complete:
   - Developer A: US3 (Context integration)
   - Developer B: US4 (Automation validation)
4. Stories complete and integrate independently

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify tests fail before implementing
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Schema regeneration (T014/T015, T021/T022) should be combined if US1 and US2 are done in sequence
