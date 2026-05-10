# GraphQL Contract: Environment-Config Update with Deployment Fanout

This contract enumerates every GraphQL surface change introduced by the feature. Each new schema element is one row in §4 — the propagation-test matrix — and **each row corresponds to one mandatory unit test** per Constitution §V.

## 1. New input types

```graphql
"""Full-replacement input for environment configuration updates.
Submit the complete desired configuration; any field omitted is persisted as unset."""
input UpdateEnvironmentInput {
  envVars: [EnvVarInput!]
  ipWhitelist: [String!]
  dedicatedIngress: DedicatedIngressInput
  scheduling: SchedulingInput
  fqdnSuffix: String
  externalUrlScheme: ExternalUrlScheme
  externalUrlPort: Int
  externalDnsEndpointsType: ExternalDnsEndpointsType
}

"""A single environment variable name/value pair to set on the environment."""
input EnvVarInput {
  name: String!
  value: String!
}

"""Dedicated ingress controller configuration for the environment.
Mirrors DedicatedIngressConfig field-for-field."""
input DedicatedIngressInput {
  className: String
  resources: ResourceRequirementsInput
  scheduling: SchedulingInput
  hostnameOverride: String
  # ... (exhaustive list mirrors the Pydantic model at implementation time)
}

"""Pod scheduling configuration. Mirrors SchedulingConfig field-for-field."""
input SchedulingInput {
  podAffinity: AffinityBlockInput
  podAntiAffinity: AffinityBlockInput
  nodeAffinity: AffinityBlockInput
  topologySpreadConstraints: [TopologySpreadConstraintInput!]
  resources: ResourceRequirementsInput
  tolerations: [TolerationInput!]
  runtimeClass: String
  inject: PostRenderInjectionInput
}

input AffinityBlockInput { required: [AffinityRuleInput!]; preferred: [AffinityRuleInput!] }
input ResourceRequirementsInput { requests: ResourceSpecInput; limits: ResourceSpecInput }
input ResourceSpecInput { cpu: String; memory: String; ephemeralStorage: String; extended: JSON }
input TolerationInput { key: String; operator: TolerationOperator; value: String; effect: TolerationEffect; tolerationSeconds: Int }
input TopologySpreadConstraintInput { maxSkew: Int!; topologyKey: String!; whenUnsatisfiable: WhenUnsatisfiable!; labelSelector: LabelSelectorInput }
input PostRenderInjectionInput { podAffinity: Boolean; nodeAffinity: Boolean; topologySpread: Boolean; resources: Boolean; tolerations: Boolean; runtimeClass: Boolean; envVars: Boolean }

enum ExternalUrlScheme { HTTP HTTPS }
enum ExternalDnsEndpointsType { NODE_EXTERNAL_IP CLUSTER_IP }
enum TolerationOperator { EXISTS EQUAL }
enum TolerationEffect { NO_SCHEDULE PREFER_NO_SCHEDULE NO_EXECUTE }
enum WhenUnsatisfiable { DO_NOT_SCHEDULE SCHEDULE_ANYWAY }
```

The illustrative list above is not exhaustive — the implementer's contract is "every field of `EnvironmentConfig` (and its nested types) gets an input mirror, every Pydantic enum gets a Strawberry enum mirror". Whatever the Pydantic model exposes at implementation time is what ships.

## 2. Mutation argument changes

```graphql
extend type Mutation {
  """Update an environment's full configuration with a typed input. Triggers
  a redeploy fanout: every non-tombstoned, non-internal deployment in the
  environment receives a fresh ApplicationInstance version and a redeploy Task.
  Returns when the env-config row is persisted and Tasks are dispatched
  (does not block on Task completion). Per-deployment Task failures are tracked
  on the affected deployment's timeline; they do not roll back the env-config
  update or affect peer deployments. A no-op update (input byte-for-byte
  identical to the persisted config) skips the fanout."""
  updateEnvironment(
    environmentId: UUID!
    input: UpdateEnvironmentInput!
  ): Environment
}
```

**Removed**: the prior `config: JSON` argument. Per FR-001 + FR-024 it is removed cleanly — no deprecation window. Any caller still passing the old shape gets a schema validation error at request time.

## 3. Read-side surface (used by the frontend, no new fields)

The frontend's environment-detail page reads `Environment.config` (already typed post-008), `Environment.envVars` (added in 008), and `Environment.deployments` (existing). **No new query fields are added by this feature** — the read side already projects what US3/US4 need. If projection gaps are discovered during implementation, they become part of US3's scope rather than this contract.

## 4. Propagation test matrix (Constitution §V)

Each row maps a new input field to one mandatory propagation test assertion. Tests live in `backend/tests/functional/graphql/test_environment_update_propagation.py`. **A schema element is not "done" until its row is green** (Constitution §V, non-negotiable).

### Top-level `UpdateEnvironmentInput` fields

| Field | Propagation test assertion |
|---|---|
| `envVars` (write-then-read round-trip) | `updateEnvironment(input: { envVars: [{name: "X", value: "y"}] })` → query `Environment.envVars` returns `[{name: "X", value: "y"}]`. |
| `ipWhitelist` | `updateEnvironment(input: { ipWhitelist: ["10.0.0.0/8"] })` → query `Environment.config` shows `ipWhitelist: ["10.0.0.0/8"]`. |
| `fqdnSuffix` | `updateEnvironment(input: { fqdnSuffix: "test.example.com" })` → query shows the suffix. |
| `externalUrlScheme` | `updateEnvironment(input: { externalUrlScheme: HTTPS })` → query shows `HTTPS`. |
| `externalUrlPort` | `updateEnvironment(input: { externalUrlPort: 8443 })` → query shows `8443`. |
| `externalDnsEndpointsType` | `updateEnvironment(input: { externalDnsEndpointsType: NODE_EXTERNAL_IP })` → query shows it. |
| `dedicatedIngress` (nested) | `updateEnvironment(input: { dedicatedIngress: { className: "nginx" } })` → query shows it. |
| `scheduling` (nested) | `updateEnvironment(input: { scheduling: { runtimeClass: "kata" } })` → query shows it. |

### Nested input fields (one assertion per nested-type field)

The implementer's job is to add one row per nested input field at implementation time, against the actual final shape of the input types. Use the parameter+scheduling propagation tests from 008 as the recipe.

### Behavioural rows (not field-projection)

| Behaviour | Propagation test assertion |
|---|---|
| Full-replacement semantics | Pre-seed an environment with `ipWhitelist: ["10.0.0.0/8"]`. `updateEnvironment(input: { envVars: [{name: "X", value: "y"}] })` (omitting `ipWhitelist`) → query shows `ipWhitelist: []` (cleared). |
| `INVALID_ENV_VAR_NAME` rejection | `updateEnvironment(input: { envVars: [{name: "1bad", value: "y"}] })` → response carries one error with `extensions.code = "INVALID_ENV_VAR_NAME"`. |
| `ENV_VAR_SIZE_LIMIT_EXCEEDED` rejection | `updateEnvironment(input: { envVars: [{name: "X", value: "<65 KiB>"}] })` → `extensions.code = "ENV_VAR_SIZE_LIMIT_EXCEEDED"`. |
| `DUPLICATE_ENV_VAR_NAME` rejection | `updateEnvironment(input: { envVars: [{name: "X", value: "1"}, {name: "X", value: "2"}] })` → `extensions.code = "DUPLICATE_ENV_VAR_NAME"`. |
| `ENVIRONMENT_NOT_FOUND` rejection | `updateEnvironment(environmentId: "<random uuid>", input: {})` → `extensions.code = "ENVIRONMENT_NOT_FOUND"`. |
| Fanout dispatch (mutation-result coupling) | Pre-seed environment with two deployments (one valid, one tombstoned). `updateEnvironment(input: { envVars: [{name: "X", value: "y"}] })` → mutation succeeds; check that exactly one redeploy Task was created (the non-tombstoned deployment); the tombstoned deployment has no new Task. |
| Per-deployment no-op skip | Pre-seed environment with two deployments **already at config v1** (their active instances were generated against config v1). `updateEnvironment(input=v1)` → mutation succeeds; **zero new Tasks** created on either deployment (per-deployment no-op detection skips both). |
| Partial-fanout recovery | Pre-seed environment with three deployments where two are at config v2 and one is at config v1 (simulating a prior partial-fanout failure). `updateEnvironment(input=v2)` → mutation succeeds; **exactly one new Task** created for the v1 laggard; zero new Tasks on the two already-at-v2 deployments. |
| Commit ordering (FR-009a) | Mock the redeploy dispatch path to raise on the first deployment in the fanout. `updateEnvironment(input=...)` → mutation surfaces the env-config row as updated (the row is committed before any dispatch), the failing deployment's dispatch is logged as a fanout dispatch failure, peer deployments still receive Tasks. The persisted env-config MUST reflect the new input regardless of dispatch outcomes. |

## 5. Removed surface (clean replace)

After this feature ships, the following MUST NOT be present anywhere in the schema, SDK, or frontend codegen:

- `Mutation.updateEnvironment(environmentId, config: JSON)` — replaced by the typed-input form.

CI's `Pre-Commit Hooks` job + the `GraphQL schema freshness` hook ensure the regenerated artefacts reflect the new shape.

## 6. Backwards compatibility

This is a **breaking change** for any caller that constructed the old JSON-blob shape. The user explicitly chose clean replace over a deprecation window (recorded in research.md §7). Internal consumers (SDK, frontend, E2E tests) update in the same PR. There are no known external consumers of the previous mutation surface.
