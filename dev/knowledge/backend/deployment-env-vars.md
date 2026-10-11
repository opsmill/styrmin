# Deployment Env Vars

A free-form `dict[str, str]` of environment variables that users can set
on a deployment without a driver change. The platform resolves the merged
dict and merges it, after the chart renders, into the **component
container** each driver component declares, by env var `name`.

This page is the user/contributor reference. The decisions behind the shape
(free-form `dict[str, str]`, three-scope deepest-wins precedence) live in
[ADR-013](../../adr/0013-driver-env-var-consumption.md); post-render
injection into the component container lives in
[ADR-057](../../adr/0057-post-render-component-overrides.md). The full
contracts are in [`specs/archive/008-deployment-env-vars/`](../../../specs/archive/008-deployment-env-vars/),
[`specs/archive/010-driver-env-var-consumption/`](../../../specs/archive/010-driver-env-var-consumption/),
and [`specs/archive/017-post-render-env-vars/`](../../../specs/archive/017-post-render-env-vars/).

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
`ComponentEnvVars.isApplicable` ([`contracts/graphql-deltas.md`](../../../specs/archive/017-post-render-env-vars/contracts/graphql-deltas.md)).

### Component-scope writes need a component container

`updateDeployment` and `deploy` raise `COMPONENT_CONTAINER_NOT_DECLARED`
(`ComponentContainerNotDeclaredError`, metadata `component_name`,
`components_with_container`, and `override`: `"env_vars"` here, `"image"` for
image overrides) when a component-scope block **adds a key or
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
version — a known gap recorded in ADR-057.

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
non-orphaned resolved env vars, `build_component_container_patches()` emits,
per kind (`Deployment`, `StatefulSet`), a strategic-merge `ContainerEnvPatch`
followed by the JSON6902 `ComponentContainerPatch` guard (018), both targeted
by the component's first identifier label. The guard fails the render when
the named container is missing instead of letting the merge add it. The
HelmRelease builder appends them after every other post-render patch.

Each patch names the container and lists `{name, value, valueFrom: null}`
per env var in resolution order. The merge keeps chart entries the patch does
not name, replaces same-name entries (including `valueFrom`), and leaves other
containers, init containers, and `Job`/`CronJob`/`DaemonSet` workloads alone.
User entries land before the chart's remaining entries and the component
container moves to `containers[0]` (research D-002; observed kyaml behaviour,
not a contract). Patches are rebuilt on every render, so clearing an env var
needs no marker. One info log per component with patches records `component`,
`container`, the env var count, and whether an image override applies, never
values.

### The shared component-container guard (018)

`build_component_container_patches()` (`services/component_container/patch_builder.py`)
serves env vars and image overrides alike: a component with a component container gets
patches when it has applicable env vars, a live image override, or both. Per kind, the
strategic merge names the container (with env entries only when env vars apply), and the
JSON6902 `ComponentContainerPatch` then:

1. moves `containers/0` to the temporary key
   `/spec/template/spec/styrmin.io~1component-container~1<component>~1<container>`
   (names JSON-pointer escaped);
2. removes its `image` and adds the substituted image override, or, for env vars only,
   copies the chart image to `styrmin-image`, removes `image`, and moves it back;
3. moves the container back to `containers/0`.

kyaml's merge adds a container when the name is missing. Before 018 that container had no
image and the API server rejected the workload; with an image override it would be valid.
The `remove` fails on the added, image-less container, so a wrong name fails the Helm
post-render with `error in remove for path: '…/styrmin.io~1component-container~1<component>~1<container>/image'`
and no container is ever added. For env vars only, the rendered workload is byte-identical
to the merge alone, so the extra patch restarts no pods.

The operator turns that failure into a typed status. On every timer tick in
`CreatingHelmRelease` (before the readiness check) and, for non-internal deployments,
`Ready` (before drift detection),
`read_helmrelease_guard_failure()` (`operator/reconciler.py`) reads the HelmRelease and
matches when `Ready` is not `True` and a condition observed for the current
`metadata.generation` carries the guard key in its message (`parse_guard_failure()` in
`services/component_container/exceptions.py`). helm-controller v1.1.0 reported it under
`Ready=False` and `Released=False`, reason `UpgradeFailed`. helm-controller v1.6.5, which the
agent chart installs, reports it in an `UpgradeFailed` Event and then reports the previous
release `Ready`; the operator then reads the guard key from that Event (see
[A failed change reported in sync](../agent/operator.md#a-failed-change-reported-in-sync)). The CR then goes
`Failed` / `Error` with `HelmReleaseReady=False` and `Ready=False`, reason
`ComponentContainerNotFound`, and
the `ComponentContainerNotFoundError` (`COMPONENT_CONTAINER_NOT_FOUND`) message, which the
status reporter copies to `Deployment.crdStatus.message`:

```text
Component 'server': component container 'wrong-name' was not found in its rendered workload.
Styrmin never adds a container; fix components.server.container in the driver specification file.
```

It shows up within one or two timer intervals (`STYRMIN_OPERATOR_RECONCILE_INTERVAL`, 60 s
by default) after helm-controller reports. Other HelmRelease failures keep the readiness
timeout path. See [ADR-058](../../adr/0058-image-overrides-and-component-container-guard.md).

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
017: both the operator's HelmRelease update and the agent's StyrminDeployment
CR applies replace each top-level spec key they write (JSON Patch
`add /spec/<key>`, nested `None` pruned, a top-level `None` key removed,
per-key metadata ops). `spec.values` and `spec.context` are replaced
wholesale; keys Styrmin never writes (`spec.suspend`,
`spec.deletionRequested`) are untouched. Without them, merge-patch kept stale
values-template env entries and cleared context keys.

History: 008 injected by a JSON-patch `replace` on `containers/0/env`, which
clobbered chart defaults; 010 moved injection into driver templates
([ADR-013](../../adr/0013-driver-env-var-consumption.md)), where Helm's list
replacement dropped chart defaults instead; 017 merges by name into the
declared container ([ADR-057](../../adr/0057-post-render-component-overrides.md));
018 adds the guard shared with image overrides
([ADR-058](../../adr/0058-image-overrides-and-component-container-guard.md)).
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
| Patch builder | `backend/styrmin_backend/services/component_container/patch_builder.py::build_component_container_patches` |
| Patch blocks | `backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py::ContainerEnvPatch`, `::ComponentContainerPatch` |
| Patch placement + rendering-context exposure | `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py` (`ApplicationHelmReleaseBuilder.build`, `render_value_template`, retired `component_env_vars` stub) |
| Write guard | `backend/styrmin_backend/services/deployment.py::_validate_component_container_targets` (env vars and image overrides); error in `services/env_vars/exceptions.py` |
| Retired-filter error | `backend/styrmin_backend/services/exceptions.py::RetiredTemplateFilterError` |
| Guard failure parser + error | `backend/styrmin_backend/services/component_container/exceptions.py` (`parse_guard_failure`, `ComponentContainerNotFoundError`) |
| Guard failure surfacing | `backend/styrmin_backend/operator/reconciler.py::read_helmrelease_guard_failure`, `operator/handlers/styrmin_deployment.py::_fail_on_component_container_guard` |
| HelmRelease / CR apply | `backend/styrmin_backend/agent/service/kubernetes/primitives.py::upsert_custom_resource` (`replace_spec_keys_on_update`); callers in `operator/pipeline.py` and `agent/tasks/orchestration.py` |
| Driver-side docs | `backend/styrmin_backend/services/driver/models/resources/env_vars.py` |
| Reference driver | `driver/examples/simple-app/driver.styrmin.yml` and `driver/examples/simple-app/src/helm/templates/deployment.yaml` |
| GraphQL types | `backend/styrmin_backend/api/definitions/deployment/model.py`, `.../environment/model.py`, `.../application_driver/model.py`, `.../deployment_timeline/model.py` |
| Frontend gating | `frontend/src/components/deployment/configuration/sections/edit/ComponentOverridesSection.tsx`, `frontend/src/pages/drivers/driver-detail/tabs/ComponentsTab.tsx` |
| Unit tests | `backend/tests/unit/agent/test_container_env_patch.py`, `.../test_component_container_patch.py`, `.../test_application_builder_env_vars.py`, `.../test_upsert_custom_resource_replace_spec.py`, `backend/tests/unit/services/component_container/test_patch_builder.py`, `.../component_container/test_exceptions.py`, `backend/tests/unit/test_styrmin_deployment_timer.py` (guard failure surfacing) |
| Kustomize integration test | `backend/tests/integration/test_component_container_kustomize.py` |
| E2E coverage | `backend/tests/e2e/test_deployment_env_vars.py`, `backend/tests/e2e/test_infrahub_services.py` (chart env defaults kept), `backend/tests/e2e/test_deployment_image_override.py::test_misnamed_container_never_added` (guard failure) |
| Propagation + mutation-error tests | `backend/tests/functional/graphql/test_env_vars_propagation.py`, `.../test_update_deployment_input_errors.py`, `.../test_application_driver_version_propagation.py` |

## Related

- [ADR-057: Post-Render Component Overrides](../../adr/0057-post-render-component-overrides.md) — component container, strategic-merge injection, ordering, HelmRelease `spec` replace.
- [ADR-058: Image Overrides and the Component-Container Guard](../../adr/0058-image-overrides-and-component-container-guard.md) — the JSON6902 guard shared with image overrides and its operator surfacing.
- [ADR-013: Driver-Side Env Var Consumption](../../adr/0013-driver-env-var-consumption.md) — free-form `dict[str, str]`, three-scope deepest-wins; its values-template injection route is superseded by ADR-057.
- [Driver-author guide](../../guides/driver-env-var-consumption.md) — declaring the component container, ordering rules, failure modes.
- [Migration guide](../../../docs/docs/drivers/migrating-env-vars.md) — user and driver-author steps off `component_env_vars`.
- [ADR-004: Embed GlobalContext in StyrminDeployment CRD](../../adr/0004-embed-context-in-deployment-crd.md) — the carrier mechanism that flows resolved env vars to the operator/agent.
- [`services.md`](services.md) — surrounding service-layer architecture.
- [`api.md`](api.md) — surrounding GraphQL API surface.
- [`specs/archive/008-deployment-env-vars/`](../../../specs/archive/008-deployment-env-vars/) — full user-facing feature spec, plan, contracts, and quickstart.
- [`specs/archive/010-driver-env-var-consumption/`](../../../specs/archive/010-driver-env-var-consumption/) — the 010 driver-side consumption spec, plan, and research.
- [`specs/archive/017-post-render-env-vars/`](../../../specs/archive/017-post-render-env-vars/) — post-render injection spec, research, and contracts.
