---
description: "Task list for Typed UpdateDeploymentInput GraphQL Surface"
---

# Tasks: Typed `UpdateDeploymentInput` GraphQL Surface

**Input**: Design documents from `specs/011-typed-deployment-input/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/graphql.md, quickstart.md

**Tests**: REQUIRED. Constitution §V mandates an E2E for every new feature plus per-field GraphQL ↔ DB propagation tests. Test tasks are interleaved with their implementation tasks below.

**Organization**: One P1 user story; tasks are organized by lifecycle phase (Setup → Foundational → US1 → Polish). No parallel user stories.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks).
- **[Story]**: Tagged on User Story phase tasks only (US1).
- Every task carries an exact file path.

## Path Conventions

Web-application repository:

- Backend: `backend/styrmin_backend/...`, `backend/tests/...`
- Frontend: `frontend/src/...`
- Python SDK: `python_sdk/src/styrmin_sdk/...`, `python_sdk/tests/...`
- Schema: `schema.graphql` (repo root)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Ensure local environment is ready for codegen + lint cycles. No project init needed (existing repo).

- [X] T001 Run `uv sync` and `cd frontend && pnpm install` from the repository root to ensure both toolchains are warmed up (codegen depends on both).
- [X] T002 Verify pre-commit hooks installed: `uv run invoke pre-commit-install` (idempotent).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared module + new typed errors + new input definitions + conversion helper. Everything in Phase 3 depends on these.

**⚠️ CRITICAL**: No User Story 1 task can begin until this phase is complete.

### 2.1 New typed errors

- [X] T003 [P] Add `DuplicateParameterNameError(ServiceError)` with `error_code = "DUPLICATE_PARAMETER_NAME"` and a `name: str` payload field, in a new file `backend/styrmin_backend/services/parameters/exceptions.py` (create the `parameters/` package directory if it doesn't already exist; if `services/parameters.py` is a single file, refactor it into a `parameters/` package with `__init__.py` re-exporting today's public names).
- [X] T004 [P] Add `DuplicateComponentNameError(ServiceError)` with `error_code = "DUPLICATE_COMPONENT_NAME"` and a `name: str` payload field, alongside the existing `DuplicateEnvVarNameError` in `backend/styrmin_backend/services/env_vars/exceptions.py`.

### 2.2 Shared-leaf extraction

- [X] T005 Create the new module directory `backend/styrmin_backend/api/definitions/config/` with an empty `__init__.py`.
- [X] T006 Move the shared leaf inputs and the `_convert_value` recursive helper from `backend/styrmin_backend/api/definitions/environment/inputs.py` into a new `backend/styrmin_backend/api/definitions/config/inputs.py`. The shared leaves to move are: `EnvVarInput`, `LabelSelectorInput`, `LabelSelectorRequirementInput`, `DeploymentReferenceInput`, `AffinityTermInput`, `WeightedAffinityTermInput`, `AffinityBlockInput`, `ResourceSpecInput`, `ResourceRequirementsInput`, `TolerationInput`, `TopologySpreadConstraintInput`, `PostRenderInjectionInput`, `SchedulingInput`, `IngressServiceConfigInput`, `DedicatedIngressInput`, and the enum mirrors `ExternalUrlScheme`, `ExternalDnsEndpointsType`, `TolerationOperator`, `TolerationEffect`, `WhenUnsatisfiable`, `LabelSelectorOperator`. Also move `_convert_value` and `_is_unset_or_none`. Preserve every `description=` argument verbatim.
- [X] T007 In `backend/styrmin_backend/api/definitions/environment/inputs.py`, replace the in-file definitions of the leaves moved by T006 with imports from `styrmin_backend.api.definitions.config.inputs`. `UpdateEnvironmentInput`, `update_environment_input_to_dict`, and the `__all__` re-export list stay in place (re-export the imported symbols so the module's public surface is unchanged).

### 2.3 New `StandardStorageInput` leaf

- [X] T008 Add `StandardStorageInput` to `backend/styrmin_backend/api/definitions/config/inputs.py` mirroring the `StandardStorage` Pydantic model: single required field `storage_class: str`, carrying a non-empty `description="The Kubernetes storage class name used as the standard storage option for this cluster."`.

### 2.4 New deployment-input module

- [X] T009 Create `backend/styrmin_backend/api/definitions/deployment/inputs.py` (new file alongside the existing `model.py`). Define `ParameterValueInput` (`name: str`, `value: JSON`), `ComponentConfigInput` (`name: str`, `env_vars: list[EnvVarInput] | None`), and the top-level `UpdateDeploymentInput` mirroring the field set in `data-model.md` §1.1 (17 fields). Reuse the leaf inputs by importing them from `styrmin_backend.api.definitions.config.inputs`. Reuse `ServiceNameOverride` unchanged by importing from `styrmin_backend.api.definitions.service.model`. Every field on all four new inputs MUST carry a non-empty `description=...` argument (FR-012).
- [X] T010 In the same `deployment/inputs.py`, implement `update_deployment_input_to_dict(input: UpdateDeploymentInput) -> dict[str, Any]` per the pseudocode in `data-model.md` §4. Reuse the imported `_convert_value` helper. Implement the four flatten branches: `env_vars` (scope `"deployment"`), `parameters` (raises `DuplicateParameterNameError`), `components` (raises `DuplicateComponentNameError`; per-component env-vars flatten with scope `f"component:{name}"`), and `service_name_overrides` (list-of-`{driver_service_name, override_name}` → `dict`).

**Checkpoint**: Foundation ready. The resolver in Phase 3 can now consume these types and the helper without missing pieces.

---

## Phase 3: User Story 1 — Typed `UpdateDeploymentInput` replaces JSON-blob args (Priority: P1) 🎯 MVP

**Goal**: Replace the four loose `updateDeployment` arguments (`name`, `config: JSON`, `parameters: JSON`, `serviceNameOverrides: [ServiceNameOverride!]`) with a single typed `input: UpdateDeploymentInput!` argument. Regenerate the SDK + frontend codegen. Retarget every in-tree caller and test to the new shape. Ship the introspection, propagation, error-propagation, and E2E tests required by Constitution §V.

**Independent Test**: After the phase completes, an SDK consumer can call `client.deployments.update(deployment_id, input=UpdateDeploymentInput(...))` end-to-end against a running stack with the new E2E `test_update_deployment_typed_input_propagates_component_env_var_and_scheduling` green, and an introspection query against the live schema returns the new argument shape with zero JSON-typed args at the top of `updateDeployment`.

### 3.1 Resolver

- [X] T011 [US1] Update `backend/styrmin_backend/api/schema/mutation.py` `update_deployment` resolver (currently at `mutation.py:761-788`) to accept `(deployment_id: UUID, input: UpdateDeploymentInput, info: strawberry.Info)`. Inside the resolver, call `update_deployment_input_to_dict(input)`, then `pop` `name` / `parameters` / `service_name_overrides` off the result, treat the remainder as `deployment_config`, and forward to the existing `update_deployment` service function unchanged. Preserve the existing `InternalDeploymentError` check ahead of input conversion. Drop the four old keyword arguments and the import of `ServiceNameOverride` from this file if it's not still used elsewhere in the module (it is — keep the import).

### 3.2 Schema + SDK regeneration

- [ ] T012 [US1] Regenerate `schema.graphql` from repo root: `uv run styrmin export graphql-schema schema.graphql`. Confirm the `updateDeployment` mutation argument list shows `(deploymentId: UUID!, input: UpdateDeploymentInput!)` and that `UpdateDeploymentInput`, `ComponentConfigInput`, `ParameterValueInput`, and `StandardStorageInput` types are present.
- [ ] T013 [US1] Update `python_sdk/src/styrmin_sdk/graphql/update_deployment.graphql` to match the new signature: `mutation UpdateDeployment($deploymentId: UUID!, $input: UpdateDeploymentInput!) { updateDeployment(deploymentId: $deploymentId, input: $input) { id status type message deploymentId } }`.
- [ ] T014 [US1] Regenerate SDK types: `uv run invoke generate`. Confirm `python_sdk/src/styrmin_sdk/graphql/_generated/update_deployment.py` and `_generated/input_types.py` include `UpdateDeploymentInput` and the four new types as Pydantic models with type-hinted fields.
- [ ] T015 [US1] Update `python_sdk/src/styrmin_sdk/resources/deployments.py` `update(...)` method to accept `input: UpdateDeploymentInput` instead of the four loose `name` / `config` / `parameters` / `service_name_overrides` keyword arguments. Forward `input` as the GraphQL variable.

### 3.3 Frontend codegen + helper + dialog

- [ ] T016 [US1] Update `frontend/src/graphql/update_deployment.graphql` to match the new mutation signature (same change as T013, plus the urql-flavoured variable declarations).
- [ ] T017 [US1] Regenerate frontend codegen: `cd frontend && pnpm run codegen`. Confirm `frontend/src/generated/graphql.ts` exports `UpdateDeploymentInput`, `ComponentConfigInput`, `ParameterValueInput`, `StandardStorageInput` as TS types and that `useUpdateDeploymentMutation()`'s variable type now expects `{ deploymentId; input }`.
- [ ] T018 [US1] [P] Create `frontend/src/lib/deployment-input.ts` exporting `deploymentConfigToInput(config: DeploymentConfig): UpdateDeploymentInput` that converts the read-API config (dict-shaped `envVars` and `components`) to the typed input list-shape, preserving every other field. Document the conversion rules in a short JSDoc comment.
- [ ] T019 [US1] Update `frontend/src/components/deployment/scheduling/SchedulingConfigDialog.tsx` `handleSubmit()` (currently at lines 67-87) to use `deploymentConfigToInput(currentConfig)`, mutate the resulting `input.scheduling`, and submit. Preserves today's "submitting the scheduling dialog does not affect env vars / IP allowlist" behaviour under the new full-replacement contract.

### 3.4 Backend test retargeting (existing tests, semantic-equivalence)

- [ ] T020 [US1] [P] Update `backend/tests/functional/graphql/operations/update_deployment.graphql` and `update_deployment_config.graphql` to the new mutation signature shape.
- [ ] T021 [US1] [P] Retarget call sites in `backend/tests/functional/graphql/test_deployment.py` to the new input shape.
- [ ] T022 [US1] [P] Retarget call sites in `backend/tests/functional/graphql/test_env_vars_propagation.py` to the new input shape.
- [ ] T023 [US1] [P] Retarget call sites in `backend/tests/functional/test_api_scheduling_config.py` to the new input shape.
- [ ] T024 [US1] [P] Retarget helper functions in `backend/tests/functional/helpers.py` that build `updateDeployment` payloads to the new input shape.

### 3.5 E2E retargeting (existing tests)

- [ ] T025 [US1] [P] Retarget `backend/tests/e2e/drivers/api_driver.py` (the SDK-backed entrypoint) to call `client.deployments.update(deployment_id, input=UpdateDeploymentInput(...))`. Update the corresponding method signature in `backend/tests/e2e/drivers/protocol.py` (the abstract base) and `backend/tests/e2e/drivers/ui_driver.py` (the Playwright-backed entrypoint).
- [ ] T026 [US1] [P] Retarget call sites in `backend/tests/e2e/test_pod_scheduling.py` to use the updated driver entrypoint signature.
- [ ] T027 [US1] [P] Retarget call sites in `backend/tests/e2e/test_deployment_env_vars.py` to use the updated driver entrypoint signature.

### 3.6 SDK test retargeting

- [ ] T028 [US1] [P] Retarget `python_sdk/tests/test_deployments.py` to call `update(deployment_id, input=UpdateDeploymentInput(...))` and assert against the typed-model fields rather than dicts.

### 3.7 New tests (Constitution §V mandatory)

- [ ] T029 [US1] Create `backend/tests/functional/graphql/test_update_deployment_input_introspection.py` with the three tests from `contracts/graphql.md` §6: `test_update_deployment_input_field_coverage`, `test_update_deployment_arguments_have_no_json_typed_args`, `test_update_deployment_input_fields_have_descriptions`.
- [ ] T030 [US1] Create `backend/tests/functional/graphql/test_update_deployment_input_propagation.py` with one parametrized test function `test_update_deployment_input_field_propagates` driving the 22-row matrix from `contracts/graphql.md` §4 via `pytest.mark.parametrize`. Rows 02 (parameters merge) and 04 (components.envVars) need bespoke assertion bodies — implement those as separate parametrized fixtures or as their own test functions.
- [ ] T031 [US1] Create `backend/tests/functional/graphql/test_update_deployment_input_errors.py` with one parametrized test function `test_update_deployment_input_error_code` driving the 9-row error matrix from `contracts/graphql.md` §5 via `pytest.mark.parametrize`. Each case asserts `response.errors[0]['extensions']['code']` matches the expected typed code.
- [ ] T032 [US1] Create `backend/tests/e2e/test_deployment_typed_input.py` with the new E2E `test_update_deployment_typed_input_propagates_component_env_var_and_scheduling` per `research.md` §7. Mark `@pytest.mark.api_only(reason="SDK-driven; no UI flow exercised — the [ui-chromium] variant would just re-run the same SDK call.")` and `@pytest.mark.ci`.

### 3.8 New frontend tests

- [ ] T033 [US1] [P] Create `frontend/src/lib/deployment-input.test.ts` covering `deploymentConfigToInput()` per `plan.md` "Frontend Testing Scope": (a) empty config → empty input, (b) config with `envVars` dict → input with `envVars` list, (c) config with `components` dict → input with `components` list, (d) fully populated config → all fields preserved in the converted input.
- [ ] T034 [US1] [P] Add dialog integration tests to `frontend/src/components/deployment/scheduling/SchedulingConfigDialog.test.tsx` (create the file if absent): (a) submitting a new scheduling block sends the typed input with all pre-existing config fields preserved, (b) explicit no-regression test asserting submission does NOT clear `envVars`, `ipWhitelist`, or `components`.

### 3.9 Validation

- [ ] T035 [US1] Run `uv run invoke validate-graphql` from repo root; assert it passes for the updated `.graphql` operation files.
- [ ] T036 [US1] Run `uv run invoke format lint` from repo root; assert clean.
- [ ] T037 [US1] Run `cd frontend && pnpm lint && pnpm test` from repo root; assert clean.
- [ ] T038 [US1] Run the new E2E to a pass: `sleep infinity | uv run pytest backend/tests/e2e/test_deployment_typed_input.py -v -s --pdb 2>&1 | tee /tmp/pdb.log` (per AGENTS.md non-interactive shell guidance). Capture timing and confirm the assertions described in T032 actually fire.

**Checkpoint**: User Story 1 complete. The new typed input is the only way to call `updateDeployment`; the SDK, frontend, and every in-tree test exercise the new shape; all four success criteria (SC-001 through SC-004) are verifiable from a green test suite.

---

## Phase 4: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, release notes, and stale-reference clean-up.

- [ ] T039 [P] Grep `docs/` for stale references to the old signature: `grep -rn "config: JSON\|parameters: JSON\|updateDeployment(name" docs/`. Update any matches to reference the new typed-input shape; if zero matches, leave a one-line note in the PR description confirming the audit found nothing.
- [ ] T040 [P] Update `python_sdk/CHANGELOG.md` (create the file if absent) with a `## Unreleased` entry describing the `client.deployments.update(...)` signature change, including a before/after code snippet pulled from `quickstart.md`. Required for external SDK consumer signal (X1).
- [ ] T041 [P] Update the project release notes (`CHANGELOG.md` at repo root, or whatever the project convention is) with a `Breaking changes` entry under the next-release header, calling out the `updateDeployment` mutation argument-list change with a before/after schema snippet.
- [ ] T042 Run the full backend test suite once to confirm no unrelated regression: `uv run invoke test`. Investigate and fix any failure.

---

## Dependency Graph

```text
Phase 1 (Setup)
   ↓
Phase 2 (Foundational)
   ├─ T003 [P] (parameter exceptions)
   ├─ T004 [P] (component exceptions)
   └─ T005 → T006 → T007 → T008 → T009 → T010 (definitions chain)
   ↓
Phase 3 (US1) — 3.1 must complete before 3.2; 3.2 must complete before 3.3, 3.4, 3.5, 3.6
   ├─ T011 (resolver)            ← depends on T009, T010
   ├─ T012 (schema regen)        ← depends on T011
   ├─ T013 → T014 → T015         (SDK chain, depends on T012)
   ├─ T016 → T017                (frontend codegen chain, depends on T012)
   ├─ T018 → T019                (frontend helper chain)
   ├─ T020–T024 [P]              (backend tests retarget, depend on T012)
   ├─ T025 → T026, T027 [P]      (E2E driver + tests, depend on T015)
   ├─ T028 [P]                   (SDK test retarget, depends on T015)
   ├─ T029, T030, T031, T032     (new tests, depend on T011 + T015)
   ├─ T033, T034 [P]             (new frontend tests, depend on T018 + T019)
   └─ T035–T038                  (validation gates, must run last in phase)
   ↓
Phase 4 (Polish)
   ├─ T039 [P]
   ├─ T040 [P]
   ├─ T041 [P]
   └─ T042
```

## Parallel Execution Examples

Within Phase 2, T003 / T004 / T005 can launch in parallel (different files); the definitions chain (T006 → T007 → T008 → T009 → T010) is sequential because each step depends on the file structure created by the previous one.

Within Phase 3:

- After T012 lands, the SDK chain (T013–T015) and the frontend codegen chain (T016–T017) can launch in parallel.
- After T012 lands, the test-retarget tasks T020–T024 can run in parallel.
- After T015 lands, T025–T028 can run in parallel.
- After T018 + T019 land, T033 and T034 can run in parallel.

Within Phase 4, T039 / T040 / T041 are independent and can run in parallel; T042 must run last.

## Implementation Strategy

**MVP** = the entire Phase 3. There is no useful sub-slice to ship first; the typed input either replaces the JSON args or it doesn't. Splitting "backend lands first" / "SDK lands second" / "frontend lands third" creates a window where the wire shape disagrees between sides, breaking every `updateDeployment` call. Per `plan.md` "Rollout & Rollback", this is a **single-PR coordinated rollout** — all of Phase 3 lands together.

**Sequencing within Phase 3**: the practical order is:

1. T011 + T012 (resolver + schema regen) lock the wire shape.
2. T013–T015 + T016–T017 + T018–T019 (codegen + helper) bring both ends of the wire onto the new shape in parallel.
3. T020–T028 retarget the existing test suite so nothing breaks.
4. T029–T034 add the new Constitution-§V coverage.
5. T035–T038 are the validation gates that say "ready to merge".

**Definition of done for this feature**: every checkbox above is `[x]`, `uv run invoke format lint` clean, `pnpm lint && pnpm test` clean, `uv run invoke validate-graphql` clean, the full backend test suite (`uv run invoke test`) green, the new E2E green per T038, and the resulting PR carries the `Breaking changes` release-notes entry from T041.
