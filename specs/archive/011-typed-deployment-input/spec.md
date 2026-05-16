# Feature Specification: Typed `UpdateDeploymentInput` GraphQL Surface

**Feature Branch**: `011-typed-deployment-input`
**Created**: 2026-05-14
**Status**: Extracted
**Input**: Replace the unstructured `JSON config`/`parameters` arguments on the `updateDeployment` GraphQL mutation with a typed, hand-rolled Strawberry input mirroring the pattern already shipped for `updateEnvironment` in archived spec `009-environment-update`. Operators today pass an opaque blob; we should give them a discoverable, schema-validated input surface for every field that `DeploymentConfig` accepts, plus deployment-only fields (`name`, driver `parameters`, `serviceNameOverrides`, per-component overrides). Source: [GitHub #219](https://github.com/opsmill/styrmin/issues/219) and `.specify/idea-brief.md`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Structured `UpdateDeploymentInput` replaces JSON-blob args (Priority: P1)

An API consumer — SDK user, GraphiQL user, frontend developer, or CLI user — composes a `updateDeployment(deploymentId: ..., input: { ... })` mutation entirely from schema introspection. The input mirrors the deployment configuration shape they already understand from the `Deployment` read API: top-level deployment fields (`name`, `parameters`, `serviceNameOverrides`), every configuration field today exposed through the Pydantic `DeploymentConfig` model (env vars, IP allowlist, ingress, scheduling, FQDN/external-DNS, ingress class, DB size, runtime class, node selector, standard storage, dedicated ingress), and a per-component overrides block. The SDK's regenerated client method accepts a typed Pydantic model. Submitting an invalid env-var name in either the top-level env-vars or any per-component env-vars block returns a precise typed error code at the GraphQL boundary, never collapsed into a generic `INVALID_CONTEXT`.

**Why this priority**: Without the typed input, every SDK / CLI / frontend / GraphiQL consumer of `updateDeployment` is hand-rolling an opaque blob whose shape only the source repo documents. That is the headline operator-experience problem this feature exists to fix. There is no useful sub-slice to ship first: the typed input either replaces the JSON arguments or it does not — there is no halfway state that delivers partial discoverability.

**Independent Test**: A GraphiQL user composes a full `updateDeployment(input: { components: [...], scheduling: {...} })` mutation entirely from introspection, with no prior knowledge of the payload shape. The Python SDK's regenerated `client.deployments.update(deployment_id, input=UpdateDeploymentInput(...))` accepts a typed Pydantic model whose fields mirror `DeploymentConfig` plus the four deployment-only fields. An invalid env-var name in a per-component env-vars block returns `extensions.code = "INVALID_ENV_VAR_NAME"` with a payload identifying the offending name and the component scope.

**Acceptance Scenarios**:

1. **Given** the GraphQL schema after this feature ships, **When** an introspection query lists the `Mutation` type, **Then** `updateDeployment` accepts exactly two arguments — `deploymentId: ID!` and `input: UpdateDeploymentInput!` — and the previous `name` / `config: JSON` / `parameters: JSON` / `serviceNameOverrides: [ServiceNameOverride!]` arguments are no longer present.
2. **Given** the typed input is full-replacement at the top level, **When** an operator submits an input that omits `ipWhitelist` while the persisted deployment row carries a non-empty allowlist, **Then** the persisted allowlist is cleared (set to its unset state). Operators editing a single field must read the existing configuration first and re-submit unchanged fields.
3. **Given** the typed input contains `components: [{ name: "web", envVars: [{ name: "1invalid", value: "x" }] }]`, **When** the mutation is submitted, **Then** the response carries exactly one error with `extensions.code = "INVALID_ENV_VAR_NAME"` and a payload identifying the offending name `"1invalid"` and the component scope `"web"`.
4. **Given** the typed input contains `components: [{ name: "web", ... }, { name: "web", ... }]`, **When** the mutation is submitted, **Then** the response carries exactly one error with `extensions.code = "DUPLICATE_COMPONENT_NAME"` and a payload identifying the offending name `"web"`.
5. **Given** the typed input contains `parameters: [{ name: "replicas", value: 3 }, { name: "replicas", value: 5 }]`, **When** the mutation is submitted, **Then** the response carries exactly one error with `extensions.code = "DUPLICATE_PARAMETER_NAME"` and a payload identifying the offending name `"replicas"`.
6. **Given** the typed input contains `parameters: [{ name: "replicas", value: 5 }]` and the persisted deployment has `parameters = { "replicas": 3, "image_tag": "v1" }`, **When** the mutation is submitted, **Then** the persisted parameters become `{ "replicas": 5, "image_tag": "v1" }` — `image_tag` survives the update because `parameters` uses merge semantics, not full replacement (preserves today's behaviour; the asymmetry vs. `config` full-replacement is documented on the input field).
7. **Given** the typed input contains `components: []`, **When** the mutation is submitted, **Then** all per-component blocks on the persisted deployment are cleared (explicit empty list ≠ omitted field).
8. **Given** the typed input contains `components: [{ name: "web", envVars: null }]`, **When** the mutation is submitted, **Then** the `web` component block is present in the persisted dict with no env-var overrides — the nested omission collapses the inner block to its unset state without removing the component entry.
9. **Given** the SDK is regenerated after the schema change, **When** a Python SDK consumer calls `client.deployments.update(deployment_id, input=UpdateDeploymentInput(...))`, **Then** the call accepts a typed Pydantic model whose fields mirror `DeploymentConfig` plus the four deployment-only fields; the previous `config: dict` / `parameters: dict` / `name: str` / `service_name_overrides: list` SDK parameters are no longer present.
10. **Given** the typed input contains no fields set (`input: {}`), **When** the mutation is submitted, **Then** the response carries one error sourced from the existing service-side validation indicating that at least one field must be provided — no new GraphQL-level non-empty constraint is introduced.

---

### Edge Cases

- **Empty input** (`updateDeployment(input: {})`) — the existing service-side "at least one of config / parameters / name / serviceNameOverrides must be provided" validation continues to fire. GraphQL has no native way to express "at least one of these fields", and a duplicated resolver-side check would shadow the typed error.
- **`components: []`** — explicit wholesale clear of the persisted components dict (full-replacement contract).
- **`components: [{ name: "web", envVars: [] }]`** — the `web` block remains in the persisted dict; the `web` block's env-vars are explicitly cleared.
- **`components: [{ name: "web", envVars: null }]`** — the recursive nested-omission rule collapses `web`'s inner block to its unset state. The `web` key is still present in the persisted components dict; its `env_vars` resolves back to its absent / unset state.
- **Duplicate component name** in the `components` list — surfaces as a new typed `DUPLICATE_COMPONENT_NAME` error code at the GraphQL boundary.
- **Duplicate parameter name** in the `parameters` list — surfaces as a new typed `DUPLICATE_PARAMETER_NAME` error code at the GraphQL boundary.
- **Unknown component name** (a component name that the deployment's currently-pinned application driver version does not declare) — the existing `UNKNOWN_COMPONENT_ENV_VAR` error code continues to surface; no new path is introduced.
- **Internal deployment** (`deployment.internal == true`) — the existing internal-deployment guard continues to surface ahead of any input conversion.
- **Malformed Kubernetes quantity** in a scheduling field (e.g. `scheduling.resources.requests.cpu = "garbage"`) — the existing Pydantic-side quantity validator rejects the request; no new GraphQL-side regex is introduced.
- **Mixed empty + populated `components`** — e.g. `[{ name: "web", envVars: [...] }, { name: "api" }]` — both keys are present in the persisted dict; the `api` block carries no overrides; the `web` block carries its env-var overrides.
- **Submitting an env-var value that exceeds the configured size limit** (top-level or in a per-component block) — the existing `ENV_VAR_SIZE_LIMIT_EXCEEDED` error code continues to surface with the right scope identifier.

## Requirements *(mandatory)*

### Functional Requirements

**Schema surface**

- **FR-001**: The system MUST expose an `UpdateDeploymentInput` GraphQL input type whose top-level fields cover every field of the deployment-configuration shape (the union of base configuration fields, cluster-level configuration fields, environment-level configuration fields, and deployment-only configuration fields) plus the four deployment-only mutation fields `name`, `parameters`, `serviceNameOverrides`, and `components`. Verifiable by introspection-coverage assertion comparing the set of input fields to the set of writable fields on the underlying configuration model.
- **FR-002**: The system MUST reuse the existing leaf input types already defined for the environment-update mutation (env-var entry, scheduling block, dedicated-ingress configuration, ingress-service configuration, resource requirements, tolerations, topology-spread constraints, affinity blocks, label selectors, and their enums) across both the environment input and the new deployment input without duplication. The invariant is "one definition per leaf input, shared by both top-level inputs"; the file/module location for the shared definitions is an implementation-detail decision deferred to planning.
- **FR-003**: The system MUST change the `updateDeployment` mutation argument list to exactly `(deploymentId: ID!, input: UpdateDeploymentInput!)` and remove the previous `name`, `config: JSON`, `parameters: JSON`, and `serviceNameOverrides: [ServiceNameOverride!]` arguments in the same release (hard cutover, no transitional period during which both signatures coexist). This matches the precedent set by the environment-update cutover and prevents JSON-typed surface area from re-growing through deprecated arguments.

**Conversion semantics**

- **FR-004**: The system MUST convert an `UpdateDeploymentInput` value into the dict shape expected by the existing `update_deployment` service function using the following rules: (a) top-level fields whose value is null or unset are omitted from the output dict (full-replacement semantics — an omitted field means "do not touch the corresponding persisted column"); (b) empty lists and empty dicts are preserved as explicit clears; (c) the top-level `envVars` list and each per-component `envVars` list are flattened from list-of-`{name, value}` to dict-of-name-to-value with typed duplicate-name detection; (d) the `parameters` list is flattened from list-of-`{name, value}` to dict-of-name-to-value with typed duplicate-name detection; (e) the `components` list is flattened from list-of-`{name, …}` to dict-of-name-to-block with typed duplicate-name detection; (f) GraphQL enum values are translated to their underlying string form expected by the Pydantic validators.
- **FR-005**: The `updateDeployment` resolver MUST derive the four legacy arguments — deployment configuration dict, parameters dict, name, service-name overrides — from the input value and forward them to the existing `update_deployment` service function without changing the service-function signature or the persisted dict shapes on the deployment row.
- **FR-006**: The system MUST preserve the existing merge semantics for the `parameters` argument: when the input provides a `parameters` list, the values merge on top of the persisted parameters dict (existing keys not named in the input survive). The field description on `UpdateDeploymentInput.parameters` MUST document this asymmetry vs. the full-replacement contract that governs the rest of the input.
- **FR-007**: The resolver MUST continue to raise the existing internal-deployment error ahead of any input conversion when the targeted deployment is marked internal, and MUST continue to raise the existing "at least one of config / parameters / name / serviceNameOverrides must be provided" service-side error when the input has no fields set.

**Error propagation**

- **FR-008**: The system MUST preserve the typed error codes `INVALID_ENV_VAR_NAME`, `ENV_VAR_SIZE_LIMIT_EXCEEDED`, `DUPLICATE_ENV_VAR_NAME`, and `UNKNOWN_COMPONENT_ENV_VAR` at the GraphQL response boundary for **both** the top-level `envVars` input and **every** per-component `envVars` input. The payload MUST identify the offending name and the scope (deployment-level vs. specific component).
- **FR-009**: The system MUST introduce two new typed errors with stable, externally-visible `error_code` values: `DUPLICATE_PARAMETER_NAME` (raised when the `parameters` list contains two entries with the same `name`) and `DUPLICATE_COMPONENT_NAME` (raised when the `components` list contains two entries with the same `name`). Both errors MUST surface at the GraphQL boundary intact (no collapse to a generic error code).

**Codegen propagation**

- **FR-010**: The Python SDK MUST be regenerated to consume the new input shape. The resulting `client.deployments.update(...)` method MUST accept a typed Pydantic model whose fields mirror the deployment-configuration shape and MUST NOT carry any free-form-dict-typed `config` or `parameters` parameters.
- **FR-011**: The frontend GraphQL codegen output MUST be regenerated and the existing deployment-edit caller MUST be updated to send the structured input. No new frontend UI screens or form work is in scope; only the existing caller is retargeted to the new input shape so that the existing edit flow continues to function.

**Discoverability**

- **FR-012**: Every field on `UpdateDeploymentInput`, `ComponentConfigInput`, `ParameterValueInput`, and `StandardStorageInput` MUST carry a non-empty human-readable `description` on its GraphQL declaration so introspection clients (GraphiQL, SDK consumers) can read both the *shape* and the *meaning* of each field without consulting source. Verifiable by an introspection assertion that asserts every input field's description is set and non-empty.

### Key Entities

- **`UpdateDeploymentInput`** (new) — top-level GraphQL input for the `updateDeployment` mutation. Full-replacement semantics for every field except `parameters` (which preserves merge semantics).
- **`ComponentConfigInput`** (new) — GraphQL input mirroring the per-component override block. Carries a required `name` field (matching the dict key on the underlying Pydantic model) plus the per-component override slots currently exposed (today: `envVars`; future per-component knobs slot into the same block).
- **`ParameterValueInput`** (new) — GraphQL input mirroring a single driver-defined parameter assignment. Shape: `name: String!`, `value: JSON!`. The value remains JSON-typed because parameter shapes are driver-defined and dynamic per driver version; a deeper static typing would require per-driver schema generation, which is explicitly out of scope.
- **`DuplicateParameterNameError`** (new typed error) — externally visible code `DUPLICATE_PARAMETER_NAME`. Raised when the input `parameters` list contains two entries with the same name.
- **`DuplicateComponentNameError`** (new typed error) — externally visible code `DUPLICATE_COMPONENT_NAME`. Raised when the input `components` list contains two entries with the same name.
- **Existing entities relied on, unchanged**: the deployment-configuration Pydantic model (its field set defines the input's field set), the per-component override block, the existing typed env-var errors, the `update_deployment` service function (signature unchanged, persisted dict shapes unchanged), and the shared leaf inputs already in use by the environment-update mutation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001 (discoverability)**: A new SDK or GraphiQL consumer can list every writable field on the `updateDeployment` mutation from schema introspection alone, with no source-reading and no examples required. Measured by an introspection-coverage assertion comparing the set of fields on `UpdateDeploymentInput` to the union of (a) every writable field on the deployment-configuration model and (b) the four deployment-only fields `name` / `parameters` / `serviceNameOverrides` / `components`. The two sets must be exactly equal.
- **SC-002 (error fidelity)**: 100% of currently-typed env-var error conditions (invalid name, duplicate name, size-limit exceeded, unknown component) return their typed `extensions.code` at the GraphQL boundary for both the top-level env-var input and every per-component env-var input. The two new conditions (duplicate parameter name, duplicate component name) likewise return their typed codes. Measured by at least one boundary-propagation test per error code per scope (≥ 10 tests total); zero collapses into the generic `INVALID_CONTEXT` code are allowed.
- **SC-003 (surface cleanliness)**: The `updateDeployment` mutation argument list contains exactly zero JSON-typed arguments at the top level. Measured by schema introspection assertion.
- **SC-004 (no behaviour regression)**: All existing deployment-update flows — top-level env-var add, scheduling tweak, rename, parameter bump, service-name override — succeed with semantically-equivalent inputs and produce semantically-equivalent persisted state. Measured by the existing deployment-update unit and integration test suite passing after retargeting to the new input shape, plus the new feature-specific end-to-end test passing.

## Assumptions

- No external (non-frontend, non-SDK, non-CLI) consumers depend on the current `updateDeployment(name, config, parameters, serviceNameOverrides)` argument list. The hard-cutover plan rests on this assumption; planning will include an in-tree search to confirm and will surface any internal automation, vendored scripts, or doc snippets that need updating in the same release.
- The existing `update_deployment` service function signature and the persisted dict shapes on the deployment row stay unchanged. This is a pure GraphQL-surface change; no behavioural change reaches the service layer, the database, or the reconciliation pipeline.
- Driver-defined parameter values must remain JSON-typed on the GraphQL surface because parameter shapes are dynamic per driver version. A deeper static typing would require per-driver schema generation, which is explicitly out of scope (track separately if desired).
- This feature does not change the existing parameter-value validation contract. Today the parameter validator constrains each `value` to match its driver-declared kind (`STRING`, `INTEGER`, `BOOLEAN`, `ENUM`) and rejects type mismatches with a typed `ServiceError`; there is no explicit byte-size cap on string-typed values. The typed input preserves this contract exactly — `ParameterValueInput.value: JSON!` round-trips through the existing validator unchanged. Adding a byte-size cap, or further constraining value shapes, is a separate behavioural change and out of scope.
- The existing frontend deployment-edit screen is sufficient as the post-cutover edit experience. No new screens, no new form work, and no new visual treatment is in scope for this feature.
- The fanout pattern from the 009 environment-update spec does not apply here. `updateDeployment` is itself the per-deployment redeploy trigger; there is no second-level fanout to other entities.

## Dependencies

- Builds directly on the shared leaf input types introduced by the archived 009-environment-update spec. That spec's existing test infrastructure for boundary-propagation of env-var errors is the model for the new tests this feature adds.
- Touches no upstream feature in flight. Future per-component knobs (e.g. per-component replicas tracked in issue #202) will slot into the new `ComponentConfigInput` once it exists; this feature ships the slot, not the knob.
