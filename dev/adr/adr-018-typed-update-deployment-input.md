# ADR-018: Typed `UpdateDeploymentInput` — List-Shaped Named Fields and Parameters-Merge Asymmetry

**Status**: Accepted
**Date**: 2026-05-16
**Source**: specs/archive/011-typed-deployment-input/ (research §1, §3, §4, §5; data-model.md §1, §3, §4)
**Builds on**: [ADR-012](adr-012-environment-config-fanout.md) (full-replacement typed input convention, clean-replace cutover), [ADR-014](adr-014-schema-walking-input-propagation-tests.md) (schema-walking propagation tests), [ADR-015](adr-015-frontend-value-transform-boundary.md) (frontend submit-boundary transforms).

## Context

ADR-012 established the typed-input convention for environment-config writes: a hand-rolled Strawberry input mirroring the Pydantic configuration model, full-replacement semantics at the top level, clean-replace cutover. Spec 011 ports the same pattern to `updateDeployment`, which until this feature accepted four loose arguments (`name`, `config: JSON`, `parameters: JSON`, `serviceNameOverrides`). Three decisions in the port are non-obvious and worth recording:

1. **How named-dict-typed config fields travel on the wire.** The deployment-configuration shape contains three fields whose persisted form is a Pydantic-typed `dict[str, T]` keyed by a human-meaningful name: top-level `env_vars` (`dict[str, str]`), `parameters` (`dict[str, Any]`), and `components` (`dict[str, ComponentConfigBlock]`). Three input shapes were on the table: `JSON` (round-trips opaquely, no typed duplicate detection), `dict` (no GraphQL dict primitive exists), or `list[{name, value, …}]` flattened to dict at the conversion boundary.

2. **Merge vs. full-replacement for `parameters`.** ADR-012 settled on full-replacement everywhere on `UpdateEnvironmentInput`. The same convention applied uniformly to `UpdateDeploymentInput.parameters` would force every caller — CLI bumping a single replica count, SDK script changing one image tag — to read-modify-write the entire parameters dict before submitting. The existing JSON-path resolver merges (`merged = {**deployment.parameters, **submitted}`); preserving that behaviour silently means asymmetric semantics inside one otherwise-uniform input.

3. **Where shared leaf inputs live.** ADR-012's leaves (`EnvVarInput`, `SchedulingInput`, `DedicatedIngressInput`, `AffinityBlockInput`, the enum mirrors, the recursive `_convert_value` helper) were defined under `api/definitions/environment/inputs.py` because environment was the only consumer. With deployment becoming a second consumer, importing leaves from `environment/inputs.py` into `deployment/inputs.py` would create a misleading "deployment depends on environment" import direction at the GraphQL-definitions layer that does not exist at the domain level.

## Decision

### 1. List-of-`{name, value, …}` for named-dict-typed config fields

Every named-dict-typed config field on `UpdateDeploymentInput` (and by extension on future typed inputs that mirror a Pydantic `dict[str, T]`) is declared as a **list of typed objects** where the first field is the dict key:

```graphql
input ParameterValueInput {
  name: String!
  value: JSON!
}

input ComponentConfigInput {
  name: String!
  envVars: [EnvVarInput!]
}

input UpdateDeploymentInput {
  parameters: [ParameterValueInput!]    # → dict[str, Any]
  components: [ComponentConfigInput!]   # → dict[str, dict]
  envVars: [EnvVarInput!]               # → dict[str, str]
  # ... other config fields
}
```

The conversion helper (`update_deployment_input_to_dict` in `api/definitions/deployment/inputs.py`) flattens each list to its dict shape **at the GraphQL-input boundary**, raising a typed `ServiceError` subclass on duplicate keys:

- `parameters` → `DuplicateParameterNameError` (`error_code = "DUPLICATE_PARAMETER_NAME"`)
- `components` → `DuplicateComponentNameError` (`error_code = "DUPLICATE_COMPONENT_NAME"`)
- `envVars` → `DuplicateEnvVarNameError` (existing, scoped `"deployment"` or `"component:<name>"`)

Both new errors inherit from `ServiceError`, surface via the existing `StructuredErrorExtension` middleware, and ship with payloads identifying the offending name (and scope, for component env vars).

### 2. `parameters` keeps merge semantics; everything else is full-replacement

`UpdateDeploymentInput.parameters` is the **one deliberate exception** to the full-replacement convention from ADR-012. When the input provides a `parameters` list, the resolver derives `dict[str, Any]` and forwards it to the existing `services/deployment.py::update_deployment(deployment_parameters=...)` service function, which preserves its current merge step (`merged = {**deployment.parameters, **submitted}`). All other top-level fields on the input are full-replacement: omitting `envVars` from the input clears the persisted top-level env-vars dict; passing `components: []` clears every per-component block.

The asymmetry MUST be documented on the GraphQL field description for `UpdateDeploymentInput.parameters` so introspection consumers see it without reading source. This is the asymmetry pretended-away alternative is rejected.

### 3. Shared leaf inputs live under `api/definitions/config/inputs.py`

Leaf inputs reused across `UpdateEnvironmentInput` and `UpdateDeploymentInput` move from `api/definitions/environment/inputs.py` into a new `api/definitions/config/inputs.py` module. The top-level inputs (`UpdateEnvironmentInput`, `UpdateDeploymentInput`) and their entity-specific conversion helpers stay co-located with their entities (`api/definitions/environment/inputs.py`, `api/definitions/deployment/inputs.py`); each imports the shared leaves from `config/inputs.py`. `environment/inputs.py` re-exports the leaves it moved out for backwards compatibility within the same release.

The leaves to extract are: `EnvVarInput`, `LabelSelectorInput`, `LabelSelectorRequirementInput`, `DeploymentReferenceInput`, `AffinityTermInput`, `WeightedAffinityTermInput`, `AffinityBlockInput`, `ResourceSpecInput`, `ResourceRequirementsInput`, `TolerationInput`, `TopologySpreadConstraintInput`, `PostRenderInjectionInput`, `SchedulingInput`, `IngressServiceConfigInput`, `DedicatedIngressInput`, and the enum mirrors (`ExternalUrlScheme`, `ExternalDnsEndpointsType`, `TolerationOperator`, `TolerationEffect`, `WhenUnsatisfiable`, `LabelSelectorOperator`). The recursive `_convert_value` helper moves to `config/inputs.py` because both top-level converters need it.

`config/inputs.py` matches the Pydantic side, where `BaseConfigSection` / `ClusterConfig` / `EnvironmentConfig` / `DeploymentConfig` all live in `context/models/config.py`. The naming makes the parallelism between "Pydantic config models" and "GraphQL config inputs" discoverable.

## Consequences

- **Typed duplicate detection at the wire boundary.** Submitting two `parameters` entries with the same `name` produces a typed `DUPLICATE_PARAMETER_NAME` error before the resolver forwards anything to the service function; same for `DUPLICATE_COMPONENT_NAME` and the existing `DUPLICATE_ENV_VAR_NAME`. Detection at the dict-flatten step is the **only** natural location — by the time the dict is built, duplicate keys silently collapse with last-wins semantics, and downstream Pydantic validators see a single value.
- **Symmetric input grammar across the three named-dict fields.** `parameters`, `components`, and `envVars` all use the same shape on the wire (`list[{name, …}]`), all use the same flatten-with-duplicate-detection rule, all produce the same class of typed error. Future typed inputs adding named-dict-typed config fields slot into the same pattern without inventing per-field grammars.
- **Convention to replicate.** Any future typed input that mirrors a Pydantic `dict[str, T]` field MUST use the list-of-`{name, value, …}` shape with a `name: String!` first field and a typed duplicate-name error raised from the conversion helper. JSON-typed dict inputs (`Map<String, T>` shape) are forbidden; they bypass introspection of value structure and bypass typed duplicate detection.
- **`parameters` merge asymmetry is load-bearing and visible.** Operators bumping one parameter value continue to work with a single-entry `parameters: [{name, value}]` input; the unnamed keys survive. The GraphQL field description on `UpdateDeploymentInput.parameters` carries the asymmetry warning so SDK/GraphiQL consumers see it from introspection alone.
- **`components: []` and `envVars: []` clear, omitted does not.** Explicit empty list = full clear; omitted/null field = "do not touch". The recursive `_convert_value` helper preserves the nested-omission rule for `ComponentConfigInput.envVars`: `components: [{name: "web", envVars: null}]` keeps the `web` key but collapses its inner env-vars block to its absent state.
- **Import direction matches domain dependency.** `deployment/inputs.py → config/inputs.py ← environment/inputs.py` is one directed graph rooted at the shared config module; the previous "deployment depends on environment" misdirection is gone. Future typed inputs (e.g. cluster, application-driver) follow the same shape: top-level input in entity-specific module, shared leaves in `config/inputs.py`.
- **No service-layer signature change.** The resolver derives the four legacy arguments (`deployment_config`, `deployment_parameters`, `deployment_name`, `service_name_overrides`) from the converted dict and forwards them to the existing `update_deployment(...)` service function unchanged. The persisted `Deployment.config` and `Deployment.parameters` dict shapes are bit-identical to what the pre-cutover JSON-blob caller produced for semantically equivalent inputs.
- **Schema-walking propagation test mandatory (ADR-014).** A test asserting `UpdateDeploymentInput`'s field set equals `set(DeploymentConfig.model_fields) ∪ {"name", "parameters", "serviceNameOverrides"}` (camelCase ↔ snake_case normalized) lives next to the per-field propagation tests; future fields added to `DeploymentConfig` and forgotten on the input fail CI loudly.
- **Frontend submit-boundary transform mandatory (ADR-015).** The frontend `deploymentConfigToInput()` helper in `frontend/src/lib/deployment-input.ts` is the documented site for converting persisted-config dict shapes (`envVars: {NAME: VALUE}`, `components: {NAME: {...}}`) into the new list-shaped input. The `SchedulingConfigDialog` and any future caller submitting `UpdateDeploymentInput` go through this helper.

## Alternatives Considered

- **`parameters: JSON | None`** — keeps the dict blob nested inside the typed input. Rejected: would lose typed duplicate detection, would lose internal grammar consistency with the rest of the input, and would re-introduce the discoverability gap the cutover was supposed to close.
- **Make `parameters` full-replacement for symmetry** — uniform full-replacement across the whole input. Rejected: forces every parameter-bump caller to read-modify-write before changing one value; silently breaks existing CLI/SDK ergonomics that today rely on merge semantics; the asymmetry is a deliberate v1 cost paid in exchange for backwards-compatible operator workflow.
- **`replaceParameters: Boolean` flag** — explicit toggle between merge and replace. Rejected as niche-knob bloat; no caller has ever asked for full-replacement on parameters, and the toggle adds a permanent surface decision to every mutation invocation.
- **Per-entry merge for `components`** — each entry in the `components` list merges into the persisted block rather than replacing it. Rejected: breaks input-wide grammar consistency (parameters would be the only merge field), and gives no clear path to "delete this component block".
- **Per-entry merge + explicit `delete: Boolean` flag on each entry** — same as above but with an opt-in clear. Rejected as surface-area bloat for a one-feature need; the full-replacement-with-explicit-empty-list contract handles the same use case with less schema surface.
- **Detect duplicates inside the Pydantic validator on `DeploymentConfig` / `Deployment.parameters`** — let the validator catch dups after the dict is built. Rejected: the validator runs on the **already-flattened** dict, by which point duplicate keys are silently collapsed with last-wins semantics. Detection must happen on the list-of-tuples, which means at the conversion boundary.
- **Raise a generic `ValueError` from the conversion helper and catch + translate in the resolver** — keeps the exception classes simple. Rejected: needless indirection; the existing `ServiceError` plumbing already routes typed codes through the middleware, and the conversion helper is the right place to raise.
- **Leave shared leaves in `environment/inputs.py` and import from there into `deployment/inputs.py`** — minimum-edit option. Rejected: creates a misleading "deployment depends on environment" import direction at the GraphQL-definitions layer where no such dependency exists at the domain level.
- **Put all GraphQL inputs in a single `inputs.py` at the `api/definitions/` root** — maximum-sharing option. Rejected: mixes top-level mutation inputs (one per mutation) with shared leaves; would get crowded as more typed mutations land and lose the entity-locality intuition.
- **Put under `api/definitions/shared/inputs.py`** — neutral-naming option. Rejected: "shared" is a non-domain word; `config/` reflects what the inputs actually model (the Pydantic configuration hierarchy that lives in `context/models/config.py`).
- **Auto-derive `UpdateDeploymentInput` from Pydantic via `strawberry.experimental.pydantic.input`** — eliminates the hand-rolling. Rejected, same rationale as ADR-012: the bridge has known issues with deeply nested optional fields, and the hand-rolled style is more debuggable and gives explicit control over GraphQL field names and enum values.
- **Per-driver-generated `ParameterValueInput.value` types** — replace `JSON!` with a per-driver-version typed value. Rejected for v1; would require per-driver schema generation, which is a much larger effort. Tracked as a follow-up; the `JSON` value type is the documented escape hatch for the genuinely-dynamic-per-driver shape.
