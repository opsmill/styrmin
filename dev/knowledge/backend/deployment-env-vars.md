# Deployment Env Vars

A free-form `dict[str, str]` of environment variables that operators can set
on a deployment without a driver change. Auto-injected into rendered workloads
via the existing post-render injection pipeline.

This page is the operator/contributor reference. The decisions behind the
shape are in [ADR-019](../../adr/adr-019-deployment-env-vars.md); the full
contract lives in [`specs/008-deployment-env-vars/`](../../../specs/008-deployment-env-vars/).

## When to reach for env vars

Use env vars when the app you are deploying respects an environment variable
(a log level, a telemetry endpoint, a feature flag) and the driver author has
not exposed it as a typed parameter. They are the deliberate escape hatch for
the long tail of inputs that are too transient or too one-off to warrant a
driver change.

Use **typed parameters** instead when the input is structural and stable —
required, defaulted, validated, surfaced in the deployment editor with proper
hand-rails. Env vars are intentionally the un-typed sibling and skip all of
that.

## Three scopes, deepest-wins

Env vars are settable at three scopes. Resolution merges them with **per-key
deepest-wins**: a key set at the component scope wins over the same key at the
deployment scope, which wins over the same key at the environment scope.

| Scope | Where it's set | Affects |
|-------|----------------|---------|
| Environment | `Environment.config.env_vars` | Every deployment in the environment |
| Deployment | `Deployment.config.env_vars` | Every component of one deployment |
| Component | `Deployment.config.components.<name>.env_vars` | One component of one deployment |

The merge runs inside the resolver and produces one `ResolvedComponentEnvVars`
per driver-declared component, including provenance (which scope set each
key). This mirrors the `SchedulingConfig` precedent — see
[`services.md`](services.md) for where in the resolver the merge fits.

## Setting values via the API

Writes ride the existing `config: JSON` argument on `deploy()` /
`updateDeployment()` / `updateEnvironment()`. There is no new mutation and no
new typed mutation argument.

```graphql
# Deployment scope
mutation {
  updateDeployment(
    deploymentId: "..."
    config: { env_vars: { LOG_LEVEL: "debug" } }
  ) { id }
}

# Per-component scope
mutation {
  updateDeployment(
    deploymentId: "..."
    config: {
      components: {
        worker: { env_vars: { WORKER_QUEUE: "orders" } }
      }
    }
  ) { id }
}
```

Reads are typed: `Environment.envVars`, `Deployment.envVars`,
`Deployment.componentEnvVars`. The full GraphQL surface is enumerated in
[`specs/008-deployment-env-vars/contracts/graphql.md`](../../../specs/008-deployment-env-vars/contracts/graphql.md).

## Driver-side documentation

Drivers may include a `spec.env_vars` block to advertise the env vars their
app respects. The block is **doc-only** — it does not validate, default, or
constrain user-set values. Driver consumers see it via
`ApplicationDriverVersion.envVars`.

```yaml
# driver.styrmin.yml
spec:
  env_vars:
    - name: LOG_LEVEL
      description: Application log level
      level: deployment
    - name: WORKER_QUEUE
      description: Queue name the worker consumes
      level: component
      components: [worker]
```

The loader validates the **shape** of the declarations (name regex, name
uniqueness, `level=component → non-empty components`, every `components`
reference exists) and refuses to register a driver whose block fails any of
those checks.

## Size caps

| Cap | Limit | Enforcement |
|-----|-------|-------------|
| Per-value | 64 KiB | Mutation reject |
| Per-scope dict (entries) | 100 | Mutation reject |
| Per-scope dict (bytes) | 256 KiB | Mutation reject |
| Resolved per-component dict | 256 KiB | Resolution failure |
| Resolved total per deployment | 1 MiB | Resolution failure |

The per-deployment total leaves headroom under Kubernetes' 1.5 MiB resource
size limit (the deployment CRD context-embedding mechanism, ADR-006, carries
the resolved env vars alongside the rest of the resolved context).

Names must match `^[A-Za-z_][A-Za-z0-9_]*$`. Empty values (`""`) are
accepted. Duplicate names within a single scope are rejected before the dict
is built.

## Upgrade orphans

If a driver upgrade renames or removes a component carrying per-component env
vars, the upgrade succeeds. The orphaned block becomes visible via
`ComponentEnvVars.isOrphaned = true` and is **not** injected into any pod.
Operators audit and remove orphans through the same `updateDeployment`
mutation. Rolling the driver back to a version that re-introduces the
component name turns the block live again.

## Component-level injection opt-out

A driver can mark a component (typically a sidecar or debug container) as
opted out of injection by setting `inject.env_vars: false` on its component
config. Peer components in the same deployment continue to receive operator-set
env vars; the opted-out component's pod containers retain their chart-rendered
env entries unchanged.

## ⚠️ No secrets

The platform stores env var values in plaintext and exposes them through any
GraphQL query that selects them. **Do not store credentials, API keys, tokens,
or other secret material in env vars.** A typed secret env var variant
(`valueFrom.secretKeyRef`-style) is a separate ticket and is not yet shipped.

The `EnvVar` GraphQL type description carries this warning at the API
boundary; type-aware UI surfaces should propagate it.

Names matching the `PATH | LD_* | PYTHONPATH | RUBYLIB | NODE_PATH |
JAVA_TOOL_OPTIONS` family emit a structured `logger.warning` at the validator;
they are accepted but flagged because operators have shot themselves in the
foot setting them in the past.

## Implementation pointers

| Concern | Location |
|---------|----------|
| Pydantic config models | `backend/styrmin_backend/context/models/config.py` (`EnvironmentConfig.env_vars`, `DeploymentConfig.env_vars`) |
| Validator | `backend/styrmin_backend/services/env_vars/validator.py` |
| Resolver (merge + orphan detection) | `backend/styrmin_backend/services/env_vars/resolver.py` |
| Patch builder (post-render injection) | `backend/styrmin_backend/services/env_vars/patch_builder.py` |
| Driver-side docs | `backend/styrmin_backend/services/driver/models/resources/env_vars.py` |
| GraphQL types | `backend/styrmin_backend/api/definitions/deployment/model.py`, `.../environment/model.py`, `.../application_driver/model.py`, `.../deployment_timeline/model.py` |
| E2E coverage | `backend/tests/e2e/test_deployment_env_vars.py` |
| Propagation tests | `backend/tests/functional/graphql/test_env_vars_propagation.py` |

## Related

- [ADR-019: Deployment Env Vars](../../adr/adr-019-deployment-env-vars.md) — durable record of the design decisions.
- [ADR-006: Embed GlobalContext in StyrminDeployment CRD](../../adr/adr-006-embed-context-in-deployment-crd.md) — the carrier mechanism that flows resolved env vars to the operator/agent.
- [`services.md`](services.md) — surrounding service-layer architecture.
- [`api.md`](api.md) — surrounding GraphQL API surface.
- [`specs/008-deployment-env-vars/`](../../../specs/008-deployment-env-vars/) — full feature spec, plan, contracts, and quickstart.
