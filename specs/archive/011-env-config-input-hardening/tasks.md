# Tasks: Env-Config Input Completeness + Validator Hardening + UI Test Infrastructure

**Input**: Design documents from `/specs/011-env-config-input-hardening/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/graphql.md, quickstart.md, critiques/critique-20260509-112106.md

**Tests**: Tests are **mandatory** for this feature per Constitution §V (Test-First Development) and `AGENTS.md`. The schema-walking propagation test (FR-002), validator unit tests (FR-009), Vitest transform coverage (FR-004..FR-007), and the unskipped T061 UI E2E are all required.

**Organization**: Tasks are grouped by user story so each can be implemented independently. US1+US2 must ship in lockstep (they touch the same write path); US3 is independent; US4 ships last (depends on US2's transform existing for parity contract).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no incomplete dependencies)
- **[Story]**: Which user story this task belongs to (US1..US4)
- File paths are absolute-from-repo-root and exact

## Path Conventions

This is a **web service** project. Backend lives under `backend/styrmin_backend/`; backend tests under `backend/tests/`; frontend under `frontend/src/` (codegen + manual frontend changes); E2E driver infra at `backend/tests/e2e/drivers/`; documentation under `dev/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Minimal scaffolding for the new files this feature creates. The hardening pass is mostly small surgical edits; only the new error class needs file scaffolding upfront.

- [X] T001 [P] Verify `backend/tests/e2e/drivers/__init__.py`, `backend/tests/e2e/drivers/api_driver.py`, `backend/tests/e2e/drivers/ui_driver.py`, and `backend/tests/e2e/drivers/protocol.py` are all importable and the existing tests pass (`uv run pytest --collect-only -q backend/tests/e2e/`). This confirms the existing UI/API driver pattern is healthy before US4 extends it.

**Checkpoint**: project tooling baseline confirmed.

---

## Phase 2: US1 — UpdateEnvironmentInput Completeness (Priority: P1)

**Goal**: `UpdateEnvironmentInput` carries every public field of `EnvironmentConfig`. The two missing fields (`ingressClass`, `dbSize`) ship along with a schema-walking propagation test that prevents future drift.

**Independent Test**: Quickstart Steps 1+2.

- [X] T002 [US1] Add `ingress_class: str | None = strawberry.UNSET` and `db_size: str | None = strawberry.UNSET` fields to `UpdateEnvironmentInput` in `backend/styrmin_backend/api/definitions/environment/inputs.py`. The Strawberry input → dict converter (`update_environment_input_to_dict`) handles them automatically via the existing `__strawberry_definition__.fields` recursion — no converter changes required. Verify the converter works correctly on the new fields by adding inline assertions or by relying on T004's tests.
- [X] T003 [US1] Regenerate `schema.graphql` (`uv run styrmin export graphql-schema schema.graphql`) and verify the diff shows ONLY the two new input fields. Then run `uv run invoke generate` to regenerate the SDK Python types and frontend TypeScript types. Commit all three regenerated outputs (`schema.graphql`, `python_sdk/src/styrmin_sdk/graphql/_generated/input_types.py`, `frontend/src/generated/graphql.ts`).
- [X] T004 [P] [US1] Add per-field propagation tests for `UpdateEnvironmentInput.ingressClass` and `UpdateEnvironmentInput.dbSize` to `backend/tests/functional/graphql/test_environment_update_propagation.py`. Each test: submit `updateEnvironment(input: { ingressClass: "nginx" })` (or `dbSize: "10Gi"`) → query `Environment.config` → assert the field round-trips. Mirror the shape of the existing per-field propagation tests for `ipWhitelist` / `fqdnSuffix` etc.
- [X] T005 [US1] Add the **schema-walking propagation test** `test_update_environment_input_covers_every_environment_config_field` to `backend/tests/functional/graphql/test_environment_update_propagation.py` per research §1. The test introspects `EnvironmentConfig.model_fields` (Pydantic) and `UpdateEnvironmentInput.__strawberry_definition__.fields` (Strawberry) and asserts every public Pydantic field has a corresponding camelCase Strawberry field. Future schema drift fails this test with a precise message. Verify the test passes with the post-T002 input shape, AND verify the test fails by temporarily removing one field from `UpdateEnvironmentInput` and confirming the failure message names the missing field — then restore the field and confirm the test passes again.
- [X] T006 [US1] Format/lint check: `uv run invoke format lint`. Confirm exit 0.

**Checkpoint**: US1 is independently shippable. The two missing fields exist; future drift is caught structurally.

---

## Phase 3: US2 — Frontend Enum Value-Transform Layer (Priority: P1)

**Goal**: The frontend's `buildFullReplacementInput` transforms persisted Pydantic-side enum strings (`"https"`, `"NodeExternalIP"`) to GraphQL enum literals (`HTTPS`, `NODE_EXTERNAL_IP`) at the form's submit boundary. The transform is write-side only; read-side display continues to work against raw JSON.

**Independent Test**: Quickstart Step 3.

- [X] T007 [US2] In `frontend/src/pages/environments/EnvironmentConfigurationTab.tsx`, add the two enum-value mapping tables (`EXTERNAL_URL_SCHEME_MAP` and `EXTERNAL_DNS_ENDPOINTS_TYPE_MAP`) and the generic `transformEnumValue<E>(field, value, mapping)` helper per data-model §3.1. The helper raises a clear `Error` when it encounters an unrecognised value (FR-006); it returns `null` for `null`/`undefined` (unset).
- [X] T008 [US2] Update `buildFullReplacementInput` in the same file to use `transformEnumValue` for the two enum fields (`externalUrlScheme`, `externalDnsEndpointsType`) and to ALSO carry through the new `ingressClass` and `dbSize` fields from US1 (read from `config.ingress_class` and `config.db_size`). Remove any TypeScript-only `as ExternalUrlScheme` casts that the transform replaces (FR-005).
- [X] T009 [US2] Update the 009 H2 nested-clearing block check to reflect that `ingressClass` and `dbSize` are NOW carried through (no longer trigger the block). The block continues to guard `dedicatedIngress` and `scheduling` (which are still cleared to null until typed nested inputs land in a future feature). Search for the H2 detection logic in `EnvironmentConfigurationTab.tsx` (likely a function checking which fields are set on the persisted config to decide whether to disable the form's submit button).
- [X] T010 [P] [US2] Add Vitest tests at `frontend/src/__tests__/EnvironmentConfigurationTab.test.tsx` covering: `transformEnumValue` correctly maps `"http"` → `HTTP`, `"https"` → `HTTPS`, `"NodeExternalIP"` → `NODE_EXTERNAL_IP`, `"ClusterIP"` → `CLUSTER_IP`; returns `null` for `null`/`undefined`; throws on unrecognised values (with a clear error message). Plus integration tests for `buildFullReplacementInput` confirming the full input is constructed correctly when persisted config has the enum fields set.
- [X] T011 [US2] Format/lint + Vitest check: `cd frontend && pnpm tsc --noEmit && pnpm lint && pnpm test --run`. Confirm all green.

**Checkpoint**: US2 is shippable. The form correctly transforms enum values at the submit boundary; existing 009 H2 contract preserved with reduced scope.

---

## Phase 4: US3 — Validator Type-Check + New Typed Error (Priority: P1)

**Goal**: `validate_env_vars_dict` rejects non-string values at the entry point with a typed `InvalidEnvVarValueError` (code `INVALID_ENV_VAR_VALUE`). JSON config callers passing integers, lists, dicts, or None get a precise typed error instead of a 500.

**Independent Test**: Quickstart Step 4.

- [X] T012 [US3] Add `InvalidEnvVarValueError` class to `backend/styrmin_backend/services/env_vars/exceptions.py` per data-model §2.1. Subclass `ServiceError`; `error_code = "INVALID_ENV_VAR_VALUE"`; constructor accepts `name`, `value_type`, optional `scope`; `error_metadata` returns `{name, value_type, [scope]}`.
- [X] T013 [US3] Register `INVALID_ENV_VAR_VALUE` in the `ErrorCode` enum in `backend/styrmin_backend/api/errors.py` so `StructuredErrorExtension` projects it onto `extensions.code` at the GraphQL boundary.
- [X] T014 [US3] Add the entry-point type guard in `backend/styrmin_backend/services/env_vars/validator.py:validate_env_var_value` per data-model §2.2: `if not isinstance(value, str): raise InvalidEnvVarValueError(...)`. The guard runs BEFORE any encoding or size computation. Add a parallel guard in `validate_env_vars_dict` if dict-level callers can bypass `validate_env_var_value`.
- [X] T015 [P] [US3] Add unit tests at `backend/tests/unit/services/env_vars/test_validator.py` covering: type-check rejection for `int`, `float`, `bool` (including `True`/`False`), `None`, `bytes`, `list`, `dict`, and tuple. Each case asserts `InvalidEnvVarValueError` is raised with the correct `name` and `value_type` metadata. String values continue to pass through (existing tests still pass).
- [X] T016 [P] [US3] Add propagation tests at `backend/tests/functional/graphql/test_env_vars_propagation.py` covering: `deploy(config: { env_vars: { X: 1 } })` → `extensions.code = "INVALID_ENV_VAR_VALUE"`; same shape for `updateDeployment(config: ...)` (the still-active JSON config write path post-009). Each test asserts the typed code surfaces through the GraphQL boundary intact (no `INVALID_CONTEXT` collapse).
- [X] T017 [US3] Format/lint check: `uv run invoke format lint`. Run the validator unit + propagation tests: `uv run pytest -q backend/tests/unit/services/env_vars/test_validator.py backend/tests/functional/graphql/test_env_vars_propagation.py`.

**Checkpoint**: US3 is shippable. Non-string env-var values produce typed errors instead of 500s.

---

## Phase 5: US4 — UI E2E + api_only Marker Audit (Priority: P2)

**Goal**: Build the `update_environment_via_form` driver method on both `api_driver.py` and `ui_driver.py`. Unskip T061 (009's UI form E2E). Audit `api_only` markers across 008+009+010 E2Es; remove the misapplied ones; document the retained ones inline.

**Independent Test**: Quickstart Steps 5+6.

- [X] T018 [US4] Add the `update_environment_via_form(*, environment_id: str, env_vars: dict[str, str]) -> None` method signature to the `ScenarioDriver` Protocol in `backend/tests/e2e/drivers/protocol.py`, with the docstring per data-model §4.1.
- [X] T019 [US4] Implement `update_environment_via_form` on `backend/tests/e2e/drivers/api_driver.py` per data-model §4.3. Critical contract: read existing config, **round-trip through `EnvironmentConfig.model_validate(config)` so Pydantic coerces `Literal["http", "https"]` etc. automatically**, modify env_vars, construct the `UpdateEnvironmentInput`, submit via `client.environments.update(...)`. This is the api-side parallel of the ui_driver's form flow; the parametrisation provides dual-entrypoint parity (per critique E1+E2).
- [X] T020 [US4] Implement `update_environment_via_form` on `backend/tests/e2e/drivers/ui_driver.py` per data-model §4.2. Drive the Playwright flow: navigate to `/environments/{environment_id}`, click the Configuration tab, add env-var rows, click Save, confirm the redeploy dialog, wait for page refresh.
- [X] T021 [US4] Unskip T061 in `backend/tests/e2e/test_environment_update.py`. Replace the `@pytest.mark.skip(...)` decorator with the appropriate test wiring. Use `scenario_driver.update_environment_via_form(...)` (the new method); the test runs under both `[api-chromium]` and `[ui-chromium]` variants automatically. Verify the test body's existing assertions still hold; adjust if the new driver method's contract differs.
- [X] T022 [US4] **api_only marker audit**: walk every `@pytest.mark.api_only` decorator in `backend/tests/e2e/test_deployment_env_vars.py` and `backend/tests/e2e/test_environment_update.py`. For each, inspect the wrapped test body. If it calls `scenario_driver.create_*`, `.update_*`, `.upgrade_*`, `.start_*`, `.stop_*`, `.run_*`, `.create_backup`, `.delete_*` (per AGENTS.md heuristic), REMOVE the marker — the test then runs under both `[api-chromium]` and `[ui-chromium]` automatically. If a test does NOT call those methods (purely SDK-level assertions, kubectl/kr8s only), KEEP the marker but add an inline comment per FR-015 documenting WHY this specific test is api-only. Document the marker landscape (pre vs post count + per-test disposition) in a comment at the top of each file or in `auto-implement-report.md`.
- [X] T023 [P] [US4] Run the full E2E suite collection check: `uv run pytest --collect-only -q backend/tests/e2e/test_deployment_env_vars.py backend/tests/e2e/test_environment_update.py`. Verify (a) the previously `@pytest.mark.skip`-marked T061 now collects under both variants, (b) tests with removed `api_only` markers now collect under both `[api-chromium]` and `[ui-chromium]`, (c) the marker count drops by ≥50% from today's 9 (SC-005).
- [X] T024 [US4] Format/lint check after the audit: `uv run invoke format lint`. Confirm exit 0.

**Checkpoint**: US4 is shippable. T061 is unskipped; `api_only` marker landscape is corrected and documented.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final-suite validation, codegen consistency, FR cross-check.

- [X] T025 [P] Run the full backend test suite: `uv run pytest -q backend/tests/unit/ backend/tests/functional/`. Confirm green (with the 2 pre-existing flakes from prior phases noted as unrelated). **Result**: 1247 passed, 1 skipped, 2 failed — the failures are `test_create_cluster_and_try_to_create_it_again` and `test_create_and_delete_cluster_with_error_support` in `backend/tests/functional/test_api.py`, both unrelated cluster-CRUD flakes from prior phases (no env-config / env-vars / validator surface area).
- [X] T026 [P] Run the frontend Vitest suite: `cd frontend && pnpm test --run`. Confirm green. **Result**: 11 test files, 77 tests, all green.
- [X] T027 [P] Run `uv run invoke validate-graphql` to confirm no schema drift. **Result**: 131/131 .graphql files passed validation.
- [X] T028 [P] Confirm `schema.graphql` and the regenerated SDK + frontend types are checked in and consistent (`uv run invoke generate` produces no diff). **Result**: clean — `git status` reports no modified files after `uv run invoke generate`.
- [ ] T029 Run the full E2E suite (`uv run pytest backend/tests/e2e/test_deployment_env_vars.py backend/tests/e2e/test_environment_update.py -v -s --pdb`) against a real Kind/vCluster. **This is the load-bearing run** — T061's unskipped UI E2E + the marker-cleaned dual-entrypoint runs are what confirms US4 actually delivers. If the dev stack isn't up, document the partial outcome and defer to PR opener (precedent from 008/009/010). **⚠️ DEFERRED to PR opener**: requires a live Kind/vCluster which is not available in this implementation chunk. Following precedent from 008/009/010, the PR opener owns the live-cluster E2E gate. Box left unchecked to honestly reflect the deferral; rationale documented inline above.
- [X] T030 Final cross-check: every FR in `spec.md` (FR-001..FR-015) maps to at least one task in this list. Generate the FR cross-check table inline in your final response. **Result**: see "## FR cross-check" section below.

## FR cross-check

Every FR-001..FR-015 in `spec.md` maps to at least one implementing task:

| FR ID | Description (short) | Task IDs |
|-------|---------------------|----------|
| FR-001 | `UpdateEnvironmentInput` gains `ingressClass` + `dbSize`; converter handles both | T002, T003, T004 |
| FR-002 | Schema-walking propagation test asserts every `EnvironmentConfig` field has a matching input field | T005 |
| FR-003 | SDK + frontend types regenerate; SDK accepts `ingress_class` / `db_size` kwargs | T003, T028 |
| FR-004 | `buildFullReplacementInput` transforms enum values (`http`→`HTTP`, `NodeExternalIP`→`NODE_EXTERNAL_IP`, etc.) | T007, T008, T010 |
| FR-005 | Transform is the only `as`-cast site for these enum values; TS-only casts removed | T008, T010 |
| FR-006 | Transform raises clear runtime error on unrecognised enum value; no silent corruption | T007, T010 |
| FR-007 | Transform is write-side only; read-side display unchanged | T007, T008 |
| FR-008 | New `InvalidEnvVarValueError` typed error, `error_code = "INVALID_ENV_VAR_VALUE"`, name + value_type metadata | T012 |
| FR-009 | `validate_env_vars_dict` type-checks values at entry-point; covers int/float/bool/None/bytes/list/dict/etc. | T014, T015 |
| FR-010 | `INVALID_ENV_VAR_VALUE` registered in `ErrorCode` enum so `StructuredErrorExtension` projects it | T013 |
| FR-011 | JSON config write path (`deploy()` / `updateDeployment(config: JSON)`) surfaces typed code | T016, T017 |
| FR-012 | New `EnvironmentDetailPage` Playwright page object with `.open_configuration_tab()` etc. | T018, T019, T020 |
| FR-013 | T061 (UI form E2E) unskipped; runs under both variants | T021 |
| FR-014 | `api_only` marker audit across env-vars / env-config E2Es; misapplied markers removed | T022, T023 |
| FR-015 | Retained `api_only` markers carry inline justification comment | T022 |

---

## Dependencies

### Phase ordering

```text
Setup (Phase 1)
   │
   ▼
US1 (Phase 2) ── must land before US2 (the H2 update in T009 references US1's fields)
   │
   ▼
US2 (Phase 3) ── depends on US1's regenerated types
   │
   ├──► US3 (Phase 4) — independent of US1/US2; can land in parallel
   │
   ▼
US4 (Phase 5) ── depends on US2's transform existing (so the api_driver / ui_driver parity contract works)
   │
   ▼
Polish (Phase 6)
```

US3 is genuinely independent; if a second implementer is available, US3 can ship in parallel with US1+US2 in a separate commit.

### Within-phase parallelism

- **Phase 2 (US1)**: T004 is `[P]`.
- **Phase 3 (US2)**: T010 is `[P]`.
- **Phase 4 (US3)**: T015, T016 are `[P]` (different test files).
- **Phase 5 (US4)**: T023 is `[P]`.
- **Phase 6 (Polish)**: T025, T026, T027, T028 are all `[P]`.

### Implementation strategy

1. **Land US1+US2+US3 in three review-friendly commits** under one PR — they're tightly coupled (US1 touches schema, US2 touches frontend, US3 touches validator) but can review independently.
2. **Land US4 in one commit** (driver methods + un-skip T061 + marker audit) — also reviewable independently.
3. **Polish + final report** as the closing commit.
4. The four bundles ship together (per Decision 5: one PR, multiple commits).

## MVP Scope (recommended)

- **MVP**: Phases 1+2+3+4 (T001..T017 — setup + US1 input completeness + US2 frontend transform + US3 validator hardening). This fixes the three correctness bugs (data-loss + enum corruption + 500s) without the test-infrastructure work.
- **Definition of done for MVP**: SC-001 + SC-002 + SC-003 + SC-006 are green. SC-004 + SC-005 (US4) ship in the same PR but are P2.
- **Strictly out of scope for MVP**: layered template context (separate feature), opinionated render macros (separate feature), inverse-direction completeness check (separate feature).

## Validation checklist

- [ ] Every FR in `spec.md` maps to at least one task above (T030 enforces).
- [ ] FR-002 (schema-walking completeness) is exercised by T005.
- [ ] FR-014a from 010 (chart-default preservation) is unaffected by 011's changes — verified by T029's full E2E run.
- [ ] Every retained `api_only` marker has an inline justification per FR-015 (T022 enforces).
- [ ] No tasks reference inline GraphQL strings (project rule).
- [ ] No tasks edit generated files manually.
