# Tasks: Deployment Env Vars (Free-Form, Post-Render Injected)

**Input**: Design documents from `/specs/008-deployment-env-vars/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/graphql.md, quickstart.md

**Tests**: Tests are **mandatory** for this feature per Constitution §V (Test-First Development) and `AGENTS.md` (E2E + GraphQL propagation tests are non-negotiable).

**Organization**: Tasks are grouped by user story so each story can be implemented and shipped as an independent MVP increment. P1 stories together form the genuine MVP (US1+US2+US3 — the three-scope hierarchy).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no incomplete dependencies)
- **[Story]**: Which user story this task belongs to (US1..US7)
- File paths are absolute-from-repo-root and exact

## Path Conventions

This is a **web service** project (backend = Python; frontend = React, untouched in v1). Backend code lives under `backend/styrmin_backend/`; backend tests under `backend/tests/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the new package skeletons and shared exception types that every later phase depends on. No business logic yet.

- [X] T001 Create new package skeleton at `backend/styrmin_backend/services/env_vars/` with empty `__init__.py`, `validator.py`, `resolver.py`, `patch_builder.py`, `exceptions.py` files (one stub class/function each so the imports work).
- [X] T002 [P] Create new module `backend/styrmin_backend/services/driver/models/resources/env_vars.py` with empty `DriverEnvVarLevel` enum and `DriverEnvVarDoc` class stubs (no validators yet).
- [X] T003 [P] Add empty test directories `backend/tests/unit/services/env_vars/` and `backend/tests/unit/services/driver/` (create `__init__.py` files only).
- [X] T004 [P] Create empty E2E test file `backend/tests/e2e/test_deployment_env_vars.py` with a single placeholder `@pytest.mark.api_only` decorator and a passing stub test, so the file is wired into pytest collection.

**Checkpoint**: `uv run pytest -q backend/tests/` collects the new paths without errors.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Pydantic config-model additions, the env-var validator, and the new exception types. **Every user story** consumes these. No story can be implemented before this phase is complete.

- [X] T005 Define exception types in `backend/styrmin_backend/services/env_vars/exceptions.py`: `InvalidEnvVarNameError`, `DuplicateEnvVarNameError`, `EnvVarSizeLimitExceededError`, `UnknownComponentEnvVarError` — all subclasses of `ServiceError` with `error_code` and `default_message` per Constitution §IV. Match the codes in `data-model.md` §7.
- [X] T006 Wire the new error codes into `backend/styrmin_backend/api/schema/errors.py` so `StructuredErrorExtension` projects them onto `extensions.code`.
- [X] T007 Implement env var name regex constant `_ENV_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")` and risky-name regex `_RISKY_ENV_VAR_NAME_RE` covering `PATH|LD_.*|PYTHONPATH|RUBYLIB|NODE_PATH|JAVA_TOOL_OPTIONS` in `backend/styrmin_backend/services/env_vars/validator.py`.
- [X] T008 Implement `validate_env_var_name(name: str)`, `validate_env_var_value(name: str, value: str)`, `validate_env_vars_dict(scope: str, mapping: dict[str, str])` in `backend/styrmin_backend/services/env_vars/validator.py`. Enforce: name regex (FR-006), per-value 64 KiB cap (FR-007), per-scope 100-entry / 256 KiB caps (FR-008), and `logger.warning("env_var_potentially_risky_name", ...)` when the name matches the risky family (FR-011 + critique E3). Empty values are accepted.
- [X] T009 Implement `validate_env_vars_input_list(items: list[EnvVarInput], scope: str) -> dict[str, str]` in `backend/styrmin_backend/services/env_vars/validator.py` — rejects duplicate names with `DuplicateEnvVarNameError` before constructing the dict (FR-009).
- [X] T010 [P] Add `env_vars: dict[str, str] | None = None` to `EnvironmentConfig` in `backend/styrmin_backend/context/models/config.py` with a Pydantic field validator that calls `validate_env_vars_dict("environment", v)`.
- [X] T011 [P] Add `env_vars: dict[str, str] | None = None` to `DeploymentConfig` in `backend/styrmin_backend/context/models/config.py` with the same validator (scope `"deployment"`).
- [X] T012 Add `env_vars: bool | None = None` to `PostRenderInjection` in `backend/styrmin_backend/context/models/config.py` (mirror of existing flags, including the docstring's three-valued semantics).
- [X] T013 [P] Add `ResolvedComponentEnvVars` model (with `config: dict[str, str]`, `provenance: dict[str, ProvenanceLevel]`, `is_orphaned: bool = False`) to `backend/styrmin_backend/context/models/components.py`. Mirror `ResolvedComponentScheduling` exactly.
- [X] T014 Add `env_vars: ResolvedComponentEnvVars | None = None` field to `ComponentContext` in `backend/styrmin_backend/context/models/components.py`.
- [X] T015 Extend `effective_inject_flag` in `backend/styrmin_backend/context/resolvers.py` to accept `"env_vars"` as a recognised feature name (returns `True` by default; honours `False` for opt-out).
- [X] T016 Implement `_merge_env_vars(env, dep, comp) -> tuple[dict[str, str], dict[str, ProvenanceLevel]]` in `backend/styrmin_backend/context/resolvers.py` with per-key deepest-wins (data-model.md §2.2).
- [X] T017 [P] Write unit test bundle at `backend/tests/unit/services/env_vars/test_validator.py` covering: name regex acceptance/rejection (per character class), per-value 64 KiB cap boundary (cap, cap+1), per-scope 100-entry cap, per-scope 256 KiB cap, empty-value acceptance, duplicate-name rejection in input list, risky-name `logger.warning` is emitted (capture via `caplog`). Reference `backend/styrmin_backend/services/scheduling/validator.py` tests for shape.
- [X] T018 [P] Write unit test bundle at `backend/tests/unit/services/env_vars/test_resolver.py` covering: precedence matrix across env/dep/comp, deployment-only, environment-only, no-components-declared fallback, provenance recording. Reference `backend/tests/unit/context/test_scheduling_resolver.py` for shape.

**Checkpoint**: `uv run pytest -q backend/tests/unit/services/env_vars/ backend/tests/unit/context/` passes; format/lint clean.

---

## Phase 3: US1 — Per-Deployment Env Var Override (Priority: P1) 🎯 MVP

**Goal**: An operator can set `LOG_LEVEL=debug` on a single deployment via `updateDeployment(config: { env_vars: { LOG_LEVEL: "debug" } })` and see it on every container of every pod-template-bearing workload after one reconcile.

**Independent Test**: Quickstart Step 1.

- [X] T019 [US1] Implement `EnvVarsResolver.resolve_for_deployment` in `backend/styrmin_backend/services/env_vars/resolver.py`: takes `EnvironmentConfig`, `DeploymentConfig`, optionally per-component config blocks; returns the deployment-level effective dict and a list of `ResolvedComponentEnvVars`. **For US1, the per-component path is empty/None.**
- [X] T020 [US1] Wire the deployment-level resolver into the existing context-resolution code in `backend/styrmin_backend/services/context.py` so the resolved dict reaches the `ComponentContext`/`InstanceContext`. Apply post-merge size cap from FR-008a (256 KiB resolved per component, 1 MiB total) — raise `EnvVarSizeLimitExceededError(scope="resolved", ...)` on overflow.
- [X] T021 [US1] Add `EnvVarsPatch` to `backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py` — a strategic-merge patch that injects an `env:` list into every container of a pod template. Include the kind/api-version branching pattern from `AffinityPatch`. Use `name: "*"` strategic-merge wildcard so all containers receive the env entries.
- [X] T022 [US1] Implement `build_env_vars_post_rendering_patches(resolved_dict, inject, label_selector=None) -> list[TargetPatch]` in `backend/styrmin_backend/services/env_vars/patch_builder.py`. Honour `effective_inject_flag(inject, "env_vars")`; skip when dict is empty; emit one patch per pod-template-bearing kind (use the `POD_TEMPLATE_BEARING_KINDS` constant from the scheduling patch builder).
- [X] T023 [US1] Implement `ApplicationBuilder.build_env_vars_post_rendering_patches()` in `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py`, mirroring `build_scheduling_post_rendering_patches`: iterate components → use `component.env_vars.config`; fall back to deployment-level resolved dict when no components declared (FR-004). Wire the call into `ApplicationBuilder.build()` next to `build_scheduling_post_rendering_patches()`.
- [X] T024 [US1] [P] Add `Deployment.envVars: [EnvVar!]!` resolver in `backend/styrmin_backend/api/definitions/deployment/model.py`. Add the `EnvVar` Strawberry type. Include the non-secret-only warning text in the type-level description per `contracts/graphql.md` §1.
- [X] T025 [US1] [P] Regenerate `schema.graphql` at the repo root (`uv run styrmin export graphql-schema schema.graphql`) and commit. Do not hand-edit the generated file.
- [X] T026 [US1] [P] Regenerate SDK Pydantic types (`uv run invoke generate`) and commit the result. CI fails when this is out of date.
- [X] T027 [US1] [P] Write unit test bundle at `backend/tests/unit/services/env_vars/test_patch_builder.py` covering: deployment-level only, inject opt-out, no-components fallback, multi-container injection. Reference `backend/tests/unit/services/scheduling/test_patch_builder.py` (or equivalent) for shape.
- [X] T028 [US1] [P] Write unit test at `backend/tests/unit/agent/test_application_builder_env_vars.py` asserting `build_env_vars_post_rendering_patches()` is invoked from `ApplicationBuilder.build()` and the emitted patches reach `target_patches`. Reference `backend/tests/unit/agent/test_application_builder_scheduling.py` for shape.
- [X] T029 [US1] Write GraphQL propagation test at `backend/tests/unit/api/schema/test_env_vars_propagation.py` for `Deployment.envVars` (Constitution §V, non-negotiable): `updateDeployment(config: { env_vars: { X: "y" } })` → query `Deployment.envVars` returns `[{name: "X", value: "y"}]`, against the real service+repository layers per `dev/guides/graphql-propagation-tests.md`.
- [X] T030 [US1] Extend `backend/tests/e2e/test_deployment_env_vars.py` with the US1 scenario (Quickstart Step 1): deploy `simple-app`, set `envVars: { LOG_LEVEL: "debug" }`, kubectl-assert the env entry on container env. Marked `@pytest.mark.api_only(reason="API/SDK-only flow; no UI exercised")`.

**Checkpoint**: US1 is independently shippable. `uv run pytest backend/tests/e2e/test_deployment_env_vars.py::test_us1_deployment_level_env_var -v -s --pdb` passes against a real cluster.

---

## Phase 4: US2 — Environment-Scoped Baseline Env Vars (Priority: P1)

**Goal**: An env var set at the environment scope propagates to every existing and future deployment in that environment; deployments can override on a per-key basis.

**Independent Test**: Quickstart Step 2.

- [ ] T031 [US2] Extend `EnvVarsResolver.resolve_for_deployment` in `backend/styrmin_backend/services/env_vars/resolver.py` to merge the environment layer ahead of the deployment layer using `_merge_env_vars(env, dep, None)`. Provenance must report `"environment"` for keys whose value comes from the environment scope.
- [ ] T032 [US2] [P] Add `Environment.envVars: [EnvVar!]!` resolver in `backend/styrmin_backend/api/definitions/environment/model.py` (mirror US1's deployment surface).
- [ ] T033 [US2] [P] Verify the existing `updateEnvironmentConfig` (or current equivalent — check `backend/styrmin_backend/api/schema/mutation.py`) accepts `config: { env_vars: { ... } }` via the existing JSON path; if it does not validate against `EnvironmentConfig`, wire it through.
- [ ] T034 [US2] [P] Regenerate `schema.graphql` and SDK types after the resolver field is added.
- [ ] T035 [US2] [P] Extend `test_resolver.py` (T018 file) with the precedence cases: env-only, env-overridden-by-deployment per-key, env-and-deployment-disjoint-keys-merge.
- [ ] T036 [US2] Add propagation test for `Environment.envVars` to `backend/tests/unit/api/schema/test_env_vars_propagation.py`: `updateEnvironmentConfig(config: { env_vars: { X: "y" } })` → query returns `[{name: "X", value: "y"}]`.
- [ ] T037 [US2] Extend the E2E test with the US2 scenario (Quickstart Step 2): set env var at environment scope, deploy a second deployment, assert both pods carry the env var; then set a deployment-level override on one and assert the divergence.

**Checkpoint**: US2 is independently shippable on top of US1.

---

## Phase 5: US3 — Per-Component Scoping with Deepest-Wins Precedence (Priority: P1)

**Goal**: Per-component env vars apply only to the targeted component's pods; deployment-level baselines are overridden on a per-key basis at the component scope; mutations targeting unknown components are rejected with a precise error listing the driver's known components.

**Independent Test**: Quickstart Step 3 (positive) + Step 4 (negative — mutation rejection).

- [ ] T038 [US3] Extend `EnvVarsResolver.resolve_for_deployment` in `backend/styrmin_backend/services/env_vars/resolver.py` to take per-component env var blocks and produce one `ResolvedComponentEnvVars` per **driver-declared** component, calling `_merge_env_vars(env, dep, comp)`. **Orphan handling is added in Phase 7 (US5)** — for now, ignore stored blocks targeting unknown components.
- [ ] T039 [US3] Extend `ApplicationBuilder.build_env_vars_post_rendering_patches()` in `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py` to iterate `context.components[*].env_vars.config` and emit per-component patches narrowed by `component.config.identifier.label.label_selectable()` (mirroring the scheduling builder).
- [ ] T040 [US3] In `backend/styrmin_backend/services/deployment.py` (existing `update_deployment` / `deploy_application` services), after parsing `DeploymentConfig`, validate that every component name in `config.components.<name>.env_vars` matches a component the deployment's current driver declares. Raise `UnknownComponentEnvVarError(unknown_component=..., known_components=[...])` on mismatch (FR-010).
- [ ] T041 [US3] [P] Add `ComponentEnvVars` Strawberry type in `backend/styrmin_backend/api/definitions/deployment/model.py` with fields `component`, `envVars: [EnvVar!]!`, `isOrphaned: Boolean!`. Add `Deployment.componentEnvVars: [ComponentEnvVars!]!` resolver. For US3 the resolver returns `isOrphaned=False` for every block (orphan path is added in Phase 7).
- [ ] T042 [US3] [P] Regenerate `schema.graphql` and SDK types.
- [ ] T043 [US3] [P] Extend `test_patch_builder.py` (T027 file) with: component-level only, mixed deployment+component, component-level patches narrow by label selector.
- [ ] T044 [US3] [P] Extend `test_resolver.py` (T018 file) with: per-component precedence overrides, no-components-declared fallback, component-only scope (no deployment-level), provenance reports `"component"` for component-overridden keys.
- [ ] T045 [US3] Add propagation tests for `Deployment.componentEnvVars` (initial isOrphaned=false case) and the `UnknownComponentEnvVarError` mutation rejection path to `backend/tests/unit/api/schema/test_env_vars_propagation.py`.
- [ ] T046 [US3] Extend the E2E test with the US3 scenario (Quickstart Step 3): multi-component deploy with deployment-level + per-component env vars; assert per-component pods reflect the merged dict; assert peer components are unaffected. Add the negative case from Step 4 asserting `UnknownComponentEnvVarError` is raised when `config.components.does_not_exist.env_vars` is set.

**Checkpoint**: The MVP (US1+US2+US3) is shippable. `uv run pytest backend/tests/e2e/test_deployment_env_vars.py -v -s --pdb` passes the US1/US2/US3 scenarios.

---

## Phase 6: US4 — Driver-Side Documentation (Priority: P2)

**Goal**: Drivers may include a `spec.env_vars` block listing documented env vars; the loader validates the block; the GraphQL driver detail surface exposes the docs.

**Independent Test**: Quickstart Step 5.

- [ ] T047 [US4] Implement `DriverEnvVarLevel` enum and `DriverEnvVarDoc` model with field/model validators in `backend/styrmin_backend/services/driver/models/resources/env_vars.py` per `data-model.md` §3 (name regex, level/components consistency, name uniqueness within the list).
- [ ] T048 [US4] Add `env_vars: list[DriverEnvVarDoc] | None = None` field to `Specification` in `backend/styrmin_backend/services/driver/models/resources/driver.py`. Add a `@field_validator` that enforces name uniqueness across the list (mirror the existing `validate_parameter_names` validator).
- [ ] T049 [US4] Add a model validator (or external function in `backend/styrmin_backend/services/driver/validators.py`) that cross-validates: every `components` entry in every `env_vars` doc must exist in `Specification.components.root`. Raise a precise validation error on mismatch (`DriverEnvVarDocComponentMismatchError`). Wire it into the driver loader at `backend/styrmin_backend/services/driver/loaders.py` so registration aborts on failure (FR-014).
- [ ] T050 [US4] [P] Add `DriverEnvVarDoc` Strawberry type and `ApplicationDriverVersion.envVars: [DriverEnvVarDoc!]!` resolver in `backend/styrmin_backend/api/definitions/application_driver/model.py`. Convert the `DriverEnvVarLevel` Pydantic enum to a Strawberry enum.
- [ ] T051 [US4] [P] Regenerate `schema.graphql` and SDK types.
- [ ] T052 [US4] [P] Write unit test bundle at `backend/tests/unit/services/driver/test_env_var_doc_validator.py`: name regex, level=component requires non-empty components, level=deployment must NOT name components, name uniqueness, components-must-exist cross-field validation, registration-fails-on-bad-doc.
- [ ] T053 [US4] Add propagation test for `ApplicationDriverVersion.envVars`: load a driver YAML with `spec.env_vars: [...]` → query returns the doc list shaped per `DriverEnvVarDoc`.
- [ ] T054 [US4] Update `driver/examples/simple-app/driver.styrmin.yml` with a representative `spec.env_vars` block (one deployment-level entry, one component-level entry referencing `server` or `database`) so the E2E test has real data.
- [ ] T055 [US4] Extend the E2E test with Quickstart Step 5: query `applicationDriverVersion.envVars` and assert the seeded entries are returned with correct `level` / `components`.

**Checkpoint**: US4 is shippable. SDK consumers of the driver detail can see documented env vars.

---

## Phase 7: US5 — Visible Orphan Tracking Across Upgrades (Priority: P2)

**Goal**: Driver upgrades that rename or remove a component succeed; the orphaned `componentEnvVars` block is visible with `isOrphaned: true`; the orphan transition is captured exactly once per upgrade transition through the existing `context_diff` machinery.

**Independent Test**: Quickstart Step 6.

- [ ] T056 [US5] Extend `EnvVarsResolver.resolve_for_deployment` in `backend/styrmin_backend/services/env_vars/resolver.py` to:
  - Accept stored per-component env var blocks regardless of whether they target current driver components.
  - Emit a `ResolvedComponentEnvVars(is_orphaned=True)` for any block whose target component is NOT in the current driver's component map. Provenance for orphaned keys is `"component"`.
  - Skip orphaned blocks when computing effective per-component dicts (so they are not injected).
- [ ] T057 [US5] Update `backend/styrmin_backend/services/deployment.py` mutation validators so `UnknownComponentEnvVarError` is raised **only on write** — reads (resolution) tolerate orphan state by exposing `isOrphaned`. Document the asymmetry in the function docstring.
- [ ] T058 [US5] [P] Update `Deployment.componentEnvVars` resolver in `backend/styrmin_backend/api/definitions/deployment/model.py` to surface orphan blocks with `isOrphaned=true`.
- [ ] T059 [US5] [P] Extend `test_resolver.py` (T018 file) with: orphan detection (component renamed + removed), orphan-and-live-mixed, orphan-only-block, orphan-then-driver-rolls-back-to-make-it-live-again (FR-033 / Edge Case).
- [ ] T060 [US5] Add propagation test for `ComponentEnvVars.isOrphaned=true`: stage a deployment with a `componentEnvVars` block on `worker`, then update `application_driver_version` to a version without `worker`; query asserts `isOrphaned: true` and rendered patches contain no `worker` env entries.
- [ ] T061 [US5] Extend the E2E test with Quickstart Step 6: full upgrade scenario including the timeline-entry assertion (`context_diff` records the orphan once for the upgrade Task).

**Checkpoint**: US5 is shippable. Operators can audit orphans through the existing query and timeline surfaces.

---

## Phase 8: US6 — Component-Level Injection Opt-Out (Priority: P3)

**Goal**: A component flagged with `inject.env_vars=False` retains its chart-rendered env entries unchanged; peer components in the same deployment continue to receive operator-set env vars.

**Independent Test**: Quickstart Step 7.

- [ ] T062 [US6] Verify `effective_inject_flag(inject, "env_vars")` (T015) is invoked inside `build_env_vars_post_rendering_patches` (T022) and inside `ApplicationBuilder.build_env_vars_post_rendering_patches()` (T023) for the per-component branch. If missing, add the call so component-level opt-out short-circuits patch emission.
- [ ] T063 [US6] [P] Extend `test_patch_builder.py` (T027 file) with: `inject.env_vars=False` opts-out at component level, peer components still receive env vars, deployment-level inject=False suppresses everything.
- [ ] T064 [US6] [P] Extend `test_application_builder_env_vars.py` (T028 file) with the multi-component opt-out scenario.
- [ ] T065 [US6] Extend the E2E test with Quickstart Step 7 (component-level opt-out asserts).

**Checkpoint**: US6 is shippable. Pristine-env components are protected.

---

## Phase 9: US7 — Chart Conflict Warning (Priority: P3)

**Goal**: When an operator-set env var collides with a chart-rendered env entry, the operator value wins (post-render replaces) AND a warning surfaces — primarily on `DeploymentTimelineEntry.envVarCollisions`, with a structured log line as the always-on fallback.

**Independent Test**: Quickstart Step 8.

- [ ] T066 [US7] Add `ChartEnvCollision` dataclass to `backend/styrmin_backend/services/env_vars/patch_builder.py`: `component: str | None`, `container: str`, `name: str`, `chart_value: str`, `user_value: str`. Mirror the dataclass style of `ContextChange` in `services/deployment_timeline.py`.
- [ ] T067 [US7] Extend `build_env_vars_post_rendering_patches` to walk rendered manifest container env entries (the patch builder is invoked at render time with access to the rendered docs through the existing pipeline) and record `ChartEnvCollision` instances on the patch result. Emit `logger.warning("env_var_chart_collision", deployment_id=..., name=..., chart_value=..., user_value=...)` unconditionally per collision (FR-027/FR-028).
- [ ] T068 [US7] Extend `TimelineEntry` in `backend/styrmin_backend/services/deployment_timeline.py` with `env_var_collisions: list[ChartEnvCollision] = field(default_factory=list)`. Wire the timeline build to populate the field from per-task agent reports (the agent layer attaches collisions to the Task on each reconcile).
- [ ] T069 [US7] [P] Add `EnvVarCollision` Strawberry type and `DeploymentTimelineEntry.envVarCollisions: [EnvVarCollision!]!` resolver in `backend/styrmin_backend/api/definitions/deployment_timeline/model.py`.
- [ ] T070 [US7] [P] Regenerate `schema.graphql` and SDK types.
- [ ] T071 [US7] [P] Extend `test_patch_builder.py` (T027 file) with collision detection cases: chart sets X=warn + user sets X=debug → exactly one `ChartEnvCollision` recorded, user value wins in the rendered output.
- [ ] T072 [US7] Add propagation test for `DeploymentTimelineEntry.envVarCollisions`: simulate a reconcile with one collision, query `deployment.timeline { envVarCollisions { ... } }` and assert the entry surfaces.
- [ ] T073 [US7] Extend the E2E test with Quickstart Step 8 (a chart that renders a colliding env entry; assert user value on pod and collision record on the timeline).

**Checkpoint**: US7 is shippable. All seven user stories are landed.

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, ADR, full-suite validation, code-quality gates.

- [ ] T074 [P] Draft `dev/adr/adr-019-deployment-env-vars.md` per `research.md` §7. Cover: (1) env vars vs typed parameters boundary, (2) doc-only driver declaration, (3) post-render-wins-with-warning conflict policy, (4) warn-and-keep upgrade orphan policy, (5) cluster scope deferred, (6) `isOrphaned` as a first-class API contract.
- [ ] T075 [P] Update `dev/knowledge/` (or `dev/guides/`) with a short reference page on the deployment env vars feature — covering the three-scope hierarchy, the size caps, and the no-secrets policy. Link from `dev/knowledge/README.md` if applicable.
- [ ] T076 [P] Run the full GraphQL propagation test suite (`uv run pytest backend/tests/unit/api/schema/test_env_vars_propagation.py -v`) and confirm every row in `contracts/graphql.md` §4 has a passing assertion.
- [ ] T077 Run the full E2E suite (`uv run pytest backend/tests/e2e/test_deployment_env_vars.py -v -s --pdb`) and observe a green run, per Constitution §V (E2E is part of the definition of done).
- [ ] T078 [P] Run `uv run invoke format lint` and resolve any violations.
- [ ] T079 [P] Run `uv run invoke validate-graphql` to confirm every new `.graphql` file (if any new query files were added for tests/SDK) passes schema validation.
- [ ] T080 [P] Confirm `schema.graphql` and the generated SDK types under `python_sdk/src/styrmin_sdk/graphql/_generated/` are checked in and consistent (CI fails otherwise).
- [ ] T081 Final cross-check: every FR in `spec.md` Requirements section is wired to at least one task in this list. Items intentionally deferred should match `spec.md` §"Out of Scope" only.

---

## Dependencies

### User-story dependency graph

```text
Setup (Phase 1)
   │
   ▼
Foundational (Phase 2)
   │
   ▼
US1 (Phase 3) ◄── MVP slice 1/3
   │
   ├──► US2 (Phase 4) ◄── MVP slice 2/3 (extends resolver only)
   │
   ├──► US3 (Phase 5) ◄── MVP slice 3/3 (extends resolver + builder + GraphQL)
   │       │
   │       ├──► US5 (Phase 7)   (depends on US3's componentEnvVars surface)
   │       └──► US6 (Phase 8)   (depends on US3's per-component patches)
   │
   ├──► US4 (Phase 6)   (independent of US2/US3 — only touches driver loader + driver query)
   │
   └──► US7 (Phase 9)   (depends on US3's per-component patches; uses TimelineEntry channel)
              │
              ▼
         Polish (Phase 10)
```

US1, US2, US3 collectively form the genuine MVP. US4 is independent and could ship in parallel with the MVP slices. US5/US6/US7 each depend on the MVP foundation.

### Within-phase parallelism

- **Phase 2 (Foundational)**: T010, T011, T013, T017, T018 are all `[P]` — different files, no inter-task dependencies.
- **Phase 3 (US1)**: T024, T025, T026, T027, T028 are `[P]` (different files; codegen tasks `git add` regenerated outputs).
- **Phase 4 (US2)**: T032, T033, T034, T035 are `[P]`.
- **Phase 5 (US3)**: T041, T042, T043, T044 are `[P]`.
- **Phase 6 (US4)**: T050, T051, T052 are `[P]`.
- **Phase 9 (US7)**: T069, T070, T071 are `[P]`.

### Implementation strategy

1. **Land the MVP first** — drive Phase 1 → Phase 2 → Phase 3 (US1) → Phase 4 (US2) → Phase 5 (US3) end-to-end including the E2E pass. **Do not move on until the MVP E2E is green** (Constitution §V).
2. **Ship US4 in parallel** with the MVP if a second implementer is available — it touches the driver loader and a separate GraphQL surface; merge conflicts with the MVP branch are minimal.
3. **Ship US5/US6/US7 sequentially** after the MVP — each extends a different MVP-built surface and the smaller scope helps keep PRs reviewable.
4. **Polish last** — the ADR draft and the propagation/E2E full-suite runs catch any last gaps before merge.

## MVP Scope (recommended)

- **MVP**: Phase 1 → Phase 2 → US1 → US2 → US3 (excludes US4/US5/US6/US7 and the polish tasks).
- **Definition of done for MVP**: All FRs except FR-012..FR-015, FR-024 (`inject.env_vars` flag — partial), FR-027..FR-033 are wired; the MVP E2E covers Quickstart Steps 1-4 inclusive (positive + negative paths for the three-scope hierarchy).
- **Strictly out of scope for MVP**: secret env vars, cluster scope, container-granularity injection, UI surfaces, parameter migration (per spec FR-034..FR-036).

## Validation checklist

- [ ] Every FR in `spec.md` maps to at least one task above (T081 enforces).
- [ ] Every new GraphQL field/argument in `contracts/graphql.md` §4 has a propagation test (Constitution §V).
- [ ] Every user story has at least one E2E assertion in `backend/tests/e2e/test_deployment_env_vars.py` (Constitution §V).
- [ ] No tasks reference inline GraphQL strings (project rule: all queries in `.graphql` files).
- [ ] No tasks edit generated files manually (boundary: `schema.graphql` and `python_sdk/src/styrmin_sdk/graphql/_generated/` are regenerated, never hand-edited).
