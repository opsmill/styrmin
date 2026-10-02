# Data Model: Platform-Owned Env Var Injection via Post-Render

**Feature**: 017-post-render-env-vars | **Spec**: [spec.md](spec.md) | **Research**: [research.md](research.md)

No database schema change and no Alembic revision: the component container rides inside JSON
columns that already store the component definition (research D-004).

## 1. Component container (driver specification)

**Where**: `spec.components.<name>.container` in `driver.styrmin.yml`.

| Field | Type | Required | Validation |
|---|---|---|---|
| `container` | string | no | Kubernetes container name: `^[a-z0-9]([-a-z0-9]*[a-z0-9])?$`, length 1–63. Malformed → driver registration fails (FR-001). |

**Models touched** (typed field added; both already `extra="allow"`):

- `services/driver/models/resources/driver.py::ArbitrarySectionModel` — load-time validation.
- `context/models/components.py::ArbitrarySectionModel` — `ComponentContext.config.container`,
  read by the env var patch builder.

**Storage path** (unchanged mechanics):

```text
driver.styrmin.yml components.<name>
  → ApplicationDriverVersion.components (JSON)            # driver-version snapshot
  → ComponentConfig.config (JSON, one row per component)  # driver-version read path
  → Component.config (JSON, per deployment)               # copied on deploy + driver switch
  → ContextInput.components → ComponentContext.config     # rendering context
```

**State transitions**: a driver-version switch recreates the deployment's `Component` rows from
the target version's `ComponentConfig` rows (`services/deployment.py`), so the deployment's
component container always reflects its pinned driver version.

## 2. Resolved env vars (unchanged)

`ResolvedComponentEnvVars {config: dict[str, str], provenance, is_orphaned}` and the resolver
(`services/env_vars/resolver.py`) are unchanged. Precedence stays per-key deepest-wins:
environment → deployment → component. `instance.config.env_vars` and
`components[<name>].env_vars.config` stay in the rendering context as read-only data (FR-009).

## 3. Applicability (derived, read-only)

A component's env vars are **applicable** iff:

```text
applicable(component) = not is_orphaned(component) and component_container(component) is not None
```

| State | `isOrphaned` | `isApplicable` | Injected? |
|---|---|---|---|
| Declared component with container | false | true | yes (when non-empty) |
| Declared component without container | false | false | no — deployment/env scope skipped silently (FR-004); component-scope writes rejected (FR-003) |
| Stored block on a component the driver no longer declares | true | false | no (existing orphan rule) |
| Stored block on a component whose container was removed by a driver upgrade | false | false | no — kept and flagged (FR-005) |

Computed in the GraphQL resolver from the deployment's pinned driver-version component configs;
not persisted, not added to the instance context.

## 4. Env var post-render patch (`ContainerEnvPatch`)

One strategic-merge patch per (applicable component with non-empty resolved env vars) × kind in
`{Deployment, StatefulSet}`; see [contracts/post-render-patch.md](contracts/post-render-patch.md).

| Attribute | Value |
|---|---|
| `target.kind` | `Deployment` or `StatefulSet` |
| `target.labelSelector` | component identifier label (`identifier.label.label_selectable()`) |
| `containers[0].name` | component container |
| `env[i]` | `{name: k, value: v, valueFrom: null}` for `(k, v)` in resolved `config`, in dict order |
| Position in `postRenderers[0].kustomize.patches` | after every existing patch (research D-002) |

**Lifecycle**: regenerated from the resolved context on every render; absence of an env var
means absence of its entry, so clearing converges without markers (FR-010).

## 5. Errors

| Error | `extensions.code` | Raised | Metadata |
|---|---|---|---|
| `ComponentContainerNotDeclaredError` | `COMPONENT_CONTAINER_NOT_DECLARED` | write path, before task submission (FR-003) | `component_name`, `components_with_container` |
| `RetiredTemplateFilterError` | `RETIRED_TEMPLATE_FILTER` | values-template render, when `component_env_vars` is called (FR-007) | `filter`, `migration_guide` |
| Container-name validation failure | driver-load validation error (existing path) | driver registration (FR-001) | offending component + value |

`ComponentContainerNotDeclaredError` fires only when the submitted component block adds a key or
changes a value relative to the stored one, judged against the driver version the deployment is
pinned to after the write (research D-007). Removals and unchanged re-submissions pass.
Unknown-component blocks keep raising `UNKNOWN_COMPONENT_ENV_VAR` first.

## 6. HelmRelease apply (operator)

| Path | Before | After (FR-011) |
|---|---|---|
| Create (`POST`) | body with `None` pruned | unchanged |
| Update, `spec` | JSON merge-patch (maps merge, omitted keys survive) | JSON Patch `add /spec` with `None` pruned — wholesale replace |
| Update, `metadata.labels` / `metadata.annotations` | merge-patch | per-key `add` ops (merge semantics preserved; Flux finalizer untouched) |

Opt-in flag on `upsert_custom_resource`, set only by the HelmRelease apply in
`operator/pipeline.py` (research D-003).
