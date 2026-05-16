# Phase 0 Research: Typed `UpdateDeploymentInput` GraphQL Surface

This document resolves every unknown that fed into `plan.md` and locks the implementation decisions that downstream contracts/tasks rely on. Each section is a single decision with rationale and alternatives.

## 1. Input shape — hand-rolled Strawberry input mirroring `DeploymentConfig`

**Decision**: Define `UpdateDeploymentInput` as a hand-rolled Strawberry input that mirrors the deployment-configuration shape (the union of `BaseConfigSection`, `ClusterConfig`-added, `EnvironmentConfig`-added, and `DeploymentConfig`-added fields) plus the four deployment-only fields `name`, `parameters`, `serviceNameOverrides`, and `components`. Nested objects (`SchedulingConfig`, `DedicatedIngressConfig`, `AffinityBlock`, `ResourceRequirements`, `Toleration`, `TopologySpreadConstraint`, `PostRenderInjection`, `StandardStorage`, etc.) reuse the existing `*Input` Strawberry inputs already defined for `UpdateEnvironmentInput` in `backend/styrmin_backend/api/definitions/environment/inputs.py`. Scalars stay scalar; enums (`ExternalUrlScheme`, `ExternalDnsEndpointsType`, `TolerationOperator`, etc.) reuse the existing Strawberry enum mirrors. The resolver converts the typed input into the existing `DeploymentConfig` dict shape via a new helper `update_deployment_input_to_dict(...)` that follows the exact same rules as `update_environment_input_to_dict(...)`.

**Rationale**: This is a direct port of the 009-environment-update pattern. The existing JSON-blob path round-trips through `DeploymentConfig.model_validate(raw_dict)` for validation. The typed input shortens the chain to "Strawberry parses → input → dict → Pydantic validates" with no behaviour change at the validation layer. All the work in 008-deployment-env-vars (env-var size caps, regex validation, the per-scope error codes) is preserved without rewriting. Hand-rolling vs `strawberry.experimental.pydantic.input` follows the same call we made in 009: the bridge has known issues with deeply nested optional fields, and the hand-rolled style is more debuggable and gives us explicit control over GraphQL field names and enum values.

**Alternatives considered**:

- *Auto-derive from Pydantic via `strawberry.experimental.pydantic.input`* — rejected, same rationale as 009.
- *Wrap a single `JSON` input in a thin typed wrapper* — rejected; defeats the purpose.
- *Per-driver-generated parameter types* — rejected for v1; tracked as a follow-up.

**Reference**: `backend/styrmin_backend/context/models/config.py` (`BaseConfigSection`, `ClusterConfig`, `EnvironmentConfig`, `DeploymentConfig`, `ComponentConfigBlock`); `backend/styrmin_backend/api/definitions/environment/inputs.py` (precedent + leaf inputs to reuse).

## 2. Shared-leaf-input extraction location

**Decision**: Move the leaf inputs that are now shared between `UpdateEnvironmentInput` and `UpdateDeploymentInput` from `backend/styrmin_backend/api/definitions/environment/inputs.py` into a new module `backend/styrmin_backend/api/definitions/config/inputs.py`. Leave the top-level `UpdateEnvironmentInput` class and the `update_environment_input_to_dict` helper in `environment/inputs.py`; have it import the shared leaves from `config/inputs.py`. Mirror for `UpdateDeploymentInput` under `backend/styrmin_backend/api/definitions/deployment/inputs.py`.

Concretely, the shared leaves to extract are: `EnvVarInput`, `LabelSelectorInput`, `LabelSelectorRequirementInput`, `DeploymentReferenceInput`, `AffinityTermInput`, `WeightedAffinityTermInput`, `AffinityBlockInput`, `ResourceSpecInput`, `ResourceRequirementsInput`, `TolerationInput`, `TopologySpreadConstraintInput`, `PostRenderInjectionInput`, `SchedulingInput`, `IngressServiceConfigInput`, `DedicatedIngressInput`, and the enum mirrors (`ExternalUrlScheme`, `ExternalDnsEndpointsType`, `TolerationOperator`, `TolerationEffect`, `WhenUnsatisfiable`, `LabelSelectorOperator`). The recursive `_convert_value` helper also moves to `config/inputs.py` because both top-level converters need it.

**Rationale**: `config/inputs.py` matches the Pydantic side, where `BaseConfigSection` / `ClusterConfig` / `EnvironmentConfig` / `DeploymentConfig` all live in `context/models/config.py`. The naming makes the parallelism between "Pydantic config models" and "GraphQL config inputs" discoverable. Keeping the top-level inputs (`UpdateEnvironmentInput`, `UpdateDeploymentInput`) co-located with their conversion helpers in entity-specific directories preserves the existing layout intuition.

**Alternatives considered**:

- *Leave the shared leaves in `environment/inputs.py` and import from there into `deployment/inputs.py`* — rejected. Creates a misleading "deployment depends on environment" import direction at the GraphQL-definitions layer where no such dependency actually exists at the domain level.
- *Put everything in a single `inputs.py` at the `definitions/` root* — rejected. Mixes top-level mutation inputs (one per mutation) with shared leaves; will get crowded as more typed mutations land.
- *Put under `api/definitions/shared/`* — rejected. "Shared" is a non-domain word; `config/` reflects what the inputs actually model.

**Reference**: `backend/styrmin_backend/context/models/config.py:361-525` (the four-tier Pydantic class hierarchy these inputs mirror).

## 3. `parameters` shape and merge semantics

**Decision**: Type `parameters: list[ParameterValueInput] | None` on `UpdateDeploymentInput`, where `ParameterValueInput { name: String!, value: JSON! }`. Resolver flattens the list to `dict[str, Any]` (raising `DuplicateParameterNameError` on duplicate names) and forwards the resulting dict to the existing `update_deployment(deployment_parameters=...)` service function unchanged. The service function continues to merge: `merged_parameters = {**deployment.parameters, **deployment_parameters}` at `services/deployment.py:321-324` is preserved as-is. The field description on `UpdateDeploymentInput.parameters` MUST document the merge-not-replace asymmetry.

**Rationale**: Driver-defined parameter shapes are dynamic per driver version. Static schema generation is a much larger effort (see §6) and explicitly out of scope. The list-of-`{name,value}` shape mirrors the env-var input grammar (typed duplicate detection, no ambiguity about how to interpret `{}` vs `[]`). Preserving merge semantics avoids a silent behaviour change for callers that today rely on "bump just one parameter without re-sending the rest" — full-replacement here would force every caller to read-modify-write before bumping a single replica count, which the existing CLI/SDK ergonomics don't gracefully support.

**Alternatives considered**:

- *`parameters: JSON | None`* — keeps the blob nested inside the typed input; rejected because we'd lose typed duplicate detection and the input loses internal grammar consistency.
- *Switch to full-replacement for symmetry* — rejected by user decision in the grilling phase; the asymmetry is documented on the input, not pretended away.
- *`replaceParameters: Boolean` flag* — rejected as niche knob bloat.

**Reference**: `backend/styrmin_backend/services/deployment.py:312-333` (merge implementation that stays unchanged); `.specify/idea-brief.md` Q2 grilling decision.

## 4. `components` shape and duplicate detection

**Decision**: Type `components: list[ComponentConfigInput] | None` on `UpdateDeploymentInput`, where:

```
input ComponentConfigInput {
  name: String!
  envVars: [EnvVarInput!]
}
```

Resolver flattens the list to `dict[str, dict]` (raising `DuplicateComponentNameError` on duplicate `name` values) before validation. Full-replacement semantics at the top level: `components: null`/omitted → omitted from the persisted dict (no change), `components: []` → explicit clear of all per-component blocks, `components: [...]` → wholesale replace of the entire dict.

Nested-omission rule (inherited from `_convert_value`): `components: [{name: "web", envVars: null}]` → `web` block is present in the persisted dict but its inner `env_vars` resolves back to absent. This is exactly the behaviour `update_environment_input_to_dict` produces for any nested Strawberry input today; we do not invent a new rule for `ComponentConfigInput`.

**Rationale**: Mirrors the env-var input grammar (typed duplicate detection). Full-replacement at the top is consistent with the rest of `UpdateDeploymentInput`. The footgun ("dropping a `components` entry on read-modify-write deletes the persisted block") is identical to the equivalent footgun on `UpdateEnvironmentInput.envVars`; the mitigation is the same — the dialog / SDK caller does a proper read-modify-write before submitting.

**Alternatives considered**:

- *Per-entry merge* — rejected; breaks input-wide grammar consistency, gives no clear path to "delete this component block".
- *Per-entry merge + explicit `delete: Boolean`* — rejected as surface-area bloat.

**Reference**: `.specify/idea-brief.md` Q4 grilling decision.

## 5. Two new typed errors — `DuplicateParameterNameError`, `DuplicateComponentNameError`

**Decision**: Add two new exception classes under `backend/styrmin_backend/services/`. Place them next to the most related existing errors:

- `DuplicateParameterNameError` → `backend/styrmin_backend/services/parameters/exceptions.py` (or wherever the existing parameter-validation errors live; verify at implementation time). `error_code = "DUPLICATE_PARAMETER_NAME"`, payload carries the offending `name`.
- `DuplicateComponentNameError` → `backend/styrmin_backend/services/env_vars/exceptions.py` (the same module where `DuplicateEnvVarNameError` lives, since both relate to deployment-input duplicate detection). `error_code = "DUPLICATE_COMPONENT_NAME"`, payload carries the offending `name`.

Both inherit from `ServiceError` so the `StructuredErrorExtension` middleware enriches the GraphQL error with the typed `extensions.code`. Both are raised from inside `update_deployment_input_to_dict()` so they fire before any Pydantic validation runs and before the resolver forwards anything to the service function.

**Rationale**: The list-flatten step is the only natural location to detect duplicates, and it lives at the GraphQL-input-conversion boundary, so the error needs to surface from there. Re-using the existing `ServiceError` plumbing means zero new middleware work. Putting the errors next to their conceptual siblings keeps the exception-module layout coherent.

**Alternatives considered**:

- *Raise a generic `ValueError` from the conversion helper and catch + translate in the resolver* — rejected; needless indirection.
- *Detect duplicates in the Pydantic validator on `DeploymentConfig` / `Deployment.parameters`* — rejected; the validator runs on the already-flattened dict, by which point duplicate keys are silently collapsed with last-wins semantics. Detection must happen on the list-of-tuples, which means at the conversion boundary.

**Reference**: `backend/styrmin_backend/services/env_vars/exceptions.py:DuplicateEnvVarNameError` (the model for the new errors).

## 6. Hard cutover — remove the JSON arguments in the same commit

**Decision**: In the same release that adds `UpdateDeploymentInput`, remove the four legacy arguments (`name`, `config: JSON`, `parameters: JSON`, `serviceNameOverrides: [ServiceNameOverride!]`) from the `updateDeployment` mutation. No transitional period during which both signatures coexist. The cutover touches the following in-tree consumers (a full audit was done at planning time; no external consumers found):

- `backend/styrmin_backend/api/schema/mutation.py:761-788` — the resolver itself
- `backend/styrmin_backend/api/definitions/deployment/inputs.py` — new file
- `backend/styrmin_backend/api/definitions/config/inputs.py` — new file (shared leaves)
- `backend/styrmin_backend/api/definitions/environment/inputs.py` — re-export shared leaves
- `python_sdk/src/styrmin_sdk/graphql/update_deployment.graphql` — query def update
- `python_sdk/src/styrmin_sdk/graphql/_generated/*` — regenerated via `uv run invoke generate`
- `python_sdk/src/styrmin_sdk/resources/deployments.py:90-104` — caller signature
- `python_sdk/tests/test_deployments.py` — call-site retarget
- `frontend/src/graphql/update_deployment.graphql` — query def update
- `frontend/src/generated/graphql.ts` — regenerated via `pnpm run codegen`
- `frontend/src/components/deployment/scheduling/SchedulingConfigDialog.tsx:64-87` — call-site retarget; this dialog must read the existing config, convert it to the typed input shape (dict→list for env vars and components), set/clear `scheduling`, and submit the full intended state to preserve today's no-other-fields-affected behaviour
- `backend/tests/e2e/drivers/api_driver.py` and `ui_driver.py` and `protocol.py` — entrypoint signatures
- `backend/tests/e2e/test_pod_scheduling.py`, `test_deployment_env_vars.py` — call-site retarget
- `backend/tests/functional/graphql/operations/update_deployment.graphql` and `update_deployment_config.graphql` — query def updates
- `backend/tests/functional/graphql/test_deployment.py`, `test_env_vars_propagation.py` — call-site retarget
- `backend/tests/functional/test_api_scheduling_config.py`, `backend/tests/functional/helpers.py` — call-site retarget
- `schema.graphql` — regenerated via `uv run styrmin export graphql-schema schema.graphql`

The `actions/primitives.py` and `services/environments.py` references found in the audit are about `updateDeploymentVersion` (a different mutation) and a doc comment respectively; neither is affected.

**Rationale**: 009 set the cutover precedent. Codegen forces both SDK and frontend onto the new shape the moment the schema changes; a transitional period would mean shipping `@deprecated` JSON args that no caller would ever use after the regen lands. The full audit confirmed no external (non-frontend, non-SDK) callers exist, so the Assumption in the spec is verified at planning time.

**Alternatives considered**:

- *Ship both signatures for one release, deprecate JSON args* — rejected; adds dead surface area with no realistic benefit.
- *Ship the typed input alongside the JSON args as an `inputV2` argument* — rejected; permanently bifurcates the surface.

**Reference**: `specs/archive/009-environment-update/plan.md` for the cutover pattern.

## 7. End-to-end test scope

**Decision**: One new E2E `test_update_deployment_typed_input_propagates_component_env_var_and_scheduling`, placed under `backend/tests/e2e/test_deployment_typed_input.py`, marked `@pytest.mark.api_only(reason="SDK-driven; no UI flow exercised — the [ui-chromium] variant would just re-run the same SDK call.")` per the AGENTS.md dual-entrypoint rule. The test:

1. Provisions a deployment fixture with one declared component named `web` (use the existing test-driver fixture).
2. Calls `client.deployments.update(deployment_id, input=UpdateDeploymentInput(components=[ComponentConfigInput(name="web", env_vars=[EnvVarInput(name="OTEL", value="https://otel.staging")])], scheduling=SchedulingInput(resources=ResourceRequirementsInput(requests=ResourceSpecInput(cpu="200m")))))`.
3. Waits one reconcile cycle.
4. Asserts the `web` pod carries `OTEL=https://otel.staging` and a container CPU request of `200m`.
5. Issues a follow-up call with an invalid env-var name (`1invalid`) in the `components.*.envVars` block and asserts the response carries `extensions.code = "INVALID_ENV_VAR_NAME"` with the offending name in the payload.

**Rationale**: Exercises both new mechanics — typed component env vars and conversion of a deeply nested input — in one fixture. The api_only mark saves ~20 minutes of CI per run with no coverage loss (the frontend caller is exercised by Vitest under `pnpm test`).

**Alternatives considered**:

- *Two E2Es (happy path + error path)* — rejected; doubles fixture cost for marginal isolation.
- *Run under both `[api-chromium]` and `[ui-chromium]`* — rejected per AGENTS.md heuristic; no UI flow is asserted.

**Reference**: `AGENTS.md` dual-entrypoint rule; `.specify/idea-brief.md` Q5 grilling decision.

## 8. Propagation-test coverage scope

**Decision**: Add boundary-propagation unit tests under `backend/tests/functional/graphql/` for each new input field on `UpdateDeploymentInput`, `ComponentConfigInput`, and `ParameterValueInput`. The full matrix is enumerated in `contracts/graphql.md` §4. Each test follows the pattern in `dev/guides/graphql-propagation-tests.md`: submit a real GraphQL mutation through the schema, assert the value reaches the database, then read it back and assert it round-trips.

Additionally, error-code propagation tests cover every error code from FR-008 and FR-009 in both scopes (top-level + per-component for env-var errors): `INVALID_ENV_VAR_NAME` × 2, `ENV_VAR_SIZE_LIMIT_EXCEEDED` × 2, `DUPLICATE_ENV_VAR_NAME` × 2, `UNKNOWN_COMPONENT_ENV_VAR` × 1 (only per-component), `DUPLICATE_PARAMETER_NAME` × 1, `DUPLICATE_COMPONENT_NAME` × 1 = **9 error-propagation tests**.

**Rationale**: Constitution §V makes this non-negotiable. The matrix in §4 makes it impossible to forget a field.

**Reference**: `dev/guides/graphql-propagation-tests.md`.

## 9. Codegen + frontend retargeting strategy

**Decision**: Run `uv run styrmin export graphql-schema schema.graphql && uv run invoke generate` and `cd frontend && pnpm run codegen` as part of the implementation tasks. The frontend `SchedulingConfigDialog.tsx` is the only non-test frontend caller; its post-cutover behaviour preserves today's read-existing-config-then-write pattern, but converts the existing config dict (which has `envVars: {NAME: VALUE}` dict-shape and `components: {NAME: {...}}` dict-shape from the read API) to the new input list-shape before submitting. A small helper `deploymentConfigToInput(config)` in `frontend/src/lib/deployment-input.ts` does this conversion in one place so future callers don't have to re-derive it.

**Rationale**: The conversion is non-trivial enough (dict→list + scope-tagged env vars) that inlining it in the dialog is fragile. A helper next to the typed mutation makes the post-cutover ergonomics survive future callers.

**Alternatives considered**:

- *Inline the conversion in the dialog* — rejected; fragile.
- *Move the conversion to the GraphQL layer (resolver)* — would force the resolver to accept both shapes, defeating the purpose of typing the input.

**Reference**: `frontend/src/components/deployment/scheduling/SchedulingConfigDialog.tsx:67-87` (current call site).
