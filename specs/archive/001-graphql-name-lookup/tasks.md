# Tasks: Name-Based Resource Lookup

**Input**: Design documents from `/specs/001-graphql-name-lookup/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Included per Constitution V (Test-First Development).

**Organization**: Tasks are grouped by user story. US4 (per-cluster uniqueness) is delivered as part of the Foundational phase since it's a prerequisite for environment name-based lookup.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Foundational (Blocking Prerequisites)

**Purpose**: Core changes that MUST be complete before any user story can be implemented. Delivers US4 (per-cluster environment uniqueness) as a side effect.

- [x] T001 [P] Add AmbiguousIdentifierError exception (error_code VALIDATION_ERROR) to backend/styrmin_backend/services/exceptions.py
- [x] T002 [P] Change Environment model: replace `Field(unique=True)` on name with `UniqueConstraint("name", "cluster_id")` via `__table_args__` in backend/styrmin_backend/db/models.py
- [x] T003 [P] Add `get_by_name_in_cluster(name: str, cluster_id: UUID) -> Environment | None` method to EnvironmentRepository (abstract + SQLModel implementation) in backend/styrmin_backend/repository/environment.py
- [x] T004 Update create_environment service to use `get_by_name_in_cluster` for per-cluster uniqueness check instead of global `get_by_name` in backend/styrmin_backend/services/environments.py
- [x] T005 Add `resolve_cluster(uow, cluster_id, cluster_name)` helper that validates mutual exclusivity and resolves by ID or name in backend/styrmin_backend/services/clusters.py
- [x] T006 Add `resolve_environment(uow, environment_id, environment_name, cluster_id, cluster_name)` helper that resolves cluster first if needed, then environment in backend/styrmin_backend/services/environments.py

**Checkpoint**: Foundation ready. Per-cluster environment uniqueness (US4) is now enforced. User story implementation can begin.

---

## Phase 2: US1 + US5 - Cluster Name Lookup (Priority: P1) MVP

**Goal**: API consumers and CLI users can query and delete clusters by name instead of UUID.

**Independent Test**: Query a cluster by name via GraphQL and via `styrminctl clusters get <name>`. Both return correct cluster details.

### Backend API (US1)

- [x] T007 [P] [US1] Update `cluster` query to accept optional `cluster_name: str | None = None`, call resolve_cluster in backend/styrmin_backend/api/schema/query.py
- [x] T008 [P] [US1] Update `delete_cluster` mutation to accept optional `cluster_name: str | None = None`, call resolve_cluster in backend/styrmin_backend/api/schema/mutation.py

### Schema & SDK (US1)

- [x] T009 [US1] Regenerate schema.graphql: `uv run styrmin export graphql-schema schema.graphql`
- [x] T010 [US1] Update get_cluster.graphql and delete_cluster.graphql to add optional `$clusterName: String` variable in python_sdk/src/styrmin_sdk/graphql/
- [x] T011 [US1] Regenerate SDK types: `uv run invoke generate`
- [x] T012 [US1] Update ClusterResource.get() and .delete() to accept optional cluster_name param, build variables dict conditionally in python_sdk/src/styrmin_sdk/resources/clusters.py

### CLI (US5)

- [x] T013 [US5] Add ClusterName type alias (str positional) and optional ResourceId type (--id flag with UUID validation) to cli/src/styrminctl/types.py
- [x] T014 [US5] Update clusters get and delete commands: name as default positional arg, --id flag for UUID fallback, validate mutual exclusivity in cli/src/styrminctl/commands/clusters.py

### Tests (US1 + US5)

- [ ] T015 [US1] [US5] Write tests for cluster name-based query, delete, validation errors (both/neither provided), and CLI name/--id parameter handling

**Checkpoint**: Cluster name lookup works end-to-end (API + SDK + CLI). MVP deliverable.

---

## Phase 3: US2 + US4 + US6 - Environment Name Lookup + Scoped Uniqueness (Priority: P2)

**Goal**: API consumers and CLI users can query and delete environments by name (with cluster context). Same environment name can exist in different clusters.

**Independent Test**: Create environments named "staging" in two different clusters. Query each by name with cluster context via GraphQL and `styrminctl environments get staging --cluster <name>`.

### Backend API (US2)

- [x] T016 [P] [US2] Update `environment` query to accept optional `environment_name`, `cluster_id`, `cluster_name` params, call resolve_environment in backend/styrmin_backend/api/schema/query.py
- [x] T017 [P] [US2] Update `delete_environment` mutation to accept optional `environment_name`, `cluster_id`, `cluster_name` params, call resolve_environment in backend/styrmin_backend/api/schema/mutation.py

### Schema & SDK (US2)

- [x] T018 [US2] Regenerate schema.graphql: `uv run styrmin export graphql-schema schema.graphql`
- [x] T019 [US2] Update get_environment.graphql and delete_environment.graphql to add optional name + cluster variables in python_sdk/src/styrmin_sdk/graphql/
- [x] T020 [US2] Regenerate SDK types: `uv run invoke generate`
- [x] T021 [US2] Update EnvironmentResource.get() and .delete() to accept optional environment_name + cluster_id/cluster_name params in python_sdk/src/styrmin_sdk/resources/environments.py

### CLI (US6)

- [x] T022 [US6] Add EnvironmentName type alias, --cluster flag (default "default"), and --cluster-id flag (UUID validated) to cli/src/styrminctl/types.py
- [x] T023 [US6] Update environments get, delete, and create commands: name as positional, --cluster/--cluster-id flags, validate mutual exclusivity in cli/src/styrminctl/commands/environments.py
- [x] T024 [US6] Update backup-locations assign and unassign commands: environment name as positional with --cluster/--cluster-id flags in cli/src/styrminctl/commands/backup_storage_locations.py

### Tests (US2 + US4 + US6)

- [ ] T025 [US2] [US4] [US6] Write tests for environment name-based query/delete with cluster context, per-cluster uniqueness (duplicate names across clusters), validation errors, and CLI parameter handling

**Checkpoint**: Environment name lookup and scoped uniqueness work end-to-end. US1, US2, US4, US5, US6 all independently functional.

---

## Phase 4: US3 - Create and Deploy Using Names (Priority: P3)

**Goal**: API consumers and CLI users can create environments and deploy using cluster/environment names instead of UUIDs.

**Independent Test**: Create an environment using cluster name via GraphQL. Deploy to that environment using environment name + cluster name.

### Backend API (US3)

- [x] T026 [US3] Update `create_environment` mutation to accept optional `cluster_name` param (alongside existing `cluster_id`), call resolve_cluster in backend/styrmin_backend/api/schema/mutation.py
- [x] T027 [US3] Update `deploy` mutation to accept optional `environment_name`, `cluster_id`, `cluster_name` params, call resolve_environment in backend/styrmin_backend/api/schema/mutation.py
- [x] T028 [US3] Update deploy_application service to accept optional environment_name + cluster context params, resolve environment before proceeding in backend/styrmin_backend/services/deployment.py

### Schema & SDK (US3)

- [x] T029 [US3] Regenerate schema.graphql: `uv run styrmin export graphql-schema schema.graphql`
- [x] T030 [US3] Update create_environment.graphql and deploy.graphql to add optional name variables in python_sdk/src/styrmin_sdk/graphql/
- [x] T031 [US3] Regenerate SDK types: `uv run invoke generate`
- [x] T032 [P] [US3] Update EnvironmentResource.create() to accept optional cluster_name param in python_sdk/src/styrmin_sdk/resources/environments.py
- [x] T033 [P] [US3] Update DeploymentResource.create() to accept optional environment_name + cluster params in python_sdk/src/styrmin_sdk/resources/deployments.py

### CLI (US3)

- [x] T034 [US3] Update deployments create command: environment name as positional with --cluster/--cluster-id flags in cli/src/styrminctl/commands/deployments.py

### Tests (US3)

- [ ] T035 [US3] Write tests for name-based create_environment (cluster by name), deploy (environment by name), and CLI deployments create parameter handling

**Checkpoint**: All user stories complete. Full name-based workflow works end-to-end.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Final validation across all stories

- [x] T036 Run format and lint: `uv run invoke format lint`
- [x] T037 Run full test suite: `uv run invoke test`
- [x] T038 Run GraphQL query validation: `uv run invoke validate-graphql`
- [x] T039 Verify backward compatibility: confirm all existing UUID-based operations still work unchanged

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 1)**: No dependencies - start immediately. BLOCKS all user stories.
- **US1 + US5 (Phase 2)**: Depends on Foundational. Can start immediately after.
- **US2 + US4 + US6 (Phase 3)**: Depends on Foundational. Can start after Phase 2 (shares query.py/mutation.py).
- **US3 (Phase 4)**: Depends on Foundational. Can start after Phase 3 (shares mutation.py and SDK files).
- **Polish (Phase 5)**: Depends on all desired user story phases being complete.

### User Story Dependencies

- **US1 (Cluster API)**: Foundational only. No cross-story dependencies.
- **US5 (Cluster CLI)**: Depends on US1 (needs SDK changes). Combined in same phase.
- **US4 (Per-cluster uniqueness)**: Delivered in Foundational phase. No story dependencies.
- **US2 (Environment API)**: Foundational only. No cross-story dependencies.
- **US6 (Environment CLI)**: Depends on US2 (needs SDK changes). Combined in same phase.
- **US3 (Create/Deploy)**: Foundational only. Uses same resolver helpers.

### Within Each Phase

- Backend API changes before schema regeneration
- Schema regeneration before SDK .graphql file updates
- SDK .graphql updates before SDK type regeneration
- SDK type regeneration before SDK resource class updates
- SDK updates before CLI updates
- Tests after implementation

### Parallel Opportunities

- **Phase 1**: T001, T002, T003 can all run in parallel (different files)
- **Phase 2**: T007, T008 can run in parallel (query.py vs mutation.py)
- **Phase 3**: T016, T017 can run in parallel (query.py vs mutation.py)
- **Phase 4**: T032, T033 can run in parallel (different SDK resource files)
- **Cross-phase**: Phases 2-4 are sequential due to shared files (query.py, mutation.py, types.py)

---

## Parallel Example: Phase 1 (Foundational)

```text
# Launch T001, T002, T003 in parallel (different files):
Task T001: "Add AmbiguousIdentifierError to backend/styrmin_backend/services/exceptions.py"
Task T002: "Change Environment uniqueness constraint in backend/styrmin_backend/db/models.py"
Task T003: "Add get_by_name_in_cluster to backend/styrmin_backend/repository/environment.py"

# Then sequentially:
Task T004: depends on T003
Task T005: depends on T001
Task T006: depends on T001, T003, T005
```

## Parallel Example: Phase 2 (US1 + US5)

```text
# Launch T007, T008 in parallel (query.py vs mutation.py):
Task T007: "Update cluster query in query.py"
Task T008: "Update delete_cluster mutation in mutation.py"

# Then sequential pipeline:
T009 (regen schema) → T010 (SDK .graphql) → T011 (regen types) → T012 (SDK resource) → T013 (CLI types) → T014 (CLI commands) → T015 (tests)
```

---

## Implementation Strategy

### MVP First (Phase 1 + Phase 2 Only)

1. Complete Phase 1: Foundational (6 tasks)
2. Complete Phase 2: US1 + US5 - Cluster Name Lookup (9 tasks)
3. **STOP and VALIDATE**: Test cluster name lookup end-to-end via API and CLI
4. Total: 15 tasks for MVP

### Incremental Delivery

1. Phase 1 (Foundational) + Phase 2 (US1+US5) → Cluster name lookup works (MVP)
2. Add Phase 3 (US2+US4+US6) → Environment name lookup + scoped uniqueness works
3. Add Phase 4 (US3) → Full name-based create/deploy workflow works
4. Phase 5 (Polish) → Final validation
5. Each phase adds value without breaking previous phases

---

## Notes

- Schema regeneration (`uv run styrmin export graphql-schema schema.graphql`) and SDK type regeneration (`uv run invoke generate`) appear in each phase. If executing phases back-to-back, intermediate regenerations can be skipped -- only the final one matters.
- The `--cluster` flag defaults to "default" on all environment-related CLI commands, meaning single-cluster users never need to specify it.
- US4 (per-cluster uniqueness) has no dedicated phase because its implementation IS the foundational model/repository/service changes in Phase 1.
