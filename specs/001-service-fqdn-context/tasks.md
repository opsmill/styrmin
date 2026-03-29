# Tasks: Include Service FQDNs in Deployment Context

**Input**: Design documents from `/specs/001-service-fqdn-context/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/deployed-service.graphql, quickstart.md
**Tests**: Required (constitution principle V: Test-First Development)

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: No setup tasks needed — this is an existing project with established structure. All new work builds on existing files and conventions.

**Skipped**: Proceed to Phase 2.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Extract shared FQDN computation utilities and establish the single source of truth for DNS sanitization and FQDN assembly. All three user stories depend on this module.

**CRITICAL**: No user story work can begin until this phase is complete.

- [x] T001 Write unit tests for DNS sanitization and FQDN computation (edge cases: special chars, length truncation, empty string, None suffix, valid suffix) in `backend/tests/unit/context/test_fqdn.py`
- [x] T002 Create FQDN utility module with `to_fqdn_label`, `compute_primary_fqdn`, and `compute_human_readable_fqdn` functions in `backend/styrmin_backend/context/fqdn.py`
- [x] T003 Update `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py` to import `to_fqdn_label` from `styrmin_backend.context.fqdn` instead of defining it locally

**Checkpoint**: Foundation ready — all three FQDN utility functions exist, tests pass, existing builder still works via import redirect. User story implementation can now begin.

---

## Phase 3: User Story 1 — View Service Access Addresses in the UI (Priority: P1)

**Goal**: Expose FQDN data through the GraphQL API and display service access addresses in the deployment detail page so users can find URLs without inspecting driver templates.

**Independent Test**: Deploy a service with `fqdn_suffix` configured, query `deployedServices` via GraphQL, verify `primaryFqdn` and `humanReadableFqdn` are returned. Open deployment detail page and confirm both FQDNs are displayed per service.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T004 [US1] Write unit tests for `DeployedService` FQDN resolver fields (with/without suffix, sanitization) in `backend/tests/unit/api/definitions/service/test_deployed_service_fqdn.py`

### Implementation for User Story 1

- [x] T005 [US1] Add `primary_fqdn: str | None` and `human_readable_fqdn: str | None` private attributes and Strawberry resolver fields (`primaryFqdn`, `humanReadableFqdn`) to `DeployedService` type in `backend/styrmin_backend/api/definitions/service/model.py`
- [x] T006 [US1] Implement FQDN computation in the `Deployment.deployed_services()` resolver: load environment + cluster, resolve config hierarchy for `fqdn_suffix`, get app name from driver version, compute FQDNs, inject into `DeployedService` instances in `backend/styrmin_backend/api/definitions/deployment/model.py`
- [x] T007 [US1] Regenerate GraphQL schema and SDK types: run `uv run styrmin export graphql-schema schema.graphql` then `uv run invoke generate`
- [x] T008 [US1] Update deployment detail query to include `primaryFqdn` and `humanReadableFqdn` fields, and add a "Services" card section displaying each service's name, FQDNs (with "Not configured" fallback), port, and kind in `frontend/src/pages/deployments/DeploymentDetailPage.tsx`

**Checkpoint**: Users can view service FQDNs in the deployment detail page. API returns FQDN data for all deployed services.

---

## Phase 4: User Story 2 — Centralized FQDN Computation in Deployment Context (Priority: P2)

**Goal**: Pre-compute FQDNs as first-class fields on the service context model so driver templates can reference them directly without inline FQDN construction.

**Independent Test**: Generate a deployment context for a deployment with configured `fqdn_suffix`, verify each `ServiceReference` in the context has correct `primary_fqdn` and `human_readable_fqdn` values. Verify `None` when suffix is unconfigured.

### Tests for User Story 2

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T009 [US2] Write unit tests for context generation FQDN population (with/without suffix, multiple services, missing config) in `backend/tests/unit/services/test_context_fqdn.py`

### Implementation for User Story 2

- [x] T010 [US2] Add `primary_fqdn: str | None = None` and `human_readable_fqdn: str | None = None` fields to `ServiceReference` model in `backend/styrmin_backend/context/models/services.py`
- [x] T011 [US2] Compute and populate FQDNs for each `ServiceReference` during context generation using `fqdn_suffix` from `ResolvedConfig`, `app.name`, `deployment_id`, and `environment.name` in `backend/styrmin_backend/services/context.py`

**Checkpoint**: Deployment context includes FQDN fields for all services. Driver templates can now reference `{{ services.<name>.primary_fqdn }}` and `{{ services.<name>.human_readable_fqdn }}`.

---

## Phase 5: User Story 3 — Simplified Driver Templates (Priority: P3)

**Goal**: Migrate all existing example driver templates to use pre-computed FQDN context fields instead of inline Jinja2 FQDN construction, eliminating duplicated logic and ensuring consistency.

**Independent Test**: Deploy each example driver and verify rendered FQDN values are identical to pre-migration output. Confirm no driver templates contain inline `fqdn_suffix` concatenation patterns.

**Dependency**: Requires Phase 4 (US2) completion — drivers reference context fields populated by context generation.

### Implementation for User Story 3

- [x] T012 [P] [US3] Replace inline FQDN construction with `{{ services.infrahub.primary_fqdn }}` and `{{ services.infrahub.human_readable_fqdn }}` in `driver/examples/infrahub/chart_values.j2.yaml`
- [x] T013 [P] [US3] Replace inline FQDN construction with `{{ services.semaphore.primary_fqdn }}` and `{{ services.semaphore.human_readable_fqdn }}` in `driver/examples/semaphore/chart_values.j2.yaml`
- [x] T014 [P] [US3] Replace inline primary FQDN construction with `{{ services.<name>.primary_fqdn }}` in `driver/examples/simple-app/chart_values.j2.yaml`
- [x] T015 [P] [US3] Replace inline primary FQDN construction with `{{ services.<name>.primary_fqdn }}` in `driver/examples/slurpit/chart_values.j2.yaml`

**Checkpoint**: All example drivers use pre-computed FQDN context fields. Zero inline FQDN construction patterns remain (SC-002). The `to_fqdn_label` Jinja2 filter remains available for non-FQDN usage (FR-008).

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation across all user stories

- [x] T016 [P] Run `uv run invoke format lint` and fix any issues
- [x] T017 Validate implementation against quickstart.md scenarios and run full test suite with `uv run invoke test`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Skipped — existing project
- **Foundational (Phase 2)**: No dependencies — start immediately. BLOCKS all user stories.
- **US1 (Phase 3)**: Depends on Phase 2 only. Independent of US2 and US3.
- **US2 (Phase 4)**: Depends on Phase 2 only. Independent of US1.
- **US3 (Phase 5)**: Depends on Phase 2 AND Phase 4 (US2) — drivers reference context fields.
- **Polish (Phase 6)**: Depends on all user stories being complete.

### User Story Dependencies

```text
Phase 2: Foundational
    ├── Phase 3: US1 (API + Frontend) — independent
    ├── Phase 4: US2 (Context Model) — independent
    │       └── Phase 5: US3 (Driver Migration) — depends on US2
    └── Phase 6: Polish — after all stories
```

- **US1 (P1)**: Can start after Phase 2. No dependency on US2 or US3 (API resolver uses shared utility directly).
- **US2 (P2)**: Can start after Phase 2. No dependency on US1 (context model is independent of API layer).
- **US3 (P3)**: Requires Phase 4 (US2) completion (driver templates reference context fields populated by context generation).

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Model/type changes before service/resolver logic
- Backend before frontend (US1)
- Schema regeneration after type changes, before frontend work (US1)

### Parallel Opportunities

- **Phase 2**: T001 → T002 → T003 (sequential — test-first, then implementation, then import update)
- **Phase 3 (US1)** and **Phase 4 (US2)**: Can run in parallel after Phase 2 (different layers, different files)
- **Phase 5 (US3)**: T012, T013, T014, T015 all [P] — four independent driver files
- **Phase 6**: T016 and T017 can overlap

---

## Parallel Example: US1 + US2 After Foundation

```text
# After Phase 2 completes, launch both stories in parallel:

# Stream A: US1 (API + Frontend)
Task T004: "Write FQDN resolver tests"
Task T005: "Add FQDN fields to DeployedService type"
Task T006: "Implement FQDN computation in Deployment resolver"
Task T007: "Regenerate GraphQL schema and SDK types"
Task T008: "Update frontend deployment detail page"

# Stream B: US2 (Context Model)
Task T009: "Write context FQDN population tests"
Task T010: "Add FQDN fields to ServiceReference model"
Task T011: "Compute FQDNs during context generation"

# After both complete → Phase 5: US3 (all 4 drivers in parallel)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 2: Foundational (extract utilities + tests)
2. Complete Phase 3: User Story 1 (API + frontend)
3. **STOP and VALIDATE**: FQDNs visible in UI for deployed services
4. Deploy/demo if ready — users can immediately see service addresses

### Incremental Delivery

1. Phase 2: Foundation ready
2. Phase 3: US1 (API + Frontend) → Users see FQDNs in UI (MVP!)
3. Phase 4: US2 (Context Model) → Drivers have FQDN context fields available
4. Phase 5: US3 (Driver Migration) → All drivers simplified, zero inline FQDN construction
5. Phase 6: Polish → Format, lint, final validation
6. Each phase adds value without breaking previous phases

### Parallel Strategy

With two streams available:
1. Complete Phase 2 together
2. Stream A: US1 (API + Frontend) | Stream B: US2 (Context Model)
3. After both complete: US3 (all 4 drivers in parallel)
4. Polish

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- [Story] label maps task to specific user story for traceability
- Constitution requires test-first development — tests precede implementation in each phase
- FQDNs are computed at runtime, not stored — no database migration needed
- GraphQL schema must be regenerated after type changes (T007)
- `to_fqdn_label` Jinja2 filter must remain available after extraction (FR-008)
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
