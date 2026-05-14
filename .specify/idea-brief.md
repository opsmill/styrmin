# Idea Brief: Typed `UpdateDeploymentInput` GraphQL Surface

**Status**: Ready for /speckit-specify
**Seed**: [GitHub #219](https://github.com/opsmill/styrmin/issues/219) — Replace the unstructured `JSON config`/`parameters` arguments on the `updateDeployment` GraphQL mutation with a typed, hand-rolled Strawberry input mirroring the pattern already shipped for `updateEnvironment` in archived spec `009-environment-update`. Operators today pass an opaque blob; we should give them a discoverable, schema-validated input surface for every field that `DeploymentConfig` accepts, plus deployment-only fields (`name`, driver `parameters`, `serviceNameOverrides`, per-component overrides).

## Users and Value

**Primary user**: SDK consumers, CLI users, GraphiQL users, and the frontend developer touching the deployment edit screen. Secondary: platform engineers who maintain the schema and want self-documenting mutations.

**Pain today**: `updateDeployment(config: JSON, parameters: JSON)` is opaque. Clients hand-roll the payload; the GraphQL schema documents nothing about its shape; per-field validation only surfaces after the request lands in Pydantic; and (per the 008-deployment-env-vars review history) error-code collapse has been a recurring failure mode — a typed `INVALID_ENV_VAR_NAME` in a `components.*` block can land as a generic `INVALID_CONTEXT` if the conversion path isn't carefully threaded. The same gap was closed for environments in #009; this is the deployment-side follow-up.

**Better looks like**: An introspectable `UpdateDeploymentInput` whose fields mirror `DeploymentConfig` plus the deployment-only `name` / `parameters` / `serviceNameOverrides` / `components`; typed validation errors (`INVALID_ENV_VAR_NAME`, `DUPLICATE_ENV_VAR_NAME`, `UNKNOWN_COMPONENT_ENV_VAR`, `ENV_VAR_SIZE_LIMIT_EXCEEDED`, and new `DUPLICATE_PARAMETER_NAME` / `DUPLICATE_COMPONENT_NAME`) reach the GraphQL caller intact for both top-level and `components.*` env-var bundles.

## User Journeys

### P1 — Structured `UpdateDeploymentInput` replaces JSON-blob args

- **Journey**: An API consumer (SDK user, GraphiQL user, frontend) composes a `updateDeployment(deploymentId: ..., input: { ... })` mutation entirely from schema introspection — including a `components: [{name: "web", envVars: [{name: "OTEL", value: "https://otel.staging"}]}]` block and a `scheduling.resources.requests.cpu = "200m"` override. The SDK's regenerated client method accepts a typed Pydantic model. Submitting an invalid env-var name in either the top-level `envVars` or any `components.*.envVars` block returns the precise typed error code, never a generic `INVALID_CONTEXT`.

- **Why this priority**: Without the typed input, every SDK/CLI/frontend consumer of `updateDeployment` is hand-rolling a blob whose shape only the source repo documents. That is the headline operator-experience problem #219 exists to fix. There is no useful sub-slice to ship first: the input either replaces the JSON args or it doesn't.

- **Independent Test**: A GraphiQL user composes a full `updateDeployment(input: { components: [...], scheduling: {...} })` mutation entirely from introspection. The Python SDK's regenerated `client.deployments.update(deployment_id, input=UpdateDeploymentInput(...))` accepts a typed Pydantic model. An invalid env-var name in a `components.*` block returns `extensions.code = "INVALID_ENV_VAR_NAME"` with a payload identifying the offending name.

- **Acceptance Scenarios**:

  1. **Given** the GraphQL schema after this feature ships, **When** an introspection query lists the `Mutation` type, **Then** `updateDeployment` accepts exactly one argument `input: UpdateDeploymentInput!` (plus `deploymentId`) and the old `name` / `config: JSON` / `parameters: JSON` / `serviceNameOverrides: [ServiceNameOverride!]` arguments are no longer present.
  2. **Given** the typed input is full-replacement at the top level, **When** the operator submits an input that omits `ipWhitelist` while the persisted deployment row carries a non-empty allowlist, **Then** the persisted allowlist is cleared.
  3. **Given** the typed input contains `components: [{name: "web", envVars: [{name: "1invalid", value: "x"}]}]`, **When** the mutation is submitted, **Then** the response carries one error with `extensions.code = "INVALID_ENV_VAR_NAME"` and a payload identifying `"1invalid"` and the component scope `"web"`.
  4. **Given** the typed input contains `components: [{name: "web", ...}, {name: "web", ...}]`, **When** the mutation is submitted, **Then** the response carries one error with `extensions.code = "DUPLICATE_COMPONENT_NAME"`.
  5. **Given** the typed input contains `parameters: [{name: "replicas", value: 3}, {name: "replicas", value: 5}]`, **When** the mutation is submitted, **Then** the response carries one error with `extensions.code = "DUPLICATE_PARAMETER_NAME"`.
  6. **Given** the typed input contains `parameters: [{name: "replicas", value: 5}]` and the persisted deployment has `parameters = {"replicas": 3, "image_tag": "v1"}`, **When** the mutation is submitted, **Then** the persisted parameters become `{"replicas": 5, "image_tag": "v1"}` (merge semantics preserved from today's behaviour; `image_tag` survives).
  7. **Given** the typed input contains `components: []`, **When** the mutation is submitted, **Then** all per-component blocks on the persisted deployment are cleared (full-replacement of the components dict).
  8. **Given** the SDK is regenerated after the schema change, **When** a Python SDK consumer calls `client.deployments.update(deployment_id, input=UpdateDeploymentInput(...))`, **Then** the call accepts a typed Pydantic model whose fields mirror `DeploymentConfig` plus the four deployment-only fields; the old `config: dict` / `parameters: dict` / `name: str` / `service_name_overrides: list` SDK parameters are no longer present.

## Functional Requirements

### Schema surface

- **FR-001**: System MUST expose a `UpdateDeploymentInput` Strawberry input type whose top-level fields cover every field of `DeploymentConfig` (i.e. `BaseConfigSection` + `ClusterConfig`-added + `EnvironmentConfig`-added + `components`) plus the four deployment-only fields `name`, `parameters`, `serviceNameOverrides`, and `components`. *Verified by*: schema introspection test diffing input fields against `DeploymentConfig.model_fields` ∪ deployment-only set.
- **FR-002**: System MUST reuse the existing leaf input types (`EnvVarInput`, `SchedulingInput`, `DedicatedIngressInput`, `IngressServiceConfigInput`, `ResourceRequirementsInput`, `TolerationInput`, `TopologySpreadConstraintInput`, `AffinityBlockInput`, `LabelSelectorInput`, etc. — currently in `api/definitions/environment/inputs.py`) without duplication. The extraction location is a plan-time decision but the *invariant* is "one definition per leaf input, shared across environment and deployment top-level inputs". *Verified by*: type-identity assertion (`UpdateEnvironmentInput.scheduling.__class__ is UpdateDeploymentInput.scheduling.__class__`).
- **FR-003**: System MUST change the `updateDeployment` mutation signature to `(deploymentId: ID!, input: UpdateDeploymentInput!)` and remove the previous `name` / `config` / `parameters` / `serviceNameOverrides` arguments in the same commit (hard cutover; no transitional dual-signature period — matches the 009 cutover precedent and avoids `JSON` regrowing through deprecated args).

### Conversion helper

- **FR-004**: System MUST provide `update_deployment_input_to_dict(input: UpdateDeploymentInput) -> dict[str, Any]` that:
  - Omits top-level fields whose value is `None` / `strawberry.UNSET` (full-replacement semantics: an omitted field means "do not touch the corresponding persisted column").
  - Preserves empty lists and empty dicts (explicit clear).
  - Flattens `envVars` and `components.*.envVars` from list-of-`{name, value}` to `dict[str, str]`, raising `DuplicateEnvVarNameError` on duplicates (one error scoped to `"deployment"`, one per `"component:<name>"`).
  - Flattens `parameters` from list-of-`{name, value}` to `dict[str, Any]`, raising new `DuplicateParameterNameError` on duplicates.
  - Flattens `components` from `list[ComponentConfigInput]` to `dict[str, ComponentConfigBlock-shaped dict]`, raising new `DuplicateComponentNameError` on duplicate names.
  - Translates GraphQL enums to their Pydantic-side string `.value`.
  *Verified by*: unit tests on the helper itself, one per branch.

### Resolver behaviour

- **FR-005**: The `updateDeployment` resolver MUST derive the split `(deployment_config, deployment_parameters, deployment_name, service_name_overrides)` from the input dict and forward to the existing `update_deployment` service function unchanged. *Verified by*: resolver-level integration test that asserts service-function call args for each combination of input fields.
- **FR-006**: The resolver MUST preserve today's merge semantics for `parameters` (existing values are the base; input-provided entries override on a per-key basis). Documented on the `UpdateDeploymentInput.parameters` field description so the asymmetry vs. `config`-style full-replacement is discoverable. *Verified by*: scenario 6 above.
- **FR-007**: The resolver MUST continue to raise `InternalDeploymentError` ahead of any input conversion for `deployment.internal == True`, and continue to raise `InvalidContextError` (from the service) when the input is empty (no field set). *Verified by*: existing tests for both error paths, retargeted to the new input shape.

### Error propagation (constitution §IV)

- **FR-008**: System MUST preserve the typed env-var error codes (`INVALID_ENV_VAR_NAME`, `ENV_VAR_SIZE_LIMIT_EXCEEDED`, `DUPLICATE_ENV_VAR_NAME`, `UNKNOWN_COMPONENT_ENV_VAR`) at the GraphQL boundary for both top-level `envVars` and any `components.*.envVars` block. *Verified by*: one propagation test per code per scope (8 tests).
- **FR-009**: System MUST introduce two new typed errors with stable `error_code` values (`DUPLICATE_PARAMETER_NAME`, `DUPLICATE_COMPONENT_NAME`) and surface them at the GraphQL boundary for the corresponding input shapes. *Verified by*: scenarios 4 and 5; one propagation test per new code.

### Codegen propagation

- **FR-010**: The Python SDK MUST be regenerated to consume the new input shape (`uv run styrmin export graphql-schema schema.graphql && uv run invoke generate`); the resulting `client.deployments.update(...)` method MUST accept a typed `UpdateDeploymentInput` Pydantic model and no `dict`-typed `config` / `parameters` parameters. *Verified by*: SDK contract test.
- **FR-011**: The frontend GraphQL codegen output MUST be regenerated; the existing deployment edit caller MUST be updated to send the structured input. *Verified by*: `pnpm lint` + `pnpm test` clean; Vitest test on the edit caller hitting the new typed mutation signature.

## Key Entities

- **`DeploymentConfig`** (existing, unchanged) — source-of-truth Pydantic model whose shape `UpdateDeploymentInput` mirrors. MRO is `BaseConfigSection` → `ClusterConfig` → `EnvironmentConfig` → `DeploymentConfig`. Fields: `ingress_class`, `db_size`, `fqdn_suffix`, `external_url_scheme`, `external_url_port`, `external_dns_endpoints_type`, `scheduling`, `runtime_class`, `node_selector`, `dedicated_ingress`, `standard_storage`, `ip_whitelist`, `env_vars`, `components`.
- **`ComponentConfigBlock`** (existing, unchanged) — per-component override block carried under `DeploymentConfig.components`, keyed by component name. Currently only `env_vars: dict[str, str] | None`. Future per-component knobs (e.g. replicas from #202) will slot into the same block.
- **`UpdateDeploymentInput`** (new) — hand-rolled Strawberry input, top-level container for the mutation. Full-replacement semantics at the top level; `parameters` is the documented asymmetry (merge).
- **`ComponentConfigInput`** (new) — Strawberry input mirroring `ComponentConfigBlock`, with an added required `name: String!` field (the dict key on the Pydantic side).
- **`ParameterValueInput`** (new) — `{ name: String!, value: JSON! }`. Driver-defined parameter shapes are not knowable at the GraphQL boundary; the value stays `JSON`.
- **Shared leaf inputs to reuse**: `EnvVarInput`, `SchedulingInput`, `DedicatedIngressInput`, `IngressServiceConfigInput`, `ResourceRequirementsInput`, `TolerationInput`, `TopologySpreadConstraintInput`, `AffinityBlockInput`, `LabelSelectorInput`, etc. Currently in `api/definitions/environment/inputs.py`. Extraction destination is a plan-time call; the invariant is "no duplication" (FR-002).

## Edge Cases

1. **Empty input** (`updateDeployment(input: {})`) → existing service-side `InvalidContextError` ("at least one of config/parameters/name/serviceNameOverrides must be provided") continues to surface. No GraphQL-side non-empty constraint (GraphQL can't express "at least one of these fields").
2. **`components: []`** → wholesale clear of the persisted components dict.
3. **`components: [{name:"web", envVars: []}]`** → `web` block survives; `web`'s env vars are cleared.
4. **`components: [{name:"web", envVars: null}]`** → nested `null`/UNSET fields are omitted by `_convert_value`'s recursive omission rule, so the `web` block lands as `{}` and the Pydantic model resolves its `env_vars` back to `None`. Effectively a no-op for `web`'s env-var state but `web` is asserted-present in the dict.
5. **Duplicate component name** in the `components` list → new typed `DuplicateComponentNameError` (`DUPLICATE_COMPONENT_NAME`), GraphQL-boundary-preserved.
6. **Duplicate parameter name** in the `parameters` list → new typed `DuplicateParameterNameError` (`DUPLICATE_PARAMETER_NAME`).
7. **Unknown component name** (component not declared by the deployment's driver version) → existing `UnknownComponentEnvVarError` raised by `_validate_component_env_var_targets` continues to surface.
8. **Internal deployment** (`deployment.internal == True`) → existing `InternalDeploymentError` continues to surface ahead of any input conversion.
9. **`scheduling: { resources: { requests: { cpu: "garbage" } } }`** → existing Pydantic `_K8S_QUANTITY_RE` validator rejects with the same typed error path as today; no new GraphQL-side regex.
10. **Mixed empty + populated `components`** — e.g. `[{name:"web", envVars: [{name:"A",value:"1"}]}, {name:"api"}]` — `api` block lands as `{}` per rule (4); `web` lands populated. Both keys present in the persisted dict.

## Success Criteria

- **SC-001 (discoverability)**: A new SDK or GraphiQL consumer can list every writable field on the `updateDeployment` mutation from schema introspection alone — no source-reading, no examples required. *Measured by*: an introspection-coverage assertion comparing the set of fields on `UpdateDeploymentInput` to `DeploymentConfig.model_fields` ∪ {`name`, `parameters`, `serviceNameOverrides`, `components`}; the two sets must be equal.
- **SC-002 (error fidelity)**: 100% of currently-typed env-var error conditions (invalid name, duplicate, size-limit, unknown-component) return their typed `extensions.code` for any input scope (top-level *and* `components.*`). The two new conditions (`DUPLICATE_PARAMETER_NAME`, `DUPLICATE_COMPONENT_NAME`) likewise return their typed codes. *Measured by*: one propagation test per code per scope (≥10 tests total); zero collapses to `INVALID_CONTEXT`.
- **SC-003 (surface cleanliness)**: The `updateDeployment` mutation argument list contains exactly zero `JSON`-typed arguments at the top level. *Measured by*: schema introspection assertion.
- **SC-004 (no behaviour regression)**: All existing deployment-update flows (top-level env var add, scheduling tweak, rename, parameter bump, service-name override) succeed with semantically-equivalent inputs and produce semantically-equivalent persisted state. *Measured by*: the existing deployment-update unit/integration tests, retargeted to the new input shape, all pass; the new E2E (below) passes.

## Constitution Alignment

- **§I Declarative state reconciliation**: pure surface change. The input still resolves down to the existing `update_deployment` service which writes the desired-state dict to `Deployment.config`. Idempotent properties unchanged; no new imperative side effects introduced.
- **§II Driver-based deployment**: not in scope — the change is at the API surface above drivers. No driver model changes, no driver-rendering changes.
- **§III Layered architecture**: input definitions live under `backend/styrmin_backend/api/definitions/deployment/`; conversion helper lives at the resolver boundary; the `update_deployment` service function signature is unchanged. No cross-layer shortcuts.
- **§IV Type safety & typed errors**: two new `ServiceError` subclasses required — `DuplicateParameterNameError` (code: `DUPLICATE_PARAMETER_NAME`) and `DuplicateComponentNameError` (code: `DUPLICATE_COMPONENT_NAME`). All existing env-var typed errors continue to surface for both top-level and `components.*` scopes (FR-008).
- **§V Test-first / E2E required**: one E2E to ship with the feature — **`test_update_deployment_typed_input_propagates_component_env_var_and_scheduling`** — marked `@pytest.mark.api_only(reason="SDK-driven; no UI flow exercised")`. Steps: (a) deploy a fixture with one `web` component; (b) call `client.deployments.update(deployment_id, input=UpdateDeploymentInput(components=[ComponentConfigInput(name="web", env_vars=[EnvVarInput(name="OTEL", value="https://otel.staging")])], scheduling=SchedulingInput(resources=ResourceRequirementsInput(requests=ResourceSpecInput(cpu="200m")))))`; (c) wait one reconcile cycle; (d) assert pod env var `OTEL=https://otel.staging` and container CPU request `200m`; (e) follow-up call with an invalid env-var name in a `components.*` block returns `extensions.code = "INVALID_ENV_VAR_NAME"`.
- **§V GraphQL ↔ DB propagation tests**: yes — propagation unit tests required for every new input field on `UpdateDeploymentInput` and `ComponentConfigInput`, plus the new `ParameterValueInput`, per `dev/guides/graphql-propagation-tests.md`. Covered by FR-001/FR-008/FR-009 verification paths.

## Governance Gates Crossed

- [x] **GraphQL schema change** — new `UpdateDeploymentInput`, `ComponentConfigInput`, `ParameterValueInput` input types; new `DUPLICATE_PARAMETER_NAME` / `DUPLICATE_COMPONENT_NAME` error codes; breaking change to the `updateDeployment` argument list (`name`, `config`, `parameters`, `serviceNameOverrides` removed in favour of `input`). SDK + frontend regen mandatory.
- [ ] Database schema or migration changes — none (resolver-side conversion only; persisted dict shapes on `Deployment.config` and `Deployment.parameters` unchanged).
- [ ] New dependency — none.
- [ ] CI/CD workflow changes — none beyond the standard schema/SDK/frontend regen already enforced by `uv run invoke validate-graphql` and `uv run invoke generate`.
- [ ] Authentication / authorization changes — none.

## Assumptions

- No external (non-frontend, non-SDK, non-CLI) consumers depend on the current `updateDeployment` argument list. To be confirmed at spec time; if any internal automation or third-party caller exists, the cutover plan must explicitly call it out.
- The existing `update_deployment` service function signature and the persisted dict shapes on `Deployment.config` / `Deployment.parameters` stay unchanged — this is a pure GraphQL-surface change.
- `parameters` values can remain `JSON`-typed on the GraphQL side because driver-defined parameter shapes are dynamic per-driver-version and cannot be statically schema'd without per-driver codegen (a separate, larger initiative explicitly out of scope per the issue Non-Goals).

## Out of Scope (v1)

- Migrating `deployDeployment` (create) to a typed input — separate issue.
- Per-driver schema generation for typed `parameters.value` — investigate during plan if cheap, defer otherwise.
- New frontend UI for editing the component-env-vars block — the existing edit screen is retargeted to the new input via codegen; no new screens or form work.
- Redeploy fanout across an environment (009-US1 equivalent) — N/A: `updateDeployment` *is* the redeploy trigger for a single deployment.
- Changing `parameters` semantics from merge to full-replacement — preserves today's behaviour deliberately; switching would be a separate, intentional behaviour change with its own E2E and migration story.
- Extraction destination for the shared leaf inputs (`EnvVarInput`, `SchedulingInput`, etc.) — implementation detail for `/speckit-plan`; the invariant (no duplication) is captured in FR-002.

## Open Questions

- [NEEDS CLARIFICATION: Confirm no external consumers depend on the current `updateDeployment(name, config, parameters, serviceNameOverrides)` signature before the hard cutover. Frontend + SDK regen handle internal callers; verify by searching for any in-tree automation, vendored scripts, or doc snippets referencing the old args.]
