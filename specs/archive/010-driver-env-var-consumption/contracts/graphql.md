# GraphQL Contract: Driver-Side Env Var Consumption

This contract is **deletion-only**. No new GraphQL types, fields, arguments, or enums are introduced. The propagation matrix shrinks; no rows are added.

## 1. Removed schema elements (clean replace per FR-005..FR-011)

```graphql
# REMOVED — no longer in schema after this feature ships
type EnvVarCollision { ... }                                    # the entire type
extend type DeploymentTimelineEntry { envVarCollisions: ... }  # the field
input PostRenderInjectionInput { envVars: Boolean }            # only this field; rest of input stays
```

After 010 ships, the schema MUST NOT advertise `EnvVarCollision` or `DeploymentTimelineEntry.envVarCollisions` anywhere. The `PostRenderInjectionInput` Strawberry input retains its other inject flags (`podAffinity`, `nodeAffinity`, `topologySpread`, `resources`, `tolerations`, `runtimeClass`) but loses `envVars`.

## 2. Preserved schema elements (no change)

Every other env-vars-related GraphQL surface from 008+009 stays exactly as it was:

```graphql
type EnvVar { name: String!, value: String! }                  # KEEP
type ComponentEnvVars {                                         # KEEP
  component: String!
  envVars: [EnvVar!]!
  isOrphaned: Boolean!
}
type DriverEnvVarDoc {                                          # KEEP
  name: String!
  description: String!
  level: DriverEnvVarLevel!
  components: [String!]!
}
enum DriverEnvVarLevel { DEPLOYMENT COMPONENT }                # KEEP

input EnvVarInput { name: String!, value: String! }            # KEEP

extend type Environment {                                       # KEEP
  envVars: [EnvVar!]!
}
extend type Deployment {                                        # KEEP
  envVars: [EnvVar!]!
  componentEnvVars: [ComponentEnvVars!]!
}
extend type ApplicationDriverVersion {                          # KEEP
  envVars: [DriverEnvVarDoc!]!
}

input UpdateEnvironmentInput {                                  # KEEP (009)
  envVars: [EnvVarInput!]
  # ... other fields ...
}

extend type Mutation {                                          # KEEP (009)
  updateEnvironment(environmentId: UUID!, input: UpdateEnvironmentInput!): Environment
}
```

## 3. Propagation test matrix changes (Constitution §V)

The propagation matrix from 008's `contracts/graphql.md` §4 was carried into 009 (which reused the env-vars-related rows). **010 deletes two rows from that matrix**:

| Row (from 008+009 matrix) | Disposition |
|---|---|
| `Environment.envVars` (read + write round-trip) | KEEP — propagation test stays green |
| `Deployment.envVars` (read + write round-trip) | KEEP |
| `Deployment.componentEnvVars` (read + write round-trip) | KEEP |
| `ComponentEnvVars.isOrphaned = true` (after orphan transition) | KEEP |
| `ApplicationDriverVersion.envVars` (driver doc) | KEEP |
| `UNKNOWN_COMPONENT_ENV_VAR` mutation rejection | KEEP |
| `INVALID_ENV_VAR_NAME` rejection | KEEP |
| `ENV_VAR_SIZE_LIMIT_EXCEEDED` rejection | KEEP |
| `DUPLICATE_ENV_VAR_NAME` rejection | KEEP |
| Full-replacement semantics (009) | KEEP |
| Per-deployment no-op skip (009) | KEEP |
| Partial-fanout recovery (009) | KEEP |
| Commit ordering (009 / FR-009a) | KEEP |
| `ENVIRONMENT_NOT_FOUND` rejection | KEEP |
| `DeploymentTimelineEntry.envVarCollisions` | **REMOVED — propagation test deleted** |
| `PostRenderInjectionInput.envVars` (write through `input.scheduling.inject.envVars`) | **REMOVED — propagation test deleted** |

`grep` after the deletion sweep confirms no propagation tests assert against the removed rows.

## 4. Backwards compatibility

This is a **breaking schema change** for any caller that references `EnvVarCollision`, `DeploymentTimelineEntry.envVarCollisions`, or `PostRenderInjectionInput.envVars`. There are no known external consumers; the SDK and frontend regenerate from the schema.

The user's pivot decision (Decision 1 from the planning conversation) is **clean replace, not a feature flag**. The injection layer was always broken; nothing legitimate uses it. The deletion lands in one PR.

## 5. New driver-template surface (not GraphQL — listed here for completeness)

The driver-template Jinja context exposes:

- `instance.config.env_vars: dict[str, str] | absent`
- `components[<name>].env_vars.config: dict[str, str] | absent`

These are NOT GraphQL fields. They are Pydantic-model attributes already serialised into the rendering context dict via `model_dump(exclude_none=True)`. The contract document for driver authors is `dev/guides/driver-env-var-consumption.md` (added by US4 / FR-021); this GraphQL contracts file does not double as a driver-API contract.
