# GraphQL Contract: Deployment Env Vars

This contract enumerates every GraphQL surface change introduced by the feature. Each new field/argument is one row in §3 — the propagation-test table — and **each row corresponds to one mandatory unit test** per Constitution §V.

## 1. New types

```graphql
"""A single environment variable to inject into rendered containers.

WARNING: This surface is for non-secret values only. The platform stores values in plaintext
and exposes them through any query that selects them. Do not store credentials, API keys, or
other secret material here — use the dedicated secret env var path (separate ticket) once available."""
type EnvVar {
  """POSIX-portable env var name, matching ^[A-Za-z_][A-Za-z0-9_]*$."""
  name: String!
  """The value to set. May be the empty string. NOT for secret material; see the EnvVar type description."""
  value: String!
}

"""A bundle of env vars targeting one component, with orphan flag."""
type ComponentEnvVars {
  """Name of the targeted component."""
  component: String!
  """The env vars set on this component."""
  envVars: [EnvVar!]!
  """True when the deployment's current driver no longer declares this component;
  orphaned blocks are visible in the API but are NOT injected into rendered pods."""
  isOrphaned: Boolean!
}

"""Doc-only declaration of an env var the driver's app respects."""
type DriverEnvVarDoc {
  """POSIX-portable env var name."""
  name: String!
  """Free-form description shown to driver consumers."""
  description: String!
  """Scope at which the env var is meaningful: deployment-wide or per-component."""
  level: DriverEnvVarLevel!
  """When level=COMPONENT, the component names this declaration applies to.
  Empty for level=DEPLOYMENT."""
  components: [String!]!
}

enum DriverEnvVarLevel {
  DEPLOYMENT
  COMPONENT
}

"""Collision between an operator-set env var and a chart-rendered env entry of the same name.
The operator-set value wins; this record exposes the chart value for audit."""
type EnvVarCollision {
  """Component the colliding container belongs to. Null if the workload is not under any component."""
  component: String
  """Container name within the pod template."""
  container: String!
  """The colliding env var name."""
  name: String!
  """Value the Helm chart rendered for this name."""
  chartValue: String!
  """Value the operator set, which wins."""
  userValue: String!
}
```

## 2. Field additions to existing types

```graphql
extend type Environment {
  """Env vars set at the environment scope. Empty when none are set."""
  envVars: [EnvVar!]!
}

extend type Deployment {
  """Effective deployment-level env vars (after merging environment & deployment scopes,
  but BEFORE component-level overrides). Empty when none are set."""
  envVars: [EnvVar!]!
  """Per-component effective env vars, including orphaned blocks (isOrphaned=true).
  Component-level entries override deployment- and environment-level entries on a per-key basis."""
  componentEnvVars: [ComponentEnvVars!]!
}

extend type ApplicationDriverVersion {
  """Doc-only env var declarations from the driver's spec.env_vars block. Empty when none declared."""
  envVars: [DriverEnvVarDoc!]!
}

extend type DeploymentTimelineEntry {
  """Chart-vs-user env var collisions detected during the reconcile this entry represents.
  Empty when no collisions occurred."""
  envVarCollisions: [EnvVarCollision!]!
}
```

## 3. Mutation input changes

**No new mutation arguments are added.** Env vars travel through the existing JSON arguments:

| Mutation | Existing argument | Schema path for env vars |
|---|---|---|
| `deploy(config: JSON, ...)` | `config` | `{ env_vars: { NAME: "VALUE", ... }, components: { <name>: { env_vars: { NAME: "VALUE" } } } }` |
| `updateDeployment(config: JSON, ...)` | `config` | same as above |
| `updateEnvironmentConfig(config: JSON, ...)` (or current equivalent) | `config` | `{ env_vars: { NAME: "VALUE", ... } }` |

Validation is enforced by the Pydantic models (`EnvironmentConfig`, `DeploymentConfig`) on the server side. Errors surface through the existing `StructuredErrorExtension` middleware as the codes documented in `data-model.md` §7.

## 4. Propagation test matrix (Constitution §V)

Each row below maps a new schema element to one mandatory propagation test assertion. The full list lives in `backend/tests/unit/api/schema/test_env_vars_propagation.py`. **A schema element is not "done" until its row is green** (Constitution §V, non-negotiable).

| Schema element | Propagation test assertion |
|---|---|
| `Environment.envVars` (read) | `updateEnvironmentConfig(config: { env_vars: { X: "y" } })` → query `Environment.envVars` returns `[{name: "X", value: "y"}]`. |
| `Deployment.envVars` (read) | `updateDeployment(config: { env_vars: { X: "y" } })` → query `Deployment.envVars` returns `[{name: "X", value: "y"}]`. |
| `Deployment.componentEnvVars` (read) | `updateDeployment(config: { components: { worker: { env_vars: { X: "y" } } } })` → query returns `[{component: "worker", envVars: [{name: "X", value: "y"}], isOrphaned: false}]`. |
| `ComponentEnvVars.isOrphaned` (read) | After driver upgrade removes "worker": query returns `[{component: "worker", envVars: [...], isOrphaned: true}]` and the resolved post-render patches contain no `worker` env entries. |
| `ApplicationDriverVersion.envVars` (read) | Driver YAML with `spec.env_vars: [{name: LOG_LEVEL, ...}]` → query returns the doc list shaped per `DriverEnvVarDoc`. |
| `DeploymentTimelineEntry.envVarCollisions` (read) | A reconcile where chart sets `LOG_LEVEL=warn` and operator sets `LOG_LEVEL=debug` → query exposes `envVarCollisions` with one entry; rendered pod has only `LOG_LEVEL=debug`. |

The propagation tests use the helper recipes in `dev/guides/graphql-propagation-tests.md` and run against the real service + repository layers per the project's mandatory rule.

## 5. Backwards compatibility

- All new fields default to empty lists; existing clients that do not select them are unaffected.
- The new `EnvironmentConfig.env_vars` / `DeploymentConfig.env_vars` JSON keys are optional in the input; existing JSON config payloads remain valid.
- Driver `spec.env_vars` is optional; existing drivers register unchanged.
- `PostRenderInjection.env_vars` defaults to `None` (inherits → `True`); existing `PostRenderInjection` payloads remain valid.

## 6. Out-of-contract surfaces (deliberate)

- No new mutation.
- No new typed mutation argument (per Research §1).
- No `Cluster.envVars` field (cluster scope deferred — PRD §"Out of Scope").
- No `valueFrom`-style secret references (deferred to a separate ticket).
- No per-container scoping (components are the smallest addressable unit).
