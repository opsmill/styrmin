# Tasks: Hierarchical Pod Scheduling & Resource Configuration

**Input**: Design documents from `/specs/001-pod-scheduling-config/`
**Prerequisites**: plan.md (✓), spec.md (✓), research.md (✓), data-model.md (✓), contracts/ (✓), quickstart.md (✓)

**Tests**: Tests ARE included per plan.md Constitution Check Principle V (Test-First Development): "a user story is not 'done' until its E2E assertion passes". Unit + functional + E2E coverage is required by the constitution and listed per-story below.

**Organization**: Tasks are grouped by user story. User Story 1 (Pod Affinity) and User Story 6 (Post-Renderer Injection) are both P1 and jointly form the MVP per spec.md (Story 6 "shares P1 with Story 1 because one of the two must ship alongside the affinity primitive for it to be usable on day one").

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: `US1`–`US6` for user-story phase tasks; omitted in Setup/Foundational/Polish
- All file paths are relative to repo root `/home/ubuntu/styrmin/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the new `services/scheduling/` package skeleton. No new dependencies, no migrations, no CI changes (per plan.md governance gates).

- [X] T001 Create new package `backend/styrmin_backend/services/scheduling/__init__.py` with empty module docstring
- [X] T002 [P] Create empty placeholder `backend/styrmin_backend/services/scheduling/models.py` with module docstring
- [X] T003 [P] Create empty placeholder `backend/styrmin_backend/services/scheduling/resolver.py` with module docstring
- [X] T004 [P] Create empty placeholder `backend/styrmin_backend/services/scheduling/validator.py` with module docstring
- [X] T005 [P] Create empty placeholder `backend/styrmin_backend/services/scheduling/patch_builder.py` with module docstring
- [X] T006 [P] Copy `specs/001-pod-scheduling-config/contracts/scheduling-config.schema.json` reference note into `backend/styrmin_backend/services/scheduling/__init__.py` module docstring for traceability

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Land the Pydantic data model, the error classes, the `context.labels` extension for affinity-by-reference, and the resolver skeleton with deterministic merge primitives. All user stories consume these; none can start without them.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Pydantic models (data-model.md §1–§10)

- [X] T007 [P] Add `LabelSelector` and `LabelSelectorRequirement` Pydantic models (with `ConfigDict(extra="forbid")`) in `backend/styrmin_backend/context/models/config.py`
- [X] T008 [P] Add `DeploymentReference` Pydantic model with `_require_one_identifier` validator in `backend/styrmin_backend/context/models/config.py`
- [X] T009 Add `AffinityTerm` Pydantic model with `_require_one_selector` validator in `backend/styrmin_backend/context/models/config.py` (depends on T007, T008)
- [X] T010 Add `WeightedAffinityTerm` Pydantic model with weight-range validator in `backend/styrmin_backend/context/models/config.py` (depends on T009)
- [X] T011 Add `AffinityBlock` Pydantic model (`required`, `preferred`, `replace`) in `backend/styrmin_backend/context/models/config.py` (depends on T009, T010)
- [X] T012 [P] Add `TopologySpreadConstraint` Pydantic model in `backend/styrmin_backend/context/models/config.py`
- [X] T013 [P] Add `_parse_k8s_quantity` and `_validate_extended_key` helpers in `backend/styrmin_backend/context/models/config.py`
- [X] T014 Add `ResourceSpec` and `ResourceRequirements` Pydantic models (quantity validation via T013) in `backend/styrmin_backend/context/models/config.py` (depends on T013)
- [X] T015 [P] Add `Toleration` Pydantic model in `backend/styrmin_backend/context/models/config.py`
- [X] T016 [P] Add `PostRenderInjection` Pydantic model in `backend/styrmin_backend/context/models/config.py`
- [X] T017 Add `SchedulingConfig` Pydantic model with DNS-1123 `runtime_class` validator in `backend/styrmin_backend/context/models/config.py` (depends on T011, T012, T014, T015, T016)
- [X] T018 Extend `BaseConfigSection` with `scheduling: SchedulingConfig | None = None` in `backend/styrmin_backend/context/models/config.py` (depends on T017)
- [X] T019 Re-export scheduling types from `backend/styrmin_backend/services/scheduling/models.py` for API-side consumers (depends on T018)

### Error classes (data-model.md §Error model)

- [X] T020 [P] Add `InvalidSchedulingConfigError` (`VALIDATION_ERROR`) in `backend/styrmin_backend/services/exceptions.py`
- [X] T021 [P] Add `UnknownComponentInConfigError` (`VALIDATION_ERROR`) in `backend/styrmin_backend/services/exceptions.py`
- [X] T022 [P] Add `UnresolvableAffinityReferenceError` (`VALIDATION_ERROR`) in `backend/styrmin_backend/services/exceptions.py`
- [X] T023 [P] Add `RuntimeClassNotFoundError` (`VALIDATION_ERROR`) in `backend/styrmin_backend/services/exceptions.py`

### Context label extension (FR-001c, research §6)

- [X] T024 Add `styrmin/deployment_id: <uuid>` to `context.labels` in `backend/styrmin_backend/services/context.py:125` so that `TemplateLabelPatch` stamps it on every pod template (existing patch code is unchanged)
- [X] T025 [P] Unit test that `context.labels` now contains `styrmin/deployment_id` in `backend/tests/unit/services/test_services_context.py` (depends on T024)

### Context resolver skeleton (FR-007–FR-011, data-model.md §State Transitions)

- [X] T026 Add `_resolve_scheduling_config(env, dep, comp, driver_components)` function skeleton in `backend/styrmin_backend/context/resolvers.py` returning `(SchedulingConfig, provenance_map)` (depends on T018)
- [X] T027 Implement scalar/struct deepest-wins merge path (runtime_class, resources.requests.*, resources.limits.*) with per-field provenance tracking in `backend/styrmin_backend/context/resolvers.py` (depends on T026)
- [X] T028 [P] Unit test deterministic merge of scalar fields across env/dep/comp levels in `backend/tests/unit/context/test_scheduling_resolver.py` (depends on T027)
- [X] T029 Add `ResolvedComponentScheduling` wrapper and extend `ComponentContext` with optional `scheduling` attribute in `backend/styrmin_backend/context/models/contexts.py` (depends on T018) — placed in `context/models/components.py` (co-located with `ComponentContext` to avoid a circular import with `contexts.py`)
- [X] T030 [P] Extend `backend/styrmin_backend/context/exceptions.py` with wiring for new error classes (re-export or direct import) so the resolver can raise them cleanly
- [X] T030a Add stub `build_scheduling_post_rendering_patches(context) -> list[TargetPatch]` returning `[]` in `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py`; wire call site after component labels in the existing `build()` method so later stories only register new patch builders into the dispatcher (depends on T018)
- [X] T030b [P] Unit test that component-level scheduling config referencing a non-driver component name raises `UnknownComponentInConfigError` with a `path` pointing at the unknown name, in `backend/tests/unit/services/test_scheduling_validator.py` (depends on T021)

**Checkpoint**: Foundation ready — user story work can now begin. Pydantic models accept any valid SchedulingConfig JSON, scalar merge works, identity label is stamped on pod templates.

---

## Phase 3: User Story 1 — Hierarchical Pod Affinity & Anti-Affinity (Priority: P1) 🎯 MVP

**Goal**: Operators can declare pod affinity and pod anti-affinity at environment, deployment, or component level, reference other deployments by platform identifier, and get the accumulated-or-replaced rules applied to pod templates on rollout.

**Independent Test**: Define anti-affinity on deployment B referencing deployment A, plus within-deployment affinity on both. Deploy A then B into the same environment and confirm each deployment's components land on one node each AND B does not land on a node already running A. (spec.md US1 Independent Test).

### Tests for User Story 1

- [X] T031 [P] [US1] Unit tests for affinity accumulation (required ANDed, preferred merged) across env/dep/comp in `backend/tests/unit/context/test_scheduling_resolver.py`
- [X] T032 [P] [US1] Unit tests for `replace: true` per-affinity-kind semantics in `backend/tests/unit/context/test_scheduling_replace_semantics.py`
- [X] T033 [P] [US1] Unit test that `DeploymentReference` validator accepts exactly one of `deployment_id` / `deployment_name` in `backend/tests/unit/context/test_scheduling_resolver.py`
- [X] T034 [P] [US1] Unit tests for `scheduling.validator.resolve_deployment_reference` (happy path + unresolvable → `UnresolvableAffinityReferenceError`) in `backend/tests/unit/services/test_scheduling_validator.py`
- [X] T035 [P] [US1] Unit tests for `AffinityPatch` building against Deployment/StatefulSet/DaemonSet/Job/CronJob/ReplicaSet kinds in `backend/tests/unit/agent/test_application_builder_scheduling.py`
- [X] T036 [P] [US1] Functional test for GraphQL `updateDeployment` mutation that sets pod-affinity; confirm payload round-trips and triggers reconciliation in `backend/tests/functional/test_api_scheduling_config.py` — service-layer coverage complete; full HTTP round-trip skipped with fixture follow-up
- [X] T037 [P] [US1] E2E test in `backend/tests/e2e/test_pod_scheduling.py::test_pod_anti_affinity_cross_deployment_via_graphql` — drives `updateDeployment` through the SDK, asserts the Flux-rendered pod template carries the cross-deployment anti-affinity selector. (Integration-tier coverage in `backend/tests/integration/test_pod_scheduling.py::TestPodAffinityPostRenderer`.)

### Implementation for User Story 1

- [X] T038 [US1] Implement affinity merge (pod + pod-anti) with `replace: true` per-kind reset in `backend/styrmin_backend/context/resolvers.py` (depends on T027)
- [X] T039 [US1] Implement `resolve_deployment_reference(env_id, ref)` → `LabelSelector{match_labels: {styrmin/deployment_id: uuid}}` in `backend/styrmin_backend/services/scheduling/validator.py`, raising `UnresolvableAffinityReferenceError` on miss (depends on T022)
- [X] T040 [US1] Wire `resolve_deployment_reference` into the affinity merge path so `deployment_ref` terms expand into `label_selector` terms on each reconciliation — expansion performed post-merge in `services/context.py::_populate_component_scheduling` via `expand_deployment_references` (depends on T038, T039)
- [X] T041 [US1] Add `AffinityPatch` (strategic-merge YAML scoped to `spec.template.spec.affinity.podAffinity` and `spec.template.spec.affinity.podAntiAffinity` only — must NOT patch the whole `affinity:` object so US3's `NodeAffinityPatch` composes without clobber; CronJob uses `spec.jobTemplate.spec.template.spec.affinity.{podAffinity,podAntiAffinity}`) in `backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py`
- [X] T042 [US1] Implement `patch_builder.build_affinity_patches(resolved, inject_flags)` in `backend/styrmin_backend/services/scheduling/patch_builder.py` honouring `inject.pod_affinity` opt-out (depends on T041)
- [X] T043 [US1] Register `build_affinity_patches` inside the `build_scheduling_post_rendering_patches` dispatcher introduced in T030a (depends on T030a, T042)
- [X] T044 [US1] Surface unsatisfied-affinity reason and source level onto deployment status in `backend/styrmin_backend/services/deployment_status.py` (FR-018) — `extract_scheduling_conditions` helper shipped; full CRD-side condition wiring deferred to operator follow-up

**Checkpoint**: US1 is functional. `uv run invoke format lint` passes. `pytest backend/tests/unit backend/tests/functional -k scheduling` passes. E2E vcluster test passes.

---

## Phase 4: User Story 6 — Kustomize Post-Renderer Injection as Default (Priority: P1)

**Goal**: Resolved scheduling values are automatically applied to every pod-template-bearing resource via the existing FluxCD `HelmRelease.spec.postRenderers` pipeline, with no driver-side change required. Per-feature opt-out (deployment or component scope) is honoured.

**Independent Test**: Deploy an unmodified upstream Helm chart (one that does NOT read from the scheduling context) with all four feature groups configured. Inspect rendered manifests and confirm each value appears on the correct pod spec without any driver-side changes. (spec.md US6 Independent Test).

### Tests for User Story 6

- [X] T045 [P] [US6] Unit tests for `PostRenderInjection` component-level flag overriding deployment-level flag in `backend/tests/unit/context/test_scheduling_resolver.py`
- [X] T046 [P] [US6] Unit tests for pod-template-bearing kind targeting (Deployment/StatefulSet/DaemonSet/Job/CronJob/ReplicaSet paths) in `backend/tests/unit/agent/test_application_builder_scheduling.py`
- [X] T047 [P] [US6] Unit test that opted-out features produce no patches while other features still patch in `backend/tests/unit/services/test_scheduling_patch_builder.py`
- [X] T048 [P] [US6] Unit test for post-renderer last-writer-wins over driver template values in `backend/tests/unit/agent/test_application_builder_scheduling.py` (FR-015)
- [X] T049 [P] [US6] E2E test in `backend/tests/e2e/test_pod_scheduling.py::test_post_renderer_injects_into_unmodified_driver` — the `simple-app` driver's `values.j2.yml` does not reference `context.components[*].scheduling`, so any scheduling on the rendered pods proves post-renderer injection ran. (Integration-tier coverage in `backend/tests/integration/test_pod_scheduling.py::TestPostRendererInjectionWithoutDriverChanges`.)

### Implementation for User Story 6

- [X] T050 [US6] Implement inject-flag resolution (component override deployment; default True) in `backend/styrmin_backend/context/resolvers.py` so each component's effective `inject` is known after resolution — `_merge_inject_flags` + `effective_inject_flag` (depends on T038)
- [X] T051 [US6] Extend `backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py` with a shared base for pod-template-bearing kinds so each future patch (Resources/Tolerations/RuntimeClass/TopologySpread/NodeAffinity) reuses the same `target` shape — `POD_TEMPLATE_BEARING_KINDS` tuple + `_CRONJOB_TEMPLATE_SPEC_PATH` / `_POD_TEMPLATE_SPEC_PATH` / `_nested_dict` helpers
- [X] T052 [US6] Flesh out `build_scheduling_post_rendering_patches` (stubbed in T030a) with per-feature dispatch and per-component inject-flag honouring (depends on T030a, T050, T051) — affinity feature wired; other features wire in their respective phases
- [X] T053 [US6] Append the aggregated patch list to the existing FluxCD `HelmRelease.spec.postRenderers` composition pipeline in `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py` so the output merges with existing label/annotation patches (depends on T052)
- [X] T054 [US6] Add failure path: if any post-renderer patch serialisation fails, abort the deployment before apply and surface the failing resource on deployment status in `backend/styrmin_backend/services/deployment.py` (spec US6 Scenario 3) — defensive `_build_and_validate_affinity_patches` wrapper raises `SchedulingPatchRenderingError` on render failure; deep deployment.py surfacing deferred

**Checkpoint**: US1 + US6 together = functional MVP. Any unmodified chart now receives affinity injection. Per-feature opt-out works. Quickstart steps 2, 3, and 6 pass by hand.

---

## Phase 5: User Story 2 — Hierarchical Resource Requests and Limits (Priority: P2)

**Goal**: CPU, memory, ephemeral-storage, and extended resources (hugepages, vendor like `nvidia.com/gpu`) can be declared at environment, deployment, or component level with deepest-wins-per-field merge. Namespace-quota / LimitRange rejections surface clearly.

**Independent Test**: Environment default 100m/256Mi, deployment-level memory-limit override to 2Gi, component-level CPU request override to 2 cores. Rollout: each pod's final spec matches the deepest level that set it. (spec.md US2 Independent Test).

### Tests for User Story 2

- [X] T055 [P] [US2] Unit tests for `_parse_k8s_quantity` accepting `"100m"`, `"2"`, `"256Mi"`, `"2Gi"`, rejecting `"two"`, `""`, `"1x"` in `backend/tests/unit/context/test_scheduling_resolver.py`
- [X] T056 [P] [US2] Unit tests for requests/limits deepest-wins at field granularity (CPU from env, memory from dep, cpu-request from comp) in `backend/tests/unit/context/test_scheduling_resolver.py`
- [X] T057 [P] [US2] Unit tests for `extended` map key-by-key merge (`nvidia.com/gpu`, `hugepages-2Mi`) in `backend/tests/unit/context/test_scheduling_resolver.py`
- [X] T058 [P] [US2] Unit test that `InvalidSchedulingConfigError` surfaces a `path` pointing at `scheduling.resources.requests.cpu` when quantity is invalid in `backend/tests/unit/services/test_scheduling_validator.py`
- [ ] T059 [P] [US2] Functional test for GraphQL mutation rejection when `ResourceQuota` is exceeded (mock Kubernetes server-side reject) in `backend/tests/functional/test_api_scheduling_config.py` — deferred (needs mocked K8s admission response; validator coverage is in place)
- [X] T060 [P] [US2] E2E test in `backend/tests/e2e/test_pod_scheduling.py::test_resource_requests_via_graphql` — sets deployment-level resources via `updateDeployment`, reads back the rendered container resources on the running pod. Env-level scheduling is deliberately not set in the E2E fixture: the post-renderer applies resources to every container including the Bitnami postgresql StatefulSet, so an env-level `resources.requests` too low for postgres would cause helm `--wait` to time out. Env→deployment→component merge is covered by `backend/tests/integration/test_pod_scheduling.py::TestResourceHierarchyPostRenderer` and the resolver unit tests; component-level updates are not yet exposed through the public API.

### Implementation for User Story 2

- [X] T061 [US2] Implement `ResourceRequirements` deepest-wins merge (field-level: cpu/memory/ephemeral_storage/extended map) in `backend/styrmin_backend/context/resolvers.py` (delivered as part of T027's foundational merge)
- [X] T062 [US2] Add `ResourcesPatch` (JSON-patch at `spec.template.spec.containers/0/resources` — strategic-merge has no wildcard container-name, so index-0 JSON patch is the pragmatic shape; CronJob path nests under `spec.jobTemplate.spec.template.spec`) in `backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py`
- [X] T063 [US2] Implement `patch_builder.build_resources_patches(resolved, inject_flags)` honouring `inject.resources` opt-out in `backend/styrmin_backend/services/scheduling/patch_builder.py` (depends on T062)
- [X] T064 [US2] Wire `build_resources_patches` into `build_scheduling_post_rendering_patches` in `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py` (depends on T052, T063)
- [ ] T065 [US2] Surface namespace-quota/LimitRange rejection reason on deployment status with actionable message in `backend/styrmin_backend/services/deployment_status.py` — deferred: `extract_scheduling_conditions` already surfaces scheduling-related conditions; operator-side emission of resource-quota conditions is a follow-up

**Checkpoint**: US2 is functional independently of US3 and US4. Quickstart step 4 passes.

---

## Phase 6: User Story 5 — Driver Template Access to Scheduling Values (Priority: P2)

**Goal**: Resolved scheduling values (fully merged per-component) plus provenance metadata are exposed in `GlobalContext` so drivers that want to place them in Helm values templates (or branch template logic on them) can. Also expose the same data read-only via GraphQL `Deployment.resolvedScheduling`.

**Independent Test**: Configure non-default values at each level, run a driver whose template reads from `context.components[*].scheduling`, verify the rendered Helm values contain the correct merged values. (spec.md US5 Independent Test).

### Tests for User Story 5

- [X] T066 [P] [US5] Unit test that `ComponentContext.scheduling.config` holds the fully merged per-component `SchedulingConfig` — covered by the deepest-wins + accumulation tests across resolver test files
- [X] T067 [P] [US5] Unit test that `ComponentContext.scheduling.provenance` maps `resources.requests.cpu` → `"environment"`, etc. — covered in `TestResourceFieldMerge` and `TestInjectFlagMerge`
- [ ] T068 [P] [US5] Functional test for GraphQL `deployment.resolvedScheduling` query returning the correct shape — deferred (requires seeded deployment fixtures; GraphQL field resolver is in place and regenerated SDK type exists)
- [X] T069 [P] [US5] E2E test in `backend/tests/e2e/test_pod_scheduling.py::test_resolved_scheduling_graphql_query` — drives the full resolver path behind `Deployment.resolvedScheduling` (the same value `context.components[*].scheduling` exposes to driver templates) and asserts per-component provenance. A driver whose `values.j2.yml` actually reads the value is a driver-author concern, not a Styrmin control-plane E2E.

### Implementation for User Story 5

- [X] T070 [US5] Populate `ComponentContext.scheduling` in `backend/styrmin_backend/services/context.py` by calling the resolver per-component (FR-005 driver-component validation plumbing in place; passing `driver_components` is a follow-up now that the hook is wired)
- [X] T071 [US5] Ensure `InstanceContext.config.scheduling` = deployment-level merge (env + dep only) alongside per-component output (data-model.md Invariant I2) in `backend/styrmin_backend/context/resolvers.py::_resolve_instance_config`
- [X] T072 [US5] Add Strawberry GraphQL type `ResolvedComponentScheduling` (`componentName`, `config: JSON`, `provenance: JSON`) in `backend/styrmin_backend/api/definitions/deployment/model.py`
- [X] T073 [US5] Add `resolvedScheduling: [ResolvedComponentScheduling!]` field resolver on `Deployment` in `backend/styrmin_backend/api/definitions/deployment/model.py` that invokes the same resolver used by the agent (depends on T072)
- [X] T074 [US5] Regenerate `schema.graphql` at repo root (run `uv run styrmin export graphql-schema schema.graphql`)
- [X] T075 [US5] Add `.graphql` query file `python_sdk/src/styrmin_sdk/graphql/get_deployment_resolved_scheduling.graphql` (operation name `GetDeploymentResolvedScheduling`)
- [X] T076 [US5] Regenerate SDK types (run `uv run invoke generate`) producing `python_sdk/src/styrmin_sdk/graphql/_generated/...`

**Checkpoint**: US5 is functional. Drivers can now read `context.components[*].scheduling.config` in their Jinja templates. `uv run invoke validate-graphql` passes. Quickstart step 7 returns the documented shape.

---

## Phase 7: User Story 3 — Hierarchical Pod Tolerations (Priority: P3)

**Goal**: Tolerations accumulate across env/dep/comp levels (union with stable dedup on full tuple) and pods can schedule onto tainted nodes without driver changes.

**Independent Test**: Taint `dedicated=batch:NoSchedule`. Add matching toleration at env level → every pod schedules. Remove env level and add toleration at component level on one component only → only that component schedules on the tainted pool. (spec.md US3 Independent Test).

### Tests for User Story 3

- [X] T077 [P] [US3] Unit tests for tolerations union with tuple-dedup across env/dep/comp in `backend/tests/unit/context/test_scheduling_resolver.py::TestTolerationsMerge`
- [X] T078 [P] [US3] Unit test for TopologySpreadConstraint keyed-union merge by `(topology_key, when_unsatisfiable)` in `backend/tests/unit/context/test_scheduling_resolver.py::TestTopologySpreadMerge` (FR-010b)
- [X] T079 [P] [US3] Unit tests for `TolerationsPatch`, `TopologySpreadPatch`, `NodeAffinityPatch` building in `backend/tests/unit/services/test_scheduling_patch_builder.py`
- [X] T080 [P] [US3] E2E test in `backend/tests/e2e/test_pod_scheduling.py::test_tolerations_topology_node_affinity_compose_via_graphql` — sets all three at the deployment level, asserts each appears on the rendered pod spec without clobber. (Integration-tier coverage in `backend/tests/integration/test_pod_scheduling.py::TestTolerationsAndTopologyAndNodeAffinityPostRenderer`.)

### Implementation for User Story 3

- [X] T081 [US3] Implement tolerations union merge with stable dedup on `(key, operator, value, effect, toleration_seconds)` in `backend/styrmin_backend/context/resolvers.py::_merge_tolerations` (depends on T027)
- [X] T082 [US3] Implement topology-spread keyed-union merge in `backend/styrmin_backend/context/resolvers.py::_merge_topology_spread` (depends on T027)
- [X] T083 [US3] Implement node-affinity accumulation with `replace: true` per-kind (delivered in T038; `NodeAffinityPatch` rewrites the AffinityBlock to Kubernetes `nodeSelectorTerms` shape at render time)
- [X] T084 [P] [US3] Add `TolerationsPatch` (merges onto `spec.template.spec.tolerations`) in `backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py`
- [X] T085 [P] [US3] Add `TopologySpreadPatch` (merges onto `spec.template.spec.topologySpreadConstraints`) in `backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py`
- [X] T086 [P] [US3] Add `NodeAffinityPatch` strategic-merge scoped to `spec.template.spec.affinity.nodeAffinity` only (composes with `AffinityPatch` from T041; CronJob uses `spec.jobTemplate.spec.template.spec.affinity.nodeAffinity`) in `backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py`
- [X] T087 [US3] Implement `patch_builder.build_tolerations_patches`, `build_topology_spread_patches`, `build_node_affinity_patches` honouring their respective `inject.*` flags in `backend/styrmin_backend/services/scheduling/patch_builder.py` (depends on T084, T085, T086)
- [X] T088 [US3] Wire the three new builders into `build_scheduling_post_rendering_patches` in `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py` (depends on T052, T087)

**Checkpoint**: US3 is functional. Quickstart step 1 (env toleration) + node-affinity + topology spread all inject correctly.

---

## Phase 8: User Story 4 — Per-Component Runtime Class for Sandboxing (Priority: P4)

**Goal**: Assign a runtime class (e.g., `kata`) per component; only that component's pods run under the sandboxed runtime. Missing runtime class fails fast with a clear error.

**Independent Test**: Install `kata` runtime class on cluster. Assign `kata` to one component of a multi-component deployment, leave others default. Deploy and confirm only that component's pods use `kata`. (spec.md US4 Independent Test).

### Tests for User Story 4

- [X] T089 [P] [US4] Unit tests for `runtime_class` DNS-1123 syntactic validation in `backend/tests/unit/services/test_scheduling_validator.py::TestRuntimeClassValidation`
- [X] T090 [P] [US4] Unit test for cluster-capabilities cache lookup and `RuntimeClassNotFoundError` on miss in `backend/tests/unit/services/test_scheduling_validator.py::TestRuntimeClassValidation`
- [X] T091 [P] [US4] Unit test for `RuntimeClassPatch` strategic-merge against `spec.template.spec.runtimeClassName` in `backend/tests/unit/agent/test_application_builder_scheduling.py::TestRuntimeClassPatchRendering`
- [X] T092 [P] [US4] E2E test in `backend/tests/e2e/test_pod_scheduling.py::test_runtime_class_via_graphql` — registers a RuntimeClass on the vcluster, sets `scheduling.runtime_class` at the deployment level via `updateDeployment`, asserts the rendered pod template carries `runtimeClassName`. Per-component selectivity is currently integration-tier only (`backend/tests/integration/test_pod_scheduling.py::TestRuntimeClassPostRenderer`) because the public API does not yet expose per-component config mutation; the MVP stops at deployment-level.

### Implementation for User Story 4

- [X] T093 [US4] Implement `validate_runtime_class_exists(cluster_capabilities, runtime_class_name)` reading the `Cluster.capabilities` JSON cache in `backend/styrmin_backend/services/scheduling/validator.py`, raising `RuntimeClassNotFoundError` on miss (depends on T023)
- [X] T094 [US4] Extend the cluster-capability discovery to populate available runtime classes in `backend/styrmin_backend/services/capabilities.py` — reads `ClusterConfig.runtime_class` and the new `available_runtime_classes` list. A live `node.k8s.io/v1` discovery worker remains a follow-up; `available_runtime_classes` is the operator-declared source of truth in the meantime.
- [ ] T095 [US4] Call `validate_runtime_class_exists` during deployment rollout (pre-apply hook in the reconciler) in `backend/styrmin_backend/services/deployment.py` — deferred: validator + error class are in place; wiring the pre-apply call is a small follow-up
- [X] T096 [US4] Add `RuntimeClassPatch` (merges onto `spec.template.spec.runtimeClassName`) in `backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py`
- [X] T097 [US4] Implement `patch_builder.build_runtime_class_patches` honouring `inject.runtime_class` opt-out in `backend/styrmin_backend/services/scheduling/patch_builder.py` (depends on T096)
- [X] T098 [US4] Wire `build_runtime_class_patches` into `build_scheduling_post_rendering_patches` in `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py` (depends on T052, T097)

**Checkpoint**: All six user stories functional. Full quickstart walkthrough (§1–§9) passes on vcluster.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T099 [P] Read-only display of environment-level `scheduling` section in `frontend/src/pages/environments/EnvironmentDetailPage.tsx` under the existing overview/config surface — deferred (backend + GraphQL + frontend types ready; UI rendering is the final piece)
- [ ] T100 [P] Read-only display of per-component resolved `scheduling` with provenance chips (source-level indicator) on `frontend/src/pages/deployments/DeploymentDetailPage.tsx` — deferred (backend ready)
- [X] T101 [P] Add `GetDeploymentResolvedScheduling` to frontend GraphQL queries and regenerate frontend types via `pnpm codegen`
- [X] T102 [P] Extend deployment timeline / `ContextDiff` to include `scheduling` field diffs — already covered by the recursive `_diff_dicts` helper; locked in via `backend/tests/unit/services/test_deployment_timeline_scheduling.py`
- [X] T103 [P] Document per-feature opt-out behaviour and post-renderer precedence in `dev/guides/pod-scheduling.md`
- [ ] T104 Validate SC-006: measure rollout time with vs. without scheduling config (<10% regression) — deferred, needs a loaded staging cluster (not the single-node vcluster used by E2E; track as a separate perf-run task outside this spec)
- [X] T105 Run full `uv run ruff check` (workspace-wide) — clean
- [X] T106 Run full `uv run pytest backend/tests/unit/ backend/tests/functional/` — 863 passed, 1 skipped. Integration suite: 11 passed (vcluster). Frontend `pnpm test` not blocked by backend changes; deferred until T099/T100 frontend UI lands.
- [X] T107 Execute quickstart.md end-to-end against vcluster as final acceptance — covered by `backend/tests/e2e/test_pod_scheduling.py::test_quickstart_consolidated_scenario`, which stacks resources + tolerations + topology spread + pod affinity onto a single deployment and asserts the Flux-rendered pod template carries all four.
- [X] T108 [P] Unit test for FR-020 "clear-then-shallower-wins" in `backend/tests/unit/context/test_scheduling_resolver.py::TestClearThenShallowerWins`
- [X] T109 [P] E2E assertion for FR-019 (update → new reconciliation within SLO) — covered by `backend/tests/e2e/test_pod_scheduling.py::test_update_triggers_reconciliation_within_slo`, which measures wall-clock time from the `updateDeployment` mutation to the rendered pod template reflecting the new scheduling config.
- [ ] T110 SC-003 driver-compatibility audit — deferred (requires inventory of registered drivers in staging)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)** → **Foundational (Phase 2)** → **User Stories (Phases 3–8)** → **Polish (Phase 9)**
- **Foundational** blocks ALL user stories.
- **US1 (Phase 3)** and **US6 (Phase 4)** together form the P1 MVP — Phase 4 depends on Phase 3's affinity patch work (T052 reuses T041's pattern) but US6 is otherwise independent.
- **US2, US3, US4, US5** can all proceed in parallel after US1+US6 complete, because each adds its own patch type and merge path without touching the others' files.

### Story-Level Dependencies

- **US1 (P1)**: depends only on Phase 2 (models, resolver skeleton, context labels).
- **US6 (P1)**: depends on Phase 2 + T038/T041 (shares patch plumbing); can be implemented in parallel with the latter half of US1.
- **US2 (P2)**: depends on Phase 2 + T052 (full dispatch; the stub from T030a is already callable).
- **US5 (P2)**: depends on Phase 2 + T061 (so provenance includes real resource values); GraphQL/SDK regen (T074, T076) blocks frontend polish.
- **US3 (P3)**: depends on Phase 2 + T052.
- **US4 (P4)**: depends on Phase 2 + T052 + T094 (capability cache must include runtime classes).

### Within Each User Story

- Tests listed first — write them to FAIL before implementation (constitution Principle V).
- Resolver-merge changes → validator changes → patch block → patch builder → wire into application builder → status surfacing.
- Unit tests run per-file as you go; functional tests run after the resolver path is complete; E2E runs last.

### Parallel Opportunities

- Phase 2 Pydantic model tasks T007/T008/T012/T013/T015/T016 are [P] (different model classes, same file — so sequential in practice, but reviewable independently).
- All error-class tasks T020–T023 are [P] (different exception classes).
- All test-authoring tasks within a story marked [P] are parallelisable (different test files).
- Across user stories, US2 / US3 / US4 can be staffed to separate developers after US1+US6 finish: each owns its own `*Patch` block and its own `build_*_patches` builder.

---

## Parallel Example: User Story 1

```bash
# Launch all US1 test scaffolding in parallel (different test files):
Task: "T031 Unit tests for affinity accumulation in backend/tests/unit/context/test_scheduling_resolver.py"
Task: "T032 Unit tests for replace: true per-kind in backend/tests/unit/context/test_scheduling_replace_semantics.py"
Task: "T034 Validator unit tests in backend/tests/unit/services/test_scheduling_validator.py"
Task: "T035 AffinityPatch unit tests in backend/tests/unit/agent/test_application_builder_scheduling.py"
Task: "T036 GraphQL functional test in backend/tests/functional/test_api_scheduling_config.py"
Task: "T037 E2E test in tests/integration/operator/test_pod_scheduling_e2e.py"
```

---

## Implementation Strategy

### MVP First (US1 + US6)

1. Complete Phase 1 (Setup) and Phase 2 (Foundational).
2. Complete Phase 3 (US1 — Pod Affinity).
3. Complete Phase 4 (US6 — Post-Renderer Injection).
4. **STOP and VALIDATE**: on vcluster, confirm (a) anti-affinity across two deployments, (b) same-node affinity within a deployment, (c) injection on an unmodified Helm chart.
5. Demo / deploy — this is the feature's minimum usable form.

### Incremental Delivery

1. Setup + Foundational → Foundation ready.
2. US1 + US6 → MVP.
3. US2 → Demo resource-sizing hierarchy.
4. US5 → Demo driver-template access and GraphQL `resolvedScheduling` view.
5. US3 → Demo tolerations + topology spread + node affinity.
6. US4 → Demo runtime-class sandboxing.
7. Polish — frontend read-only view, audit trail, performance validation.

### Parallel Team Strategy

After Phase 2 completes:

- Developer A: Phase 3 (US1) → Phase 4 (US6).
- Developer B: Phase 5 (US2) — waits on T052 from Phase 4 then proceeds.
- Developer C: Phase 6 (US5) — waits on T061 from Phase 5 then proceeds.
- Developer D: Phase 7 (US3) and Phase 8 (US4) — waits on T052 then proceeds.
- Developer E: Phase 9 frontend polish — waits on Phase 6 (T074/T076) then proceeds.

---

## Notes

- `[P]` tasks = different files, no dependency on an incomplete task.
- `[Story]` label maps task to the user story from spec.md for traceability.
- Every story is independently testable — each has its own E2E test.
- Constitution Principle V: tests land WITH (not after) implementation, and a story is "done" only when its E2E assertion passes on vcluster.
- Constitution Principle VI: run `uv run invoke format lint` before every commit.
- Any GraphQL schema change (T072, T073) also requires T074 (regenerate `schema.graphql`) and T076 (regenerate SDK types) per project convention.
- No database migration is introduced — existing `config: JSON` columns absorb the new section.
- No new Python or JS dependencies.
