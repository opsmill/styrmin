# Tasks: Driver-Side Env Var Consumption via Values Template

**Input**: Design documents from `/specs/010-driver-env-var-consumption/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/graphql.md, quickstart.md, critiques/critique-20260508-164015.md

**Tests**: Tests are **mandatory** for this feature per Constitution §V (Test-First Development) and `AGENTS.md`. The user explicitly called out FR-014a (chart-default-preservation E2E assertion) and FR-001/FR-002 (template-context exposure unit test).

**Organization**: Tasks are grouped by user story so each can be implemented independently. US1 + US2 + US3 form the load-bearing trio; US4 is documentation that ships in v1.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no incomplete dependencies)
- **[Story]**: Which user story this task belongs to (US1..US4)
- File paths are absolute-from-repo-root and exact

## Path Conventions

This is a **web service** project. Backend lives under `backend/styrmin_backend/`; backend tests under `backend/tests/`; frontend under `frontend/src/` (codegen only — no hand-written changes); driver examples under `driver/examples/`; documentation under `dev/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create new file scaffolding. Deletion-heavy feature, so most setup is preparing test files for the new context-exposure verification + the docs.

- [X] T001 [P] Create new test file `backend/tests/unit/agent/test_render_value_template_env_vars.py` with one passing placeholder test, so the file is wired into pytest collection.
- [X] T002 [P] Create new doc file `dev/guides/driver-env-var-consumption.md` with a stub heading + one-line summary, so the file exists for content fill-in.
- [X] T003 [P] Create new ADR file `dev/adr/adr-021-driver-env-var-consumption.md` with Status / Context / Decision / Consequences scaffolding (reference adr-019 + adr-020 for shape).

**Checkpoint**: `uv run pytest --collect-only -q backend/tests/unit/agent/test_render_value_template_env_vars.py` collects cleanly. The two doc files exist as stubs.

---

## Phase 2: Foundational (Verification)

**Purpose**: Prove the rendering context already exposes env vars before deleting the broken injection layer. The verification test is load-bearing — without it, removing the injection would silently break operator-set env vars on every driver.

- [X] T004 Implement `test_render_value_template_env_vars.py` per research §1: feed a synthetic `GlobalContext` (with env vars set at deployment scope and per-component scope) through `ApplicationBuilder.render_value_template` with a probe Jinja template that reads `instance.config.env_vars` and `components[<name>].env_vars.config`. Assert the rendered output reflects the expected values. Cover the absent-key case (no env vars set anywhere → defensive `or {}` handles it without raising).
- [X] T005 [P] Verify the test passes against the current (pre-deletion) codebase. **Don't delete anything yet** — this commit is the safety net that proves the new path works. If T004 fails against the current code, the implementer must investigate why before proceeding to Phase 3 (the rendering-context exposure may need a small fix; the spec assumes it's already correct, but verification is the gate).

**Checkpoint**: `uv run pytest -q backend/tests/unit/agent/test_render_value_template_env_vars.py` passes. This proves FR-001 + FR-002 hold against the live `GlobalContext.model_dump(exclude_none=True)` path.

---

## Phase 3: US1 — Driver Template Consumption (Priority: P1)

**Goal**: Driver templates receive `instance.config.env_vars` and `components[<name>].env_vars.config` in their Jinja rendering context. Verified by Phase 2's unit test plus the simple-app demo (US3).

**Note**: Phase 2 proved the consumption surface works. US1 is logically complete once Phase 2 passes — there is no additional code to write. The remaining tasks for US1 are documentation/verification tied to FR-001..FR-004.

- [X] T006 [US1] Verify the Pydantic models (`ResolvedConfig.env_vars`, `ComponentContext.env_vars`) keep `model_config = ConfigDict(extra="forbid")` (or whatever the existing convention is) so `model_dump(exclude_none=True)` continues to behave consistently across releases. If the convention isn't pinned today, add a regression unit test that asserts the dump shape for a known input. (This guards against future Pydantic-config changes silently breaking the rendering context.)
- [X] T007 [US1] [P] Add a docstring to `ApplicationBuilder.render_value_template` (in `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py`) noting that `instance.config.env_vars` and `components[<name>].env_vars.config` are part of the rendering contract surfaced to driver templates. Cross-link to `dev/guides/driver-env-var-consumption.md` for the consumer-side documentation.

**Checkpoint**: US1 is verified. The exposure works; the consumption contract is documented inline.

---

## Phase 4: US2 — Delete the Broken Injection Layer (Priority: P1)

**Goal**: Remove `EnvVarsPatch`, `build_env_vars_post_rendering_patches`, the `ApplicationBuilder.build_env_vars_post_rendering_patches()` method + invocation, the `PostRenderInjection.env_vars` flag, the `EnvVarCollision` Strawberry type, the `ChartEnvCollision` dataclass, the `DeploymentTimelineEntry.envVarCollisions` GraphQL field, and every test asserting against any of them. Schema regenerates; SDK regenerates; frontend types regenerate.

**Independent Test**: Quickstart Step 3 (`grep` returns zero hits for the removed symbols).

- [X] T008 [US2] Delete `EnvVarsPatch` class from `backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py`. Verify no other production code imports it (`grep -rn "EnvVarsPatch" backend/styrmin_backend/`).
- [X] T009 [US2] Delete `build_env_vars_post_rendering_patches` from `backend/styrmin_backend/services/env_vars/patch_builder.py`. Delete `ChartEnvCollision` dataclass from the same file. If the file has no other content after these deletions, delete the entire file. Verify no production imports remain (`grep -rn "from.*env_vars.patch_builder\|build_env_vars_post_rendering_patches\|ChartEnvCollision" backend/styrmin_backend/`).
- [X] T010 [US2] Delete `ApplicationBuilder.build_env_vars_post_rendering_patches` method from `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py`. Delete the `target_patches.extend(self.build_env_vars_post_rendering_patches())` invocation inside `ApplicationBuilder.build()`. Delete the now-unused import line at the top of the file.
- [X] T011 [US2] Delete `PostRenderInjection.env_vars` field from `backend/styrmin_backend/context/models/config.py`. Verify no resolver code depends on the field (`grep -rn "inject.env_vars\|env_vars.*PostRenderInjection" backend/styrmin_backend/`).
- [X] T012 [US2] Remove the `"env_vars"` entry from `_INJECT_FIELDS` in `backend/styrmin_backend/context/resolvers.py` (so `_merge_inject_flags` and `effective_inject_flag` no longer recognise it).
- [X] T013 [US2] Delete `PostRenderInjectionInput.envVars` (Strawberry input field) from `backend/styrmin_backend/api/definitions/environment/inputs.py`. The `PostRenderInjectionInput` input type retains its other inject flags.
- [X] T014 [US2] Delete `EnvVarCollision` Strawberry type and `DeploymentTimelineEntry.envVarCollisions` field from `backend/styrmin_backend/api/definitions/deployment_timeline/model.py`. Delete the corresponding `from_data` adapter. Delete the unused import for `ChartEnvCollision` (now-deleted from §T009).
- [X] T015 [US2] Delete `TimelineEntry.env_var_collisions` field from `backend/styrmin_backend/services/deployment_timeline.py`. Delete any code populating the field (likely none, since 008 documented it as unpopulated). Verify `build_deployment_timeline` no longer references the deleted field.
- [X] T016 [US2] Review `backend/styrmin_backend/api/errors.py` for error codes introduced specifically for the deleted surface. The 008 codes (`INVALID_ENV_VAR_NAME`, `ENV_VAR_SIZE_LIMIT_EXCEEDED`, `DUPLICATE_ENV_VAR_NAME`, `UNKNOWN_COMPONENT_ENV_VAR`) STAY — they're for the validation pipeline. Any code introduced solely for the injection layer (none expected, but verify) gets deleted.
- [X] T017 [US2] [P] Delete the entire test file `backend/tests/unit/services/env_vars/test_patch_builder.py`.
- [X] T018 [US2] [P] In `backend/tests/unit/agent/test_application_builder_env_vars.py`, delete every assertion / test method that exercises `build_env_vars_post_rendering_patches` or `EnvVarsPatch`. If the file has no other content after these deletions, delete the entire file.
- [X] T019 [US2] [P] In `backend/tests/functional/graphql/test_env_vars_propagation.py`, delete propagation rows that assert `DeploymentTimelineEntry.envVarCollisions` or `PostRenderInjectionInput.envVars`. Keep every other propagation row green.
- [X] T020 [US2] Regenerate `schema.graphql` (`uv run styrmin export graphql-schema schema.graphql`). Diff should show: removed `EnvVarCollision` type, removed `DeploymentTimelineEntry.envVarCollisions` field, removed `PostRenderInjectionInput.envVars` field. Commit the regenerated file.
- [X] T021 [US2] [P] Regenerate SDK Pydantic types (`uv run invoke generate`). Commit the regenerated `python_sdk/src/styrmin_sdk/graphql/_generated/` output and the frontend's regenerated `frontend/src/generated/graphql.ts`.
- [X] T022 [US2] Run the verification grep from research §2: `grep -rn "EnvVarsPatch\|build_env_vars_post_rendering_patches\|ChartEnvCollision\|envVarCollisions\|PostRenderInjection.*env_vars\|env_var_collisions" backend/styrmin_backend/ python_sdk/src/ frontend/src/ schema.graphql 2>&1 | grep -v Binary`. Result MUST be zero hits in source code. Archived spec docs (`specs/008-...`, `specs/009-...`) may match — that's historical, leave them.
- [X] T023 [US2] Run `uv run invoke format lint` — must pass cleanly. Run `uv run pytest -q backend/tests/unit/ backend/tests/functional/` — every retained test stays green. The deleted-injection tests are gone (not skipped); the propagation matrix is shorter; everything else passes.

**Checkpoint**: US2 is independently shippable. The platform no longer attempts post-render env-vars injection. The remaining surfaces (configuration model, validators, query surface, mutation, frontend) are unchanged.

---

## Phase 5: US3 — simple-app Driver Update + Chart-Default-Preservation E2E (Priority: P1)

**Goal**: The simple-app driver's `values.j2.yml` consumes `instance.config.env_vars` and emits operator-set env vars through the chart's own templating. The 008/009 E2E continues to pass via this driver-side consumption path. **FR-014a**: the retained E2E gains an explicit assertion that at least one chart-default env entry is preserved alongside the operator-set entries — the load-bearing assertion vs 008's broken behaviour.

**Independent Test**: Quickstart Steps 1–4.

- [X] T024 [US3] Update `driver/examples/simple-app/values.j2.yml` per research §3: add an `env:` block on the simple-app container that consumes `(instance.config.env_vars or {}).items()`, emitting each entry as `{ name: <name>, value: <value> }`. Use Jinja's `tojson` filter (or equivalent) on the value to safely escape characters that would otherwise break unquoted YAML (FR-022 / critique E2). The empty-dict case renders an empty list `[]` — chart template handles this without rendering the section.
- [X] T025 [US3] Verify the simple-app Helm chart's container template accepts an `env: [{ name, value }]` array on the container spec. If the chart does not currently support this, extend the chart minimally (FR-013) — the chart is project-controlled at `driver/examples/simple-app/` (or wherever the simple-app chart's source lives in this repo). No external dependency.
- [X] T026 [US3] **FR-014a — chart-default-preservation E2E assertion**. Extend the retained 008/009 E2E test `test_us1_deployment_level_env_var` in `backend/tests/e2e/test_deployment_env_vars.py`: after asserting `LOG_LEVEL=debug` is present on the pod's container env, ALSO assert that at least one chart-default env entry (sourced from the simple-app chart's `values.yaml` defaults) is present. The assertion target is whichever chart-default the simple-app chart ships — if the chart currently sets none, add one to the chart's `values.yaml` (e.g., `STYRMIN_CHART_DEFAULT=marker`) so this assertion has something to pin against. Document the marker explicitly in a test comment so future chart maintainers don't remove it accidentally.
- [X] T027 [US3] [P] Run the full backend unit + functional test suite: `uv run pytest -q backend/tests/unit/ backend/tests/functional/`. Confirm green.
- [X] T028 [US3] Verify the E2E test collects cleanly: `uv run pytest --collect-only -q backend/tests/e2e/test_deployment_env_vars.py 2>&1 | tail -5`. The body changes (adding the chart-default assertion) but the test ID and decoration stay the same.

**Checkpoint**: US3 is shippable. The simple-app driver demos the new consumption pattern. The retained E2E now exercises both "operator-set entry reaches pod" AND "chart-default entry is preserved" — covering SC-001 + SC-002.

---

## Phase 6: US4 — Driver-Author Guide + ADR (Priority: P2)

**Goal**: A driver-author unfamiliar with 008/009/010 can write a values template that consumes env vars correctly without reading simple-app source. The pivot is recorded as a durable ADR.

**Independent Test**: Quickstart Step 7.

- [ ] T029 [US4] Fill in `dev/guides/driver-env-var-consumption.md` per research §4. Three sections:
  1. **What env vars reach your template** — `instance.config.env_vars` and `components[<name>].env_vars.config` shapes; when populated; how the platform-side merge works.
  2. **How to render them** — three worked examples per FR-022:
     - Single-component driver (simple-app pattern).
     - Multi-component driver (per-component scoping).
     - Driver combining chart-default env entries with operator-set ones (driver-author chooses ordering).
     **All examples MUST use safe value escaping** (Jinja `tojson` filter or equivalent quoting) per FR-022 + critique E2.
  3. **What the platform doesn't do** — explicit non-policy: no enforcement, no validation that env vars are consumed, no automatic chart-default merging. Drivers own consumption shape.
  Cross-link to `dev/knowledge/backend/deployment-env-vars.md` (operator-facing) and `specs/010-driver-env-var-consumption/spec.md` (canonical contract).
- [ ] T030 [US4] [P] Fill in `dev/adr/adr-021-driver-env-var-consumption.md` per research §5. Six topics:
  1. Why post-render injection failed (k8s strategic-merge has no container wildcard; per-container patches require chart-internal container names the platform doesn't have without an invasive new contract — see research §2's third rejected alternative).
  2. Why driver-side consumption is the right boundary (drivers know their charts).
  3. Why merged dicts (not layered) — simpler API; layered is future work.
  4. Why no helper macros — drivers know their charts; v1 minimum surface; helpers land when patterns emerge.
  5. Migration responsibility — driver authors update templates as needed.
  6. Relationship to ADR-019 + ADR-020 — 010 supersedes ADR-019's post-render-injection portions; ADR-020 (env-config fanout) is unaffected.
  Status: Accepted. Date: 2026-05-08.
- [ ] T031 [US4] [P] Update `dev/knowledge/backend/deployment-env-vars.md` per FR-023: replace the "post-render injection" paragraph with a "driver-side consumption" paragraph pointing at the new guide. Note that the consumption contract belongs to the driver author; the platform's role is to expose the resolved dict via the rendering context.

**Checkpoint**: US4 is shippable. Driver authors have docs; the design is recorded for the future.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final-suite validation, codegen consistency, FR cross-check.

- [ ] T032 [P] Run `uv run invoke format lint` — must pass.
- [ ] T033 [P] Run `uv run invoke validate-graphql` — must pass.
- [ ] T034 [P] Run the full GraphQL propagation test suite (`uv run pytest -q backend/tests/functional/graphql/`). Every retained row in 008+009's matrix continues to pass; the rows for `DeploymentTimelineEntry.envVarCollisions` + `PostRenderInjectionInput.envVars` are gone (T019).
- [ ] T035 Run the full E2E suite (`uv run pytest backend/tests/e2e/test_deployment_env_vars.py -v -s --pdb`) against a real Kind/vCluster and observe a green run, per Constitution §V. **This is the load-bearing run** — the chart-default-preservation assertion (T026 / FR-014a) confirms the pivot achieves SC-002. If the dev stack isn't up locally, document the partial outcome and defer to PR opener.
- [ ] T036 [P] Confirm `schema.graphql` and the regenerated SDK + frontend types are checked in and consistent (no drift after a fresh `uv run invoke generate`). Per the deletion sweep, the diff against pre-010 should show ONLY removed surface; no unrelated drift.
- [ ] T037 [P] Run `cd frontend && pnpm test --run`. The frontend codegen-only changes should not affect Vitest behaviour; every existing test continues to pass.
- [ ] T038 Final cross-check: every FR in `spec.md` (FR-001..FR-026) maps to at least one task in this list. Items in spec §"Out of Scope" / FR-024..FR-026 are deliberately not wired (codified non-features). Generate the FR cross-check table inline in your final response.

---

## Dependencies

### Phase ordering

```text
Setup (Phase 1)
   │
   ▼
Foundational (Phase 2 — verification proves consumption works)
   │
   ▼
US1 (Phase 3 — verification + docstring; logically empty after Phase 2)
   │
   ▼
US2 (Phase 4 — DELETE the broken injection)
   │
   ▼
US3 (Phase 5 — simple-app demo + chart-default-preservation E2E)
   │
   ▼
US4 (Phase 6 — driver-author guide + ADR)
   │
   ▼
Polish (Phase 7)
```

**Critical dependency**: Phase 2 MUST pass before Phase 4 begins. The verification test is the safety net — without it, deleting the injection could leave operators stranded if the rendering context exposure isn't actually working.

### Within-phase parallelism

- **Phase 1**: T001, T002, T003 are all `[P]`.
- **Phase 4 (US2)**: T017, T018, T019, T021 are `[P]` (different files / different test methods). T020 (schema regen) MUST run after T008–T015 finish.
- **Phase 5 (US3)**: T027 is `[P]` (full-suite verification, independent of T024–T026).
- **Phase 6 (US4)**: T030, T031 are `[P]` with T029.
- **Phase 7 (Polish)**: T032, T033, T034, T036, T037 are `[P]`.

### Implementation strategy

1. **Land Phase 1 + Phase 2 first**. The verification proves the consumption surface works.
2. **Land Phase 4 (US2 deletion sweep)** in a single coherent commit chain. The schema/SDK/frontend regen happens once, after all Python deletions land.
3. **Land Phase 5 (US3)** — simple-app demo + chart-default-preservation E2E assertion. This is where the pivot becomes operationally visible.
4. **Land Phase 6 (US4) + Phase 7 (Polish)** as the final cleanup.

## MVP Scope (recommended)

- **MVP**: Phases 1+2+4+5 (T001..T028 — setup, verification, deletion sweep, simple-app demo + E2E).
- **Definition of done for MVP**: SC-001 + SC-002 + SC-003 + SC-005 + SC-006 are all green. The chart-default-preservation E2E assertion (FR-014a) passes against a real cluster. SC-004 (driver-author guide) is deferred to US4 (Phase 6).
- **Strictly out of scope for MVP**: layered template context, opinionated render macros, reintroducing platform-side injection — all codified as FR-024..FR-026.

## Validation checklist

- [ ] Every FR in `spec.md` maps to at least one task above (T038 enforces).
- [ ] Every retained GraphQL field/argument in 008+009's propagation matrix continues to have a passing assertion (Constitution §V).
- [ ] FR-014a is exercised by an explicit chart-default-preservation E2E assertion (T026).
- [ ] No tasks reference inline GraphQL strings (project rule).
- [ ] No tasks edit generated files manually.
- [ ] The deletion sweep grep (T022) returns zero hits in source code.
