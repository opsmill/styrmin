# Tasks: Environment-Config Update with Deployment Fanout

**Input**: Design documents from `/specs/009-environment-update/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/graphql.md, quickstart.md, critiques/critique-20260507-082602.md

**Tests**: Tests are **mandatory** for this feature per Constitution §V (Test-First Development) and `AGENTS.md` (E2E + GraphQL propagation tests are non-negotiable). The user explicitly called out two mandatory E2E scenarios (US1 headline + failure-isolation).

**Organization**: Tasks are grouped by user story so each story can be implemented and shipped as an independent MVP increment. P1 stories (US1+US2) together form the genuine MVP — backend correctness + structured input. US3+US4 are operator-UX wrappers that ship after the API is in place.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no incomplete dependencies)
- **[Story]**: Which user story this task belongs to (US1..US4)
- File paths are absolute-from-repo-root and exact

## Path Conventions

This is a **web service** project. Backend lives under `backend/styrmin_backend/` (Python); frontend under `frontend/src/` (React + TypeScript). Both are touched in this feature.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create new file skeletons every later phase consumes. No business logic yet.

- [X] T001 Create new module `backend/styrmin_backend/api/definitions/environment/inputs.py` with placeholder `UpdateEnvironmentInput` Strawberry input class (no fields yet) so imports resolve.
- [X] T002 [P] Create test stub at `backend/tests/unit/services/test_environment_update_inputs.py` with one passing placeholder test, so the file is wired into pytest collection.
- [X] T003 [P] Create test stub at `backend/tests/functional/graphql/test_environment_update_propagation.py` with one passing placeholder test (and the same `from .conftest import gql` / `from ._queries import load_query` imports the 008 propagation file uses, to lock the convention).
- [X] T004 [P] Create E2E test file `backend/tests/e2e/test_environment_update.py` with one passing `@pytest.mark.api_only` placeholder test, so the file is wired into pytest collection.
- [X] T005 [P] Create frontend component skeleton at `frontend/src/pages/environments/EnvironmentConfigurationTab.tsx` with a minimal placeholder export so the import resolves.
- [X] T006 [P] Create frontend component skeleton at `frontend/src/components/environment/EnvVarsForm.tsx` with a minimal placeholder export.
- [X] T007 [P] Create frontend component skeleton at `frontend/src/components/environment/RedeployConfirmDialog.tsx` with a minimal placeholder export.
- [X] T008 [P] Create frontend Vitest test stub at `frontend/src/__tests__/EnvVarsForm.test.tsx` with one passing placeholder.

**Checkpoint**: `uv run pytest --collect-only -q backend/tests/` collects the new paths without errors. `cd frontend && pnpm test --run` collects the new Vitest stub.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Extract shared helpers and verify reused infrastructure is intact. Every user story consumes these. No story can be implemented before this phase is complete.

- [ ] T009 Extract `redeploy_for_environment_update(deployment, uow) -> Task` helper in `backend/styrmin_backend/services/deployment.py`, mirroring the post-version-decision portion of `update_deployment_version` (data-model.md §2.3). The helper does NOT change the deployment's application_version, parameters, or service overrides — only regenerates the active instance against the deployment's current bound driver and returns the dispatched Task.
- [ ] T010 Add `_extract_environment_slice_from_context` helper in `backend/styrmin_backend/services/environments.py` (or `services/env_vars/resolver.py` if a more natural home exists) — reads the environment-scope config slice from a persisted `ApplicationInstance.context` JSON column. Used by per-deployment no-op detection in US1.
- [ ] T011 Add `_deployment_already_at_config(deployment, new_config) -> bool` helper in `backend/styrmin_backend/services/environments.py` per data-model.md §3 pseudocode. Compares the deployment's active-instance environment-config slice against the new config via the canonical Pydantic round-trip. Returns False when the deployment has no active instance.
- [ ] T012 [P] Verify `_prevalidate_environment_env_vars` and `validate_environment_config` from 008 are still wired correctly into `update_environment` and produce typed errors at the GraphQL boundary. Add a unit test at `backend/tests/unit/services/test_environments.py` (extend the existing file) that asserts an invalid env var name surfaces as `InvalidEnvVarNameError` (not `InvalidContextError`) when `update_environment` is called directly.
- [ ] T013 [P] Write unit tests at `backend/tests/unit/services/test_environments.py` (extend) for `_deployment_already_at_config`: positive case (active instance matches config), negative case (config differs by one env var), edge case (no active instance), edge case (canonical equality across `None`-vs-missing drift).

**Checkpoint**: `uv run pytest -q backend/tests/unit/services/test_environments.py` passes. `redeploy_for_environment_update` and the no-op helper are importable.

---

## Phase 3: US1 — Per-Deployment Redeploy Fanout (Priority: P1) 🎯 MVP

**Goal**: An `updateEnvironment(input=...)` call persists the env-config row, dispatches one redeploy Task per non-tombstoned, non-internal deployment in the environment whose active instance is not already at the new config, and emits structured log + metrics for ops observability. Per-deployment failures don't roll back the env-config row or affect peer deployments. Partial-fanout recovery works (a re-submission of the same input dispatches Tasks only for laggards).

**Independent Test**: Quickstart Steps 2 + 3 + 5 + 7.

**Dependencies**: Phase 2 (the helpers extracted there are load-bearing).

- [ ] T014 [US1] Rewrite `update_environment` in `backend/styrmin_backend/services/environments.py` to perform the fanout: persist the env-config row, commit the UoW, then iterate over deployments dispatching `redeploy_for_environment_update` per per-deployment no-op decision. **Commit before dispatch** (FR-009a). Tombstoned (`deployment.deletion_requested`) and internal (`deployment.internal`) deployments are excluded from the fanout (FR-012, FR-013).
- [ ] T015 [US1] Wrap each `redeploy_for_environment_update` call in `try/except Exception` inside the fanout loop; on exception, increment `dispatch_failed` counter, log via `logger.exception("env_config_fanout_dispatch_error", environment_id=..., deployment_id=..., error=...)`, and continue (FR-008).
- [ ] T016 [US1] Emit one structured log entry per fanout dispatch via `logger.info("env_config_fanout_dispatched", environment_id=..., evaluated=..., dispatched=..., skipped_noop=..., dispatch_failed=...)` (FR-023). The log is emitted regardless of dispatched count (so true environment-wide no-ops still produce an audit entry with `dispatched=0`).
- [ ] T017 [US1] Emit metric `env_config_fanout_deployments_total{environment, outcome}` per deployment in the fanout, where `outcome` is one of `dispatched | skipped_noop | dispatch_failed` (FR-023a). Use the project's standard metric emission path; if no metric backend is wired today, document the integration point as a TODO and ensure the call site exists so the metric becomes available once the backend lands.
- [ ] T018 [US1] [P] Extend `backend/tests/unit/services/test_environments.py` with fanout-dispatch unit tests: 3 deployments all fresh (config is new for them) → 3 Tasks dispatched + log shows `dispatched=3`; 3 deployments where 2 are already at config + 1 isn't → 1 Task dispatched + log shows `dispatched=1, skipped_noop=2`; 3 deployments where 1 is tombstoned → 2 Tasks dispatched, tombstoned excluded; 3 deployments where 1 is internal → 2 Tasks dispatched.
- [ ] T019 [US1] [P] Extend `backend/tests/unit/services/test_environments.py` with **partial-fanout recovery** unit test: pre-seed environment with 3 deployments where deployment B's active instance is at config v1 and deployments A/C are at config v2; persist v2 (already current); call `update_environment` with v2 input → exactly one redeploy Task dispatched (for B); A/C are skipped. This is the regression test for critique X1.
- [ ] T020 [US1] [P] Extend `backend/tests/unit/services/test_environments.py` with **per-deployment failure isolation** unit test: mock `redeploy_for_environment_update` to raise on deployment B; assert env-config row persists, deployments A/C dispatch successfully, B is logged but does not propagate the exception out of `update_environment`.
- [ ] T021 [US1] [P] Extend `backend/tests/unit/services/test_environments.py` with **commit ordering** unit test: mock `apply_state` (or wherever the dispatch happens) to raise on first deployment; assert the env-config row was committed BEFORE the raise (verify by reading the row back through the same UoW).
- [ ] T022 [US1] Add a propagation test at `backend/tests/functional/graphql/test_environment_update_propagation.py` for **fanout-dispatch + mutation-result coupling**: pre-seed an environment with 2 deployments (one fresh, one tombstoned); call `updateEnvironment` mutation; assert mutation succeeds, exactly one new Task is created (the non-tombstoned one), and the env-config row reflects the new input.
- [ ] T023 [US1] Add a propagation test for **per-deployment no-op skip**: pre-seed environment + 2 deployments already at the target config; submit mutation with that config → mutation succeeds, zero new Tasks created.
- [ ] T024 [US1] Add a propagation test for **partial-fanout recovery**: pre-seed environment with 3 deployments where 2 are at v2 and 1 is at v1; submit mutation with v2 → exactly one new Task created (the v1 laggard).
- [ ] T025 [US1] Extend `backend/tests/e2e/test_environment_update.py` with the **US1 headline E2E** (Quickstart Steps 1-3): create an environment with 3 simple-app deployments; call `updateEnvironment` to set `OTEL_EXPORTER_OTLP_ENDPOINT`; within RECONCILE_TIMEOUT, assert all 3 deployments' pods carry the new env entry on container[0]; assert each deployment's timeline has a fresh entry whose `contextDiff` records the env-config change. Marked `@pytest.mark.api_only`.
- [ ] T026 [US1] Extend `backend/tests/e2e/test_environment_update.py` with the **US1 failure-isolation E2E** (Quickstart Step 7): set up an environment with 2 deployments where deployment B's chart will fail to render under a specific scheduling override; call `updateEnvironment` with that override + an env var; assert env-config row persists, deployment A converges, deployment B's timeline records a failed Task, peer deployments unaffected. Marked `@pytest.mark.api_only`. **May skip with explicit reason** if the multi-driver fixture isn't available — the test body must be fully written so unskipping is one-line.

**Checkpoint**: US1 is independently shippable. Submitting `update_environment` (still using `config: JSON` at this phase since US2 hasn't landed) fans out to all deployments correctly, with per-deployment no-op detection, partial-fanout recovery, and failure isolation working.

---

## Phase 4: US2 — Structured `UpdateEnvironmentInput` (Priority: P1) 🎯 MVP

**Goal**: The `updateEnvironment` mutation accepts a typed `UpdateEnvironmentInput!` argument instead of `config: JSON`. Every field of `EnvironmentConfig` has a corresponding input mirror. The SDK's regenerated client exposes `client.environments.update(environment_id, input=UpdateEnvironmentInput(...))`. Typed error codes (`INVALID_ENV_VAR_NAME`, etc.) survive the GraphQL boundary intact.

**Independent Test**: Quickstart Steps 2 + 6 (positive + negative).

**Dependencies**: Phase 2. Independent of Phase 3 — but pragmatically lands together because both target the same mutation surface and the breaking-change clean-replace requires touching all callers in one PR.

- [ ] T027 [US2] Define `EnvVarInput` Strawberry input in `backend/styrmin_backend/api/definitions/environment/inputs.py`: `name: str`, `value: str`. Reuse the same shape used (if any) by `008-deployment-env-vars`'s SDK input types; otherwise define here.
- [ ] T028 [US2] Define `UpdateEnvironmentInput` Strawberry input in `inputs.py` with the top-level fields per `data-model.md §1.1`: `env_vars: list[EnvVarInput] | None`, `ip_whitelist: list[str] | None`, `dedicated_ingress: DedicatedIngressInput | None`, `scheduling: SchedulingInput | None`, `fqdn_suffix: str | None`, `external_url_scheme: ExternalUrlScheme | None`, `external_url_port: int | None`, `external_dns_endpoints_type: ExternalDnsEndpointsType | None`. All fields default to `None` to support nullable input shape (full-replacement semantics: missing field → unset on persisted row).
- [ ] T029 [US2] Define nested `DedicatedIngressInput` Strawberry input in `inputs.py` mirroring `DedicatedIngressConfig` (Pydantic) field-for-field.
- [ ] T030 [US2] Define nested `SchedulingInput`, `AffinityBlockInput`, `ResourceRequirementsInput`, `ResourceSpecInput`, `TolerationInput`, `TopologySpreadConstraintInput`, `PostRenderInjectionInput` Strawberry inputs in `inputs.py` per `data-model.md §1.2`. Each mirrors its Pydantic counterpart from `backend/styrmin_backend/context/models/config.py`.
- [ ] T031 [US2] Define Strawberry enum mirrors for `ExternalUrlScheme`, `ExternalDnsEndpointsType`, `TolerationOperator`, `TolerationEffect`, `WhenUnsatisfiable` (Pydantic enums or `Literal` types in `EnvironmentConfig`). Place in `inputs.py` or in a sibling `enums.py` if the project's convention is to separate enums.
- [ ] T032 [US2] Implement `update_environment_input_to_dict(input: UpdateEnvironmentInput) -> dict` helper in `inputs.py` that converts a Strawberry input into a dict suitable for `EnvironmentConfig.model_validate(...)`. Handles None-vs-empty-list semantics correctly (a `None` env_vars field means "unset" not "empty list").
- [ ] T033 [US2] Rewrite the `Mutation.update_environment` resolver in `backend/styrmin_backend/api/schema/mutation.py`: replace the `config: JSON | None = None` argument with `input: UpdateEnvironmentInput!`. Convert input → dict → `EnvironmentConfig.model_validate(...)` (the `_prevalidate_environment_env_vars` helper still runs ahead of `model_validate` to surface typed env-var errors). Pass the validated config to the service-layer `update_environment` (which already does the fanout per Phase 3).
- [ ] T034 [US2] Verify `_prevalidate_environment_env_vars` is invoked **before** `EnvironmentConfig.model_validate` in the new resolver path — same order as the post-008 path. Add or extend a unit test at `backend/tests/unit/services/test_environments.py` to pin this ordering (an invalid env var name in the input must produce `INVALID_ENV_VAR_NAME` not `INVALID_CONTEXT`).
- [ ] T035 [US2] [P] Regenerate `schema.graphql` (`uv run styrmin export graphql-schema schema.graphql`). Diff should show: (a) new `UpdateEnvironmentInput` + nested input types + enum mirrors; (b) `Mutation.updateEnvironment(environmentId, input)` replacing the old `Mutation.updateEnvironment(environmentId, config)` argument signature. Commit the regenerated file.
- [ ] T036 [US2] [P] Regenerate SDK Pydantic types (`uv run invoke generate`). The SDK's `EnvironmentResource.update` method signature changes from `(environment_id, config: dict)` to `(environment_id, input: UpdateEnvironmentInput)`. Commit the regenerated `python_sdk/src/styrmin_sdk/graphql/_generated/` output and the frontend's regenerated `frontend/src/generated/graphql.ts`.
- [ ] T037 [US2] Update `python_sdk/src/styrmin_sdk/resources/environments.py` `update` method to accept the typed `UpdateEnvironmentInput` (Pydantic, regenerated by codegen) and pass it through to the GraphQL client. Remove the old `config: dict` parameter cleanly (FR-024 — no deprecation window).
- [ ] T038 [US2] [P] Update every internal caller of `client.environments.update(...)` to use the new typed input shape. Search for usages: `grep -rn "environments.update\|updateEnvironment" backend/tests/ python_sdk/ frontend/src/ --include="*.py" --include="*.ts" --include="*.tsx" --include="*.graphql"`. Update each call site to construct an `UpdateEnvironmentInput` from the existing config + the new fields.
- [ ] T039 [US2] [P] Update `backend/tests/functional/graphql/operations/update_environment.graphql` (and `python_sdk/src/styrmin_sdk/graphql/update_environment.graphql` if it exists) to use the new `input: UpdateEnvironmentInput!` argument. Re-run codegen if the operation file changes affect generated types.
- [ ] T040 [US2] [P] Implement unit tests at `backend/tests/unit/services/test_environment_update_inputs.py` for the input-conversion helper: every top-level field of `UpdateEnvironmentInput` round-trips through `update_environment_input_to_dict` → `EnvironmentConfig.model_validate(...)` cleanly; nested optionals unset correctly when the input field is `None`; full-replacement semantics tested (input with `env_vars=[X]` and missing `ip_whitelist` → persisted config has `env_vars=[X]` and unset `ip_whitelist`).
- [ ] T041 [US2] Add propagation tests at `backend/tests/functional/graphql/test_environment_update_propagation.py` for **every new top-level input field** per the `contracts/graphql.md §4` matrix: `envVars`, `ipWhitelist`, `fqdnSuffix`, `externalUrlScheme`, `externalUrlPort`, `externalDnsEndpointsType`, `dedicatedIngress`, `scheduling`. One assertion per row: write through the typed mutation → DB read-back → query projection.
- [ ] T042 [US2] Add propagation tests at `backend/tests/functional/graphql/test_environment_update_propagation.py` for **every nested input field** of `DedicatedIngressInput` and `SchedulingInput`. The test pattern: write through `updateEnvironment(input: { scheduling: { runtimeClass: "kata" } })` → query `Environment.config` → assert the `runtimeClass` field projects correctly. One row per nested field per the matrix.
- [ ] T043 [US2] Add propagation tests for the **3 error-code rejection paths** at `test_environment_update_propagation.py`: `INVALID_ENV_VAR_NAME` (regex violation in input), `ENV_VAR_SIZE_LIMIT_EXCEEDED` (oversized value), `DUPLICATE_ENV_VAR_NAME` (duplicate names in input list). Each test asserts `extensions.code` matches and the underlying env-config row is unchanged.
- [ ] T044 [US2] Add propagation test for **full-replacement semantics**: pre-seed environment with `ipWhitelist: ["10.0.0.0/8"]`. Submit `updateEnvironment(input: { envVars: [...] })` (omitting `ipWhitelist`). Assert persisted `Environment.config` shows `ipWhitelist: []` (cleared).
- [ ] T045 [US2] Add propagation test for **`ENVIRONMENT_NOT_FOUND` rejection**: submit mutation with a random `environmentId`. Assert `extensions.code = "ENVIRONMENT_NOT_FOUND"`, no DB writes occur, no Tasks dispatched.
- [ ] T046 [US2] Confirm the schema change has zero remaining references to `config: JSON` on `Mutation.updateEnvironment`: run `grep -rn "updateEnvironment.*config" backend/ python_sdk/ frontend/src/ --include="*.py" --include="*.ts" --include="*.tsx" --include="*.graphql"` and verify all hits use the new shape (FR-024).
- [ ] T047 [US2] Extend the E2E test at `backend/tests/e2e/test_environment_update.py` with the **typed-input rejection scenario** (Quickstart Step 6): submit `updateEnvironment(input: { envVars: [{name: "1invalid", value: "y"}] })` via the regenerated SDK — assert the GraphQL response carries an error with `extensions.code = "INVALID_ENV_VAR_NAME"`. Marked `@pytest.mark.api_only`.

**Checkpoint**: The MVP (US1+US2) is shippable. Mutation accepts typed input, fans out to all deployments correctly with per-deployment no-op detection, surfaces typed errors precisely, and the SDK exposes the typed API.

---

## Phase 5: US3 — Frontend Configuration Tab (Read-Only) (Priority: P2)

**Goal**: An operator opens the environment detail page, clicks the new "Configuration" tab, and sees the full environment configuration rendered in structured sections. Empty/unset fields show explicit "no overrides set" messaging rather than blank panels.

**Independent Test**: Quickstart Step 8.

**Dependencies**: Phase 2 (the GraphQL projection of `Environment.config` is already in place post-008; this phase consumes it).

- [ ] T048 [US3] Implement `EnvironmentConfigurationTab.tsx` in `frontend/src/pages/environments/EnvironmentConfigurationTab.tsx`: takes `environmentId`, `config`, `deployments` as props. Renders sections in a vertical layout: Environment Variables, IP Allowlist, Dedicated Ingress, Scheduling, FQDN/External-URL Settings.
- [ ] T049 [US3] Each section reads its slice of `config` and renders content OR an empty state ("no overrides set" with appropriate phrasing per section) per FR-015. Use the project's existing `EmptyState` component for consistency.
- [ ] T050 [US3] Add `Configuration` to the `TABS` array in `frontend/src/pages/environments/EnvironmentDetailPage.tsx` and wire the new tab content to render `<EnvironmentConfigurationTab>` when active.
- [ ] T051 [US3] [P] Update `frontend/src/graphql/get_environment.graphql` if needed to ensure the `Environment.config` field is fully projected (with all nested sub-fields the configuration tab needs). Regen frontend types via `cd frontend && pnpm codegen` if the projection changed.
- [ ] T052 [US3] [P] Add a Vitest test at `frontend/src/__tests__/EnvironmentConfigurationTab.test.tsx` covering: an environment with multiple sections populated renders all sections; an environment with empty sections renders empty-state messages; the page does not crash on a partially-populated config.

**Checkpoint**: US3 is independently shippable. Operators can read the full environment config via the new tab without dropping into the SDK.

---

## Phase 6: US4 — Frontend Env-Vars Edit Form (Priority: P2)

**Goal**: An operator can add, edit, or remove environment-scope env vars from the Configuration tab. Client-side validation matches the backend rules. On submit, a confirmation dialog explicitly names the count of deployments that will be redeployed; on confirm, the form posts via the typed mutation and refreshes page state.

**Independent Test**: Quickstart Step 9.

**Dependencies**: US3 (the form embeds in the Configuration tab) + US2 (the typed mutation surface the form submits to).

- [ ] T053 [US4] Implement `EnvVarsForm.tsx` in `frontend/src/components/environment/EnvVarsForm.tsx`: takes `initialEnvVars`, `deployments`, `onSubmit` props. Manages local row state per `data-model.md §7.2`. Add/edit/remove rows; live-validation per row; running total bytes for the per-scope cap.
- [ ] T054 [US4] Implement client-side validation in `EnvVarsForm.tsx` mirroring backend rules (FR-018): name regex `^[A-Za-z_][A-Za-z0-9_]*$`, per-value 64 KiB cap, per-scope 100 entries / 256 KiB total, no duplicate names. Inline error display per row; submit button disabled when any row has errors or globalError is set.
- [ ] T055 [US4] Implement `RedeployConfirmDialog.tsx` in `frontend/src/components/environment/RedeployConfirmDialog.tsx` per `data-model.md §7.3`: takes `open`, `deploymentCount`, `deploymentNames`, `onConfirm`, `onCancel`. Renders count + name list (truncated past 5 names). Cancel + Redeploy buttons. Always shown on Save (even when count is 0; in that case the dialog states "No deployments will be redeployed").
- [ ] T056 [US4] Wire `EnvVarsForm` into `EnvironmentConfigurationTab` (US3): the env vars section becomes editable; clicking Save opens the `RedeployConfirmDialog`; confirming triggers submission via the regenerated SDK / generated GraphQL hook (`useUpdateEnvironmentMutation`). On success, refresh the page's environment query.
- [ ] T057 [US4] Implement form-state retention on submit failure (FR-021): when the mutation fails (network error, server error, validation rejection), the form retains the operator's edits, displays an error notice, and allows retry. Use the project's existing toast/notification component for errors.
- [ ] T058 [US4] [P] Build the full-replacement input correctly in the form's submit handler: read the current persisted config, replace only the `env_vars` field with the form's edited rows, preserve all other fields (ipWhitelist, scheduling, etc.) unchanged. The full-replacement semantics (FR-003) means the form MUST re-include unchanged fields or they get cleared.
- [ ] T059 [US4] [P] Add a Vitest test at `frontend/src/__tests__/EnvVarsForm.test.tsx` covering: add row → validates → enables submit; invalid name → inline error + submit disabled; duplicate name → inline error + submit disabled; oversized value → inline error + submit disabled; clicking Save with valid rows → opens dialog; clicking Cancel in dialog → form remains in edited state; clicking Redeploy → calls onSubmit with full env-vars payload.
- [ ] T060 [US4] [P] Add a Vitest test at `frontend/src/__tests__/RedeployConfirmDialog.test.tsx` covering: zero deployments → "No deployments will be redeployed" message + Redeploy button enabled; 1 deployment → name displayed; 5+ deployments → "and N more" truncation.
- [ ] T061 [US4] Extend the E2E test at `backend/tests/e2e/test_environment_update.py` with the **US4 form E2E** (Quickstart Step 9), marked `[ui-chromium]` only (the form is UI-only). Use the Playwright page-object patterns from existing UI E2E tests. Steps: navigate to environment detail → Configuration tab → add env var → Save → confirm → assert page refreshes with new state. **May skip with explicit reason** if the existing Playwright fixtures don't support multi-deployment environments yet.

**Checkpoint**: US4 is independently shippable. Operators can edit env vars from the UI, with full-replacement semantics correctly preserved and explicit redeploy confirmation.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, full-suite validation, code-quality gates.

- [ ] T062 [P] Update `dev/knowledge/backend/api.md` to reflect the new `Mutation.updateEnvironment(input: UpdateEnvironmentInput!)` signature. Remove any references to the old `config: JSON` argument.
- [ ] T063 [P] Update `dev/knowledge/backend/services.md` to mention the env-config fanout in the services-layer overview (one-liner pointing to `update_environment` + `redeploy_for_environment_update`). Add the new `redeploy_for_environment_update` helper to relevant indexes.
- [ ] T064 [P] Append a section to `dev/adr/adr-019-deployment-env-vars.md` (or create a new ADR `dev/adr/adr-020-environment-config-fanout.md` — implementer's choice depending on whether the design feels novel enough to warrant its own ADR) documenting: per-deployment no-op detection (vs mutation-level skip), full-replacement vs incremental-update v1 choice, structured-input migration strategy (clean replace).
- [ ] T065 [P] Run the full GraphQL propagation test suite (`uv run pytest backend/tests/functional/graphql/test_environment_update_propagation.py -v`) and confirm every row in `contracts/graphql.md §4` has a passing assertion.
- [ ] T066 [P] Run `uv run invoke format lint` and resolve any violations.
- [ ] T067 [P] Run `uv run invoke validate-graphql` to confirm every new `.graphql` file passes schema validation.
- [ ] T068 [P] Confirm `schema.graphql` and the generated SDK + frontend types are checked in and consistent (no drift after a fresh `uv run invoke generate`).
- [ ] T069 [P] Run `cd frontend && pnpm test --run` and confirm all Vitest tests pass.
- [ ] T070 Run the full E2E suite (`uv run pytest backend/tests/e2e/test_environment_update.py -v -s --pdb`) against a real Kind/vCluster and observe a green run, per Constitution §V (E2E is part of the definition of done). If skipped scenarios exist (per T026 / T061 deferral), document them in the final report.
- [ ] T071 Final cross-check: every FR in `spec.md` Requirements section is wired to at least one task in this list. Items intentionally deferred should match `spec.md` Out of Scope only. Any FR without a task is a gap.

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
US1 (Phase 3) ◄── MVP slice 1/2 — backend correctness
   │
   ▼
US2 (Phase 4) ◄── MVP slice 2/2 — typed input
   │
   ▼ (US3 + US4 depend on US2's typed mutation surface)
   │
   ├──► US3 (Phase 5) ◄── frontend read view
   │       │
   │       ▼
   │     US4 (Phase 6) ◄── frontend edit form
   │
   ▼
Polish (Phase 7)
```

**Note**: US1 and US2 logically can be implemented independently against the post-008 baseline (US1 wires the fanout into the existing JSON-blob `update_environment`; US2 swaps the JSON-blob path for the typed input), but they must ship together because the breaking schema change forces all callers to update at the same time. Treat US1+US2 as one merge unit for the MVP.

### Within-phase parallelism

- **Phase 1 (Setup)**: T002, T003, T004, T005, T006, T007, T008 are all `[P]` — different files, no inter-task dependencies.
- **Phase 2 (Foundational)**: T012, T013 are `[P]` — different files / extend the existing test file in different test classes.
- **Phase 3 (US1)**: T018, T019, T020, T021 are `[P]` — different test methods; codegen tasks elsewhere are sequenced.
- **Phase 4 (US2)**: T035, T036, T038, T039, T040 are `[P]` — different files / different operations.
- **Phase 5 (US3)**: T051, T052 are `[P]`.
- **Phase 6 (US4)**: T058, T059, T060 are `[P]`.
- **Phase 7 (Polish)**: T062, T063, T064, T065, T066, T067, T068, T069 are all `[P]` — independent doc/validation tasks.

### Implementation strategy

1. **Land the MVP first** — drive Phase 1 → Phase 2 → Phase 3 (US1) → Phase 4 (US2) end-to-end including the propagation suite + E2E pass. **Do not move on until the MVP E2E is green** (Constitution §V).
2. **Ship US3 + US4 in sequence** after the MVP merges — both are frontend-only and depend on the typed mutation surface from US2.
3. **Polish last** — the full-suite runs and FR cross-check catch any last gaps before merge.

## MVP Scope (recommended)

- **MVP**: Phase 1 → Phase 2 → US1 → US2 (excludes US3, US4, and polish).
- **Definition of done for MVP**: All FRs except FR-014..FR-022 (frontend) are wired. The MVP E2E covers Quickstart Steps 1-7 inclusive (positive + negative paths for the typed mutation, plus the partial-fanout-recovery scenario).
- **Strictly out of scope for MVP**: incremental-update mutation, env-var-name autocomplete, optimistic concurrency control, parent Prefect flow for the fanout, surfacing per-deployment failures in the mutation envelope (per spec Out of Scope).

## Validation checklist

- [ ] Every FR in `spec.md` maps to at least one task above (T071 enforces).
- [ ] Every new GraphQL field/argument in `contracts/graphql.md §4` has a propagation test (Constitution §V).
- [ ] Every user story has at least one E2E assertion in `backend/tests/e2e/test_environment_update.py` (Constitution §V).
- [ ] No tasks reference inline GraphQL strings (project rule: all queries in `.graphql` files).
- [ ] No tasks edit generated files manually (boundary: `schema.graphql`, `python_sdk/src/styrmin_sdk/graphql/_generated/`, `frontend/src/generated/graphql.ts` are regenerated, never hand-edited).
