# Deployment Env Vars

A free-form `dict[str, str]` of environment variables that users can set
on a deployment without a driver change. The platform resolves the merged
dict and merges it, after the chart renders, into the **component
container** each driver component declares, by env var `name`.

This page is the user/contributor reference. The decisions behind the shape
(free-form `dict[str, str]`, three-scope deepest-wins precedence) live in
[ADR-013](../../adr/0013-driver-env-var-consumption.md); post-render
injection into the component container lives in
[ADR-055](../../adr/0055-post-render-component-overrides.md). The full
contracts are in [`specs/archive/008-deployment-env-vars/`](../../../specs/archive/008-deployment-env-vars/),
[`specs/archive/010-driver-env-var-consumption/`](../../../specs/archive/010-driver-env-var-consumption/),
and [`specs/017-post-render-env-vars/`](../../../specs/017-post-render-env-vars/).

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

<!-- Extracted from specs/009-environment-update on 2026-05-10 -->

**Environment scope** uses the typed `UpdateEnvironmentInput` mutation
introduced in spec 009 (see [ADR-012](../../adr/0012-environment-config-fanout.md)).
The mutation full-replaces the env-config row and fans out a redeploy task
per non-tombstoned, non-internal deployment in the environment:

```graphql
mutation {
  updateEnvironment(
    environmentId: "..."
    input: { envVars: [{ name: "LOG_LEVEL", value: "debug" }] }
  ) { id }
}
```

**Deployment and per-component scopes** now ride the typed
`input: UpdateDeploymentInput!` argument on `updateDeployment()`
(`deploy()` retains the `config: JSON` write path until the analogous
deploy-side migration ships). The wire layer (`EnvVarInput.value: String!`)
rejects non-string values structurally — the legacy `INVALID_ENV_VAR_VALUE`
error code is no longer reachable through `updateDeployment()` and survives
only on the deploy-side JSON path.

```graphql
# Deployment scope
mutation {
  updateDeployment(
    deploymentId: "..."
    input: { envVars: [{ name: "LOG_LEVEL", value: "debug" }] }
  ) { id }
}

# Per-component scope
mutation {
  updateDeployment(
    deploymentId: "..."
    input: {
      components: [
        {
          name: "worker",
          envVars: [{ name: "WORKER_QUEUE", value: "orders" }]
        }
      ]
    }
  ) { id }
}
```

Reads are typed: `Environment.envVars`, `Deployment.envVars`,
`Deployment.componentEnvVars`. The full GraphQL surface is enumerated in
[`specs/archive/008-deployment-env-vars/contracts/graphql.md`](../../../specs/archive/008-deployment-env-vars/contracts/graphql.md);
017 adds `Component.container`, `ComponentConfig.container`, and
`ComponentEnvVars.isApplicable` ([`contracts/graphql-deltas.md`](../../../specs/017-post-render-env-vars/contracts/graphql-deltas.md)).

### Component-scope writes need a component container

`updateDeployment` and `deploy` raise `COMPONENT_CONTAINER_NOT_DECLARED`
(`ComponentContainerNotDeclaredError`, metadata `component_name` and
`components_with_container`) when a component-scope block **adds a key or
changes a value** on a component that declares no component container in
the deployment's pinned driver version. Removals and unchanged
re-submissions pass, so the frontend's full-config submits and the removal
of stranded values keep working. The check runs after
`UNKNOWN_COMPONENT_ENV_VAR` and before any task is submitted. Component rows
stored before 017 have no `container` key and count as containerless.
Deployment- and environment-scope env vars are never rejected for this; they
skip containerless components at render time.

`updateDeployment` never switches driver versions, so the pinned version is
the target. `styrminctl apply` calls `updateDeployment` before
`updateDeploymentVersion` (ADR-048), so a manifest that switches version and
adds component env vars in one go is validated against the pre-switch
version — a known gap recorded in ADR-055.

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
size limit (the deployment CRD context-embedding mechanism, ADR-004, carries
the resolved env vars alongside the rest of the resolved context).

Names must match `^[A-Za-z_][A-Za-z0-9_]*$`. Empty values (`""`) are
accepted. Duplicate names within a single scope are rejected before the dict
is built.

## Upgrade orphans and non-applicable blocks

If a driver upgrade renames or removes a component carrying per-component env
vars, the upgrade succeeds. The orphaned block becomes visible via
`ComponentEnvVars.isOrphaned = true` and is **not** injected into any pod.
Users audit and remove orphans through the same `updateDeployment`
mutation. Rolling the driver back to a version that re-introduces the
component name turns the block live again.

A driver upgrade that keeps the component but drops its component container
is handled the same way: the stored block is kept and read back with
`isOrphaned: false`, `isApplicable: false`. `isApplicable` is computed in the
`componentEnvVars` resolver as `not isOrphaned and container != null`, reading
the container from the deployment's `Component` rows (which mirror the pinned
driver version). It is not persisted and not part of the instance context.

| State | `isOrphaned` | `isApplicable` | Injected |
|-------|--------------|----------------|----------|
| Component declared, with container | false | true | yes (when non-empty) |
| Component declared, no container | false | false | no |
| Component no longer declared | true | false | no |

## Injection by post-render (017+)

Env vars reach pods through a **post-render Kustomize patch**, not through
the driver's values template. Each driver component may declare a component
container (`components.<name>.container`, a DNS-1123 label validated at
driver registration). For every component with a container and non-empty,
non-orphaned resolved env vars, `build_env_var_patches()` emits one
strategic-merge `ContainerEnvPatch` per kind (`Deployment`, `StatefulSet`),
targeted by the component's first identifier label. The HelmRelease builder
appends them after every other post-render patch.

Each patch names the container and lists `{name, value, valueFrom: null}`
per env var in resolution order. The merge keeps chart entries the patch does
not name, replaces same-name entries (including `valueFrom`), and leaves other
containers, init containers, and `Job`/`CronJob`/`DaemonSet` workloads alone.
User entries land before the chart's remaining entries and the component
container moves to `containers[0]` (research D-002; observed kyaml behaviour,
not a contract). Patches are rebuilt on every render, so clearing an env var
needs no marker. One info log per component with patches records `component`,
`container`, and the env var count, never values.

The resolved dicts stay in the rendering context as **read-only data**:

- `instance.config.env_vars` — the deployment-effective merged dict
  (`dict[str, str]`), env→dep merged.
- `components[<name>].env_vars.config` — the per-component merged dict
  (`dict[str, str]`), env→dep→comp merged.

The `component_env_vars` template filter is retired: it raises
`RetiredTemplateFilterError` (`RETIRED_TEMPLATE_FILTER`, metadata `filter`
and `migration_guide`), which aborts rendering before a HelmRelease is
built. The operator records `Failed to create HelmRelease: <message>` on the
deployment; the typed code and metadata do not survive the CR → operator hop,
the message and the migration guide URL do.

Two apply-path changes make clearing work on deployments created before
017: the operator's HelmRelease update replaces `spec` (JSON Patch
`add /spec`, `None` pruned, per-key metadata ops), and the agent's
StyrminDeployment CR applies replace each top-level spec key they write
(`spec.context` wholesale; `spec.deletionRequested` untouched). Without them,
merge-patch kept stale values-template env entries and cleared context keys.

History: 008 injected by a JSON-patch `replace` on `containers/0/env`, which
clobbered chart defaults; 010 moved injection into driver templates
([ADR-013](../../adr/0013-driver-env-var-consumption.md)), where Helm's list
replacement dropped chart defaults instead; 017 merges by name into the
declared container ([ADR-055](../../adr/0055-post-render-component-overrides.md)).
The [driver-author guide](../../guides/driver-env-var-consumption.md) covers
declaring the container and the failure modes.

## ⚠️ No secrets

The platform stores env var values in plaintext and exposes them through any
GraphQL query that selects them. **Do not store credentials, API keys, tokens,
or other secret material in env vars.** A typed secret env var variant
(`valueFrom.secretKeyRef`-style) is a separate ticket and is not yet shipped.

The `EnvVar` GraphQL type description carries this warning at the API
boundary; type-aware UI surfaces should propagate it.

Names matching the `PATH | LD_* | PYTHONPATH | RUBYLIB | NODE_PATH |
JAVA_TOOL_OPTIONS` family emit a structured `logger.warning` at the validator;
they are accepted but flagged because users have shot themselves in the
foot setting them in the past.

## Implementation pointers

| Concern | Location |
|---------|----------|
| Pydantic config models | `backend/styrmin_backend/context/models/config.py` (`EnvironmentConfig.env_vars`, `DeploymentConfig.env_vars`) |
| Validator | `backend/styrmin_backend/services/env_vars/validator.py` |
| Resolver (merge + orphan detection) | `backend/styrmin_backend/services/env_vars/resolver.py` |
| Component container field + validation | `backend/styrmin_backend/services/driver/models/resources/driver.py::ArbitrarySectionModel`, `backend/styrmin_backend/context/models/components.py::ArbitrarySectionModel` |
| Patch builder | `backend/styrmin_backend/services/env_vars/patch_builder.py::build_env_var_patches` |
| Patch block | `backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py::ContainerEnvPatch` |
| Patch placement + rendering-context exposure | `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py` (`ApplicationHelmReleaseBuilder.build`, `render_value_template`, retired `component_env_vars` stub) |
| Write guard | `backend/styrmin_backend/services/deployment.py::_validate_component_env_var_containers`; error in `services/env_vars/exceptions.py` |
| Retired-filter error | `backend/styrmin_backend/services/exceptions.py::RetiredTemplateFilterError` |
| HelmRelease / CR apply | `backend/styrmin_backend/agent/service/kubernetes/primitives.py::upsert_custom_resource` (`replace_spec_on_update`, `replace_spec_keys_on_update`); callers in `operator/pipeline.py` and `agent/tasks/orchestration.py` |
| Driver-side docs | `backend/styrmin_backend/services/driver/models/resources/env_vars.py` |
| Reference driver | `driver/examples/simple-app/driver.styrmin.yml` and `driver/examples/simple-app/src/helm/templates/deployment.yaml` |
| GraphQL types | `backend/styrmin_backend/api/definitions/deployment/model.py`, `.../environment/model.py`, `.../application_driver/model.py`, `.../deployment_timeline/model.py` |
| Frontend gating | `frontend/src/components/deployment/configuration/sections/edit/ComponentOverridesSection.tsx`, `frontend/src/pages/drivers/driver-detail/tabs/ComponentsTab.tsx` |
| Unit tests | `backend/tests/unit/agent/test_container_env_patch.py`, `.../test_application_builder_env_vars.py`, `.../test_upsert_custom_resource_replace_spec.py`, `backend/tests/unit/services/env_vars/test_patch_builder.py` |
| E2E coverage | `backend/tests/e2e/test_deployment_env_vars.py`, `backend/tests/e2e/test_infrahub_services.py` (chart env defaults kept) |
| Propagation + mutation-error tests | `backend/tests/functional/graphql/test_env_vars_propagation.py`, `.../test_update_deployment_input_errors.py`, `.../test_application_driver_version_propagation.py` |

## Related

- [ADR-055: Post-Render Component Overrides](../../adr/0055-post-render-component-overrides.md) — component container, strategic-merge injection, ordering, HelmRelease `spec` replace.
- [ADR-013: Driver-Side Env Var Consumption](../../adr/0013-driver-env-var-consumption.md) — free-form `dict[str, str]`, three-scope deepest-wins; its values-template injection route is superseded by ADR-055.
- [Driver-author guide](../../guides/driver-env-var-consumption.md) — declaring the component container, ordering rules, failure modes.
- [Migration guide](../../../docs/docs/drivers/migrating-env-vars.md) — user and driver-author steps off `component_env_vars`.
- [ADR-004: Embed GlobalContext in StyrminDeployment CRD](../../adr/0004-embed-context-in-deployment-crd.md) — the carrier mechanism that flows resolved env vars to the operator/agent.
- [`services.md`](services.md) — surrounding service-layer architecture.
- [`api.md`](api.md) — surrounding GraphQL API surface.
- [`specs/archive/008-deployment-env-vars/`](../../../specs/archive/008-deployment-env-vars/) — full user-facing feature spec, plan, contracts, and quickstart.
- [`specs/archive/010-driver-env-var-consumption/`](../../../specs/archive/010-driver-env-var-consumption/) — the 010 driver-side consumption spec, plan, and research.
- [`specs/017-post-render-env-vars/`](../../../specs/017-post-render-env-vars/) — post-render injection spec, research, and contracts.
