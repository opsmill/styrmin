# Feature Specification: Env-Config Input Completeness + Validator Hardening + UI Test Infrastructure

**Feature Branch**: `011-env-config-input-hardening`
**Created**: 2026-05-09
**Status**: Draft
**Input**: Hardening pass on 008+009+010 surfacing four real bugs found by an external review:

1. `UpdateEnvironmentInput` (added in 009) is incomplete — `EnvironmentConfig` (via `BaseConfigSection`) carries `ingress_class` and `db_size`, but the input definition omitted them. Under full-replacement semantics, any environment with these fields set silently loses them on env-var save through the UI.
2. The frontend's `buildFullReplacementInput` (added in 009 / US4) does TypeScript-only enum casts. Persisted JSON config carries Pydantic-side raw strings (`"https"`, `"NodeExternalIP"`); GraphQL inputs require Strawberry uppercase literals (`HTTPS`, `NODE_EXTERNAL_IP`). Saving env vars on any environment with these fields set fails validation OR silently corrupts the persisted enum.
3. `api_only` marker misuse + UI E2E gap. Per AGENTS.md heuristic, tests calling `scenario_driver.*` dual-entrypoint methods exercise both UI and API code paths and must run under both variants — but 9 `api_only` markers across 008+009+010 E2Es wrap tests that call those methods. T061 (009's UI form E2E) is also `@pytest.mark.skip` for missing page-object infrastructure, a real gap rather than just marker drift.
4. `validate_env_vars_dict` crashes on non-string values: `validate_env_vars_dict("environment", {"X": 1})` raises `AttributeError: 'int' object has no attribute 'encode'` because `_utf8_bytes` calls `.encode("utf-8")` before any type check. JSON-config write paths surface as 500s instead of typed validation errors.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Complete `UpdateEnvironmentInput` carries every `EnvironmentConfig` field (Priority: P1)

An operator submits an `updateEnvironment(input: ...)` mutation through the SDK, the frontend, or GraphiQL. Every field on `EnvironmentConfig` (including those inherited from `BaseConfigSection`) has a corresponding field on `UpdateEnvironmentInput`. Concretely: `ingress_class` and `db_size` join the existing `env_vars`, `ip_whitelist`, `dedicated_ingress`, `scheduling`, `fqdn_suffix`, `external_url_scheme`, `external_url_port`, `external_dns_endpoints_type` fields. Operators can read the persisted config and round-trip it through the typed mutation without losing any field.

**Why this priority**: This is the load-bearing correctness fix. Until it lands, the frontend env-vars edit form (009/US4) silently destroys `ingress_class` and `db_size` settings on every env-var save — a data-loss bug indistinguishable from operator error from the user's perspective. The 009 H2 review-pass block partially mitigates by refusing to submit when `dedicated_ingress`/`scheduling` are set, but `ingress_class` and `db_size` slip through that guard because they're not nested-input types.

**Independent Test**: Pre-seed an environment with `Environment.config = {"env_vars": {"X": "y"}, "ingress_class": "nginx", "db_size": "10Gi"}`. Submit `updateEnvironment(input: { envVars: [{name: "Z", value: "1"}], ingressClass: "nginx", dbSize: "10Gi" })`. Read back `Environment.config` — the persisted record retains all three fields with the new env_vars value applied. Submit `updateEnvironment(input: { envVars: [{name: "Z", value: "1"}] })` (omitting `ingressClass` + `dbSize`); the persisted record now has `ingress_class: None` and `db_size: None` (full-replacement semantics, working correctly because the operator explicitly omitted the fields).

**Acceptance Scenarios**:

1. **Given** an environment with `ingress_class: "nginx"` and `db_size: "10Gi"` set, **When** the operator submits `updateEnvironment(input: { envVars: [...], ingressClass: "nginx", dbSize: "10Gi" })`, **Then** the persisted `Environment.config` retains both fields with the new env_vars applied.
2. **Given** the GraphQL schema after this feature ships, **When** an introspection query lists `UpdateEnvironmentInput`, **Then** every field on `EnvironmentConfig` has a corresponding camelCase input field; no field is missing.
3. **Given** the frontend reads a persisted environment with `ingress_class` set, **When** an operator opens the Configuration tab and saves env vars, **Then** the `buildFullReplacementInput` helper carries `ingressClass` through unchanged in the submitted input — no silent clearing.
4. **Given** future schema drift adds a new field to `EnvironmentConfig`, **When** the propagation test for input completeness runs, **Then** the test fails with a clear "input field missing for `<new_field>`" message — preventing future drift without an explicit input addition.

---

### User Story 2 - Frontend value-transform layer maps persisted strings to GraphQL enum literals (Priority: P1)

An operator opens the Configuration tab on an environment whose persisted config has `external_url_scheme: "https"` and `external_dns_endpoints_type: "NodeExternalIP"`. They edit env vars and click Save. The form's `buildFullReplacementInput` translates the persisted Pydantic-side strings into the GraphQL enum literals (`HTTPS`, `NODE_EXTERNAL_IP`) at the submit boundary. The mutation succeeds; the persisted enums are preserved.

**Why this priority**: Without the transform, the form silently corrupts these fields on every env-var save — same blast radius as US1 but for a different class of fields. Both bugs land in the same `buildFullReplacementInput` helper; fixing US1 without US2 leaves half the form's submit path broken. They ship together.

**Independent Test**: Pre-seed an environment with `external_url_scheme: "https"` and `external_dns_endpoints_type: "NodeExternalIP"`. Open the Configuration tab in a Playwright session, add an env var, click Save and confirm the redeploy dialog. The mutation succeeds (no GraphQL validation error); the persisted enums remain `https` and `NodeExternalIP`.

**Acceptance Scenarios**:

1. **Given** a persisted environment with `external_url_scheme: "http"`, **When** the form submits a full-replacement input, **Then** the mutation arrives at the backend with `externalUrlScheme: HTTP` (the GraphQL enum literal), not `externalUrlScheme: "http"` (the raw lowercase string).
2. **Given** a persisted environment with `external_dns_endpoints_type: "NodeExternalIP"`, **When** the form submits, **Then** the mutation arrives with `externalDnsEndpointsType: NODE_EXTERNAL_IP`.
3. **Given** a persisted environment with neither enum field set, **When** the form submits, **Then** the corresponding input fields are `null` (consistent with full-replacement semantics for unset fields).
4. **Given** a persisted environment with an unrecognised enum value (corrupt data, future-added value not yet in the frontend's enum union), **When** the form attempts to transform, **Then** the form raises a clear error before submitting (no silent corruption); the operator sees an actionable message.

---

### User Story 3 - Validator type-checks env-var values with a typed error (Priority: P1)

A backend caller passes a non-string value into `validate_env_vars_dict` — directly via the JSON config write path on `deploy()` / `updateDeployment(config: JSON)`, or indirectly via SDK callers constructing dicts with mixed-type values. Instead of an `AttributeError` surfacing as a 500, the validator raises a typed `InvalidEnvVarValueError` with code `INVALID_ENV_VAR_VALUE`. The operator receives a precise GraphQL error pointing at the offending key and value type.

**Why this priority**: A 500 on an operator-correctable input is a usability bug AND a missed Constitution §IV typed-error opportunity. Other env-var validators (name regex, size caps, duplicate names) all surface typed codes; values are the only input that doesn't. The fix is small (3-line type guard + new error class) but completes the typed-error contract for env vars.

**Independent Test**: Through a service-layer call (or via `deploy(config: JSON)` at the GraphQL boundary), submit `env_vars: {"X": 1}`. The response has `extensions.code = "INVALID_ENV_VAR_VALUE"` and the message names `"X"` and the offending type (`int`). Same for `[]`, `{}`, `None`, `True`, `1.5` — each surfaces the typed error.

**Acceptance Scenarios**:

1. **Given** a JSON config write path receiving `env_vars: {"X": 1}`, **When** validation runs, **Then** `InvalidEnvVarValueError` is raised with `error_code = "INVALID_ENV_VAR_VALUE"` and metadata identifying name `"X"` and Python type `"int"`.
2. **Given** the GraphQL boundary surfaces the error, **When** the operator inspects `extensions`, **Then** they see `extensions.code = "INVALID_ENV_VAR_VALUE"` (no INVALID_CONTEXT collapse, matching the H1 fix from 008's review).
3. **Given** a value of `None`, `True`, `False`, `1.5`, `[]`, `{}`, or any nested non-string type, **When** validation runs, **Then** the same typed error is raised regardless of which non-string variant the caller passed.
4. **Given** a value that IS a string (including empty string), **When** validation runs, **Then** the rest of the validator runs normally — name regex, size caps, etc. The type check is the entry-point gate; downstream validation is unchanged.

---

### User Story 4 - UI E2E unblocked + `api_only` markers corrected (Priority: P2)

An end-to-end Playwright scenario drives the full env-vars edit form flow: navigate to `Environment > Configuration` tab, add a new env-var row, click Save, confirm the redeploy dialog, observe the page refresh with the new state. The required page object (`EnvironmentDetailPage`) lands as part of this feature so T061 (009's UI form E2E) can be unskipped. Separately, the project's E2E suite is audited: every test calling `scenario_driver.*` dual-entrypoint methods that's currently marked `api_only` has the marker removed, so the test runs under both `[api-chromium]` and `[ui-chromium]` variants per AGENTS.md.

**Why this priority**: This unblocks the Constitution §V "E2E covers user-visible flow" obligation that T061 was deferring. The marker cleanup is mechanical but fixes a real policy violation across 9 markers in 008+009+010 E2Es. P2 because the load-bearing fixes are US1+US2+US3; this one ships in the same PR for cohesion but isn't the blocker for env-config correctness.

**Independent Test**: Run `uv run pytest backend/tests/e2e/test_environment_update.py::test_us4_env_vars_form_redeploys_environment -v -s`. Both `[api-chromium]` and `[ui-chromium]` variants complete green against a real cluster — the UI variant exercises the full Playwright form flow end-to-end. Audit: `grep -c "@pytest.mark.api_only" backend/tests/e2e/test_*env*.py` returns a substantially smaller number than today's 9 (the only retained markers are tests that genuinely don't drive `scenario_driver.*`).

**Acceptance Scenarios**:

1. **Given** an `EnvironmentDetailPage` Playwright page object exists, **When** an E2E test instantiates it and calls `.open_configuration_tab()`, **Then** the page navigates to the tab and waits for the configuration sections to render.
2. **Given** the page object's `.add_env_var(name, value)` method, **When** called from the test, **Then** the form gains a new row populated with the supplied name/value pair, observable via Playwright assertions on the rendered DOM.
3. **Given** T061 is unskipped after the page object lands, **When** the test runs against a real cluster, **Then** it asserts: form submission triggers the confirm dialog naming the deployment count, confirming dispatches the redeploy, the page refreshes with the new env vars visible.
4. **Given** an existing E2E that calls `scenario_driver.update_deployment` is currently marked `api_only`, **When** the marker cleanup completes, **Then** the marker is removed (or replaced with a documented justification if the test genuinely is api-only by some other criterion). The pytest suite picks it up under both variants.
5. **Given** T061 is parametrised over both `[api-chromium]` and `[ui-chromium]` after the marker cleanup, **When** the test runs, **Then** the same observable outcomes are asserted under both variants — and that parametrisation IS the api/ui-parity check. The api_driver's `update_environment_via_form` reaches the same persisted state as the ui_driver's form flow (the api_driver does this via Pydantic `EnvironmentConfig.model_validate` coercion of raw JSON config; the ui_driver does it via the US2 manual transform). No separate parity test is needed.

---

### Edge Cases

- **US1 — operator submits an `UpdateEnvironmentInput` field with the same value the persisted config carries**: 009's per-deployment no-op detection (FR-010) handles this — no fanout dispatched.
- **US1 — operator submits an `UpdateEnvironmentInput` omitting `ingressClass` when the persisted config has it set**: full-replacement semantics clear it, intentionally. This is a deliberate operator action, not a silent UI side-effect.
- **US2 — frontend reads a persisted enum value that's neither in the union (corrupt data or future addition)**: form raises a clear error before submit instead of casting silently.
- **US3 — validator receives a `bytes` value (which has `.encode()` defined and would NOT raise an `AttributeError`)**: type check rejects it explicitly because it's not `str` — the error path doesn't depend on the absence of `.encode()`, it depends on the type being `str`.
- **US4 — running `[ui-chromium]` variant for tests that don't have UI flows**: AGENTS.md says these tests should be `api_only` *with a justification*. The audit retains markers where the justification holds (e.g., a propagation-style test that only inspects API response shapes); removes them where dual-entrypoint methods are actually called.
- **US4 — the `[ui-chromium]` variant doubles E2E run time**: per AGENTS.md, this is the cost of dual-entrypoint coverage and is acceptable.

## Requirements *(mandatory)*

### Functional Requirements

#### US1 — UpdateEnvironmentInput completeness

- **FR-001**: `UpdateEnvironmentInput` MUST gain `ingressClass: String | null` and `dbSize: String | null` fields. The Strawberry input → dict converter (`update_environment_input_to_dict`) MUST handle both fields correctly.
- **FR-002**: A propagation test MUST assert `UpdateEnvironmentInput` has a corresponding camelCase input field for every public `EnvironmentConfig` field (including inherited fields from `BaseConfigSection`). The test introspects the schema and the Pydantic model at runtime — future schema drift is caught even when no human notices the omission.
- **FR-003**: SDK Python types and frontend TypeScript types MUST regenerate after the schema change. The SDK `client.environments.update(input=UpdateEnvironmentInput(...))` accepts `ingress_class` and `db_size` keyword arguments.

#### US2 — Frontend enum value transform

- **FR-004**: The frontend's `buildFullReplacementInput` (in `EnvironmentConfigurationTab.tsx`) MUST transform persisted enum-valued fields from their Pydantic-side raw strings to the GraphQL enum literals before submission. The transform handles: `external_url_scheme` (`"http"` ↔ `HTTP`, `"https"` ↔ `HTTPS`), `external_dns_endpoints_type` (`"NodeExternalIP"` ↔ `NODE_EXTERNAL_IP`, `"ClusterIP"` ↔ `CLUSTER_IP`).
- **FR-005**: The transform MUST be the only `as`-cast site for these enum values in the form's submit path. TypeScript-only casts elsewhere in the build path that don't run a runtime transform MUST be removed.
- **FR-006**: The transform MUST raise a clear runtime error when it encounters an unrecognised enum value. The error message MUST identify the field name and the unrecognised value. The form MUST NOT submit corrupt data on this error path.
- **FR-007**: The transform MUST be write-side only. Read-side display of `Environment.config` continues to work against raw JSON; no inverse-direction transform is added.

#### US3 — Validator type-check + new typed error

- **FR-008**: A new typed error `InvalidEnvVarValueError` MUST be added to `backend/styrmin_backend/services/env_vars/exceptions.py`, subclassing `ServiceError` per Constitution §IV, with `error_code = "INVALID_ENV_VAR_VALUE"` and `error_metadata` carrying the offending name and Python type.
- **FR-009**: `validate_env_vars_dict` MUST type-check values at the entry point — before any encoding or size computation — and raise `InvalidEnvVarValueError` for values that are not `str`. The check MUST cover: `int`, `float`, `bool`, `None`, `bytes`, `list`, `dict`, and any other non-`str` type.
- **FR-010**: The new error code MUST be registered in `backend/styrmin_backend/api/errors.py` so `StructuredErrorExtension` projects it onto `extensions.code` at the GraphQL boundary.
- **FR-011**: The JSON config write path on `deploy()` / `updateDeployment(config: JSON)` MUST surface the typed error when a non-string value reaches the validator. The operator-facing GraphQL error has `extensions.code = "INVALID_ENV_VAR_VALUE"` (no INVALID_CONTEXT collapse — matches the post-008-H1 typed-error preservation contract).

#### US4 — UI E2E + api_only marker cleanup

- **FR-012**: A new Playwright page object `EnvironmentDetailPage` MUST be added to the frontend test infrastructure. It MUST expose at minimum: `.open_configuration_tab()`, `.add_env_var(name, value)`, `.edit_env_var_value(name, value)`, `.remove_env_var(name)`, `.save()`, `.confirm_redeploy_in_dialog()`, `.expect_env_var_visible(name, value)`.
- **FR-013**: T061 from 009 (the UI form E2E `test_us4_env_vars_form_redeploys_environment`) MUST be unskipped. The test body uses the new page object and runs against a real cluster.
- **FR-014**: Every E2E test in `backend/tests/e2e/test_deployment_env_vars.py`, `backend/tests/e2e/test_environment_update.py`, and any other E2E touching env-vars/env-config flows MUST be audited against AGENTS.md's `api_only` heuristic. Markers wrapping tests that call `scenario_driver.*` dual-entrypoint methods MUST be removed unless an explicit justification (documented inline) applies. After the audit, the marker count drops substantially from the current 9.
- **FR-015**: Tests with `api_only` markers retained after the audit MUST carry an inline comment naming the specific reason the test does not exercise UI flow (e.g., "asserts on GraphQL response shape only; no `scenario_driver.*` calls"). The audit produces a documented landscape, not just a numeric reduction.

### Key Entities

- **`UpdateEnvironmentInput`**: Strawberry input type added in 009. Gains two scalar fields in this feature (`ingressClass`, `dbSize`).
- **`InvalidEnvVarValueError`**: new typed error subclass with `error_code = "INVALID_ENV_VAR_VALUE"`. Thrown by `validate_env_vars_dict` when a value is not `str`.
- **`EnvironmentDetailPage`** (frontend test helper): Playwright page object that drives the env-config + env-vars form UI flow.
- **`buildFullReplacementInput`**: existing frontend helper in `EnvironmentConfigurationTab.tsx`. Gains a value-transform layer for enum fields; loses the TypeScript-only casts.
- **Schema-walking propagation test**: new completeness test that introspects `UpdateEnvironmentInput` against `EnvironmentConfig` at runtime — catches future drift.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An environment with `ingress_class` and `db_size` set survives an operator's env-vars save through the UI without losing those fields. Verified by a propagation test (US1) and the unskipped UI E2E (US4) that explicitly seeds these fields and confirms post-save state.
- **SC-002**: An environment with `external_url_scheme: "https"` and `external_dns_endpoints_type: "NodeExternalIP"` survives a UI env-vars save without enum corruption. Verified by Vitest on the transform helper (US2) and the UI E2E (US4) round-tripping these fields.
- **SC-003**: Submitting `env_vars: {"X": 1}` (or any other non-string value) through the JSON config write path produces `extensions.code = "INVALID_ENV_VAR_VALUE"`. Verified by a unit test on the validator and a propagation test on the GraphQL boundary (US3).
- **SC-004**: T061 (the UI form E2E) is unskipped and runs green under `[ui-chromium]`. The page object infrastructure supports adding new env-config UI tests without bespoke Playwright code per test.
- **SC-005**: Across `backend/tests/e2e/test_deployment_env_vars.py` + `backend/tests/e2e/test_environment_update.py`, the `api_only` marker count drops by at least 50% from today's 9 — and every retained marker carries an inline justification.
- **SC-006**: The schema-walking propagation test (US1) prevents future drift: adding a new field to `EnvironmentConfig` without a corresponding `UpdateEnvironmentInput` field fails CI with a clear, actionable message.

## Assumptions

- The Pydantic-side `EnvironmentConfig` shape (and its inherited `BaseConfigSection`) is the source of truth for "what fields the input must carry". Field additions to `EnvironmentConfig` are the trigger for input updates, not the other way round.
- The frontend's existing `buildFullReplacementInput` helper is the right place to land the value transform — co-located with the rest of the form's submit logic.
- Adding a new typed error (`InvalidEnvVarValueError`) is preferable to extending `InvalidEnvVarNameError` or `EnvVarSizeLimitExceededError`. Each existing error has a distinct semantic; "value is wrong type" is its own category.
- The new Playwright page object (`EnvironmentDetailPage`) is a project-wide test infrastructure addition, not specific to env-config. Future env-management UI tests build on the same object.
- The `api_only` marker cleanup is purely a marker change — no test bodies are rewritten. Tests that were `api_only` and shouldn't be will simply also run under `[ui-chromium]` post-cleanup; their existing assertions stay valid because they don't depend on UI absence.
- Deployment-side `updateDeployment(config: JSON)` retains its JSON config argument (it was never replaced by a typed input the way `updateEnvironment` was in 009). The validator hardening (US3) protects this still-active write path; this feature does NOT migrate it to a typed input.
- The 009 H2 nested-clearing block in the form stays. After US1+US2 land, the block guards a smaller set of fields (only `dedicatedIngress` and `scheduling`, since `ingressClass` and `dbSize` are now correctly carried through). The block's logic is unchanged; only the field set it inspects shrinks.
- The schema-walking propagation test is robust to future Strawberry/Pydantic version changes that affect introspection — implementer chooses the introspection mechanism (`__strawberry_definition__.fields`, Pydantic's `model_fields`, or both) and pins the assertion shape.
