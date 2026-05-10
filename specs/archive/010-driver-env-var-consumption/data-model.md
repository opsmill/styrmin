# Data Model: Driver-Side Env Var Consumption

This is a deletion-heavy feature. The data model section enumerates what disappears (cleanly), what stays (untouched), and the new template-context surface (which is just documentation of an already-existing path).

## 1. Removed entities

### 1.1 Backend Pydantic / dataclass types

| Entity | File | Disposition |
|---|---|---|
| `EnvVarsPatch` | `agent/.../blocks/patches.py` | DELETE class |
| `ChartEnvCollision` | `services/env_vars/patch_builder.py` | DELETE dataclass |
| `PostRenderInjection.env_vars` field | `context/models/config.py` | DELETE field; `PostRenderInjection` model retains its other inject flags unchanged |
| `TimelineEntry.env_var_collisions` field | `services/deployment_timeline.py` | DELETE field; `TimelineEntry` retains everything else |
| `EnvVarsResolver` (if exists, post-008) | `services/env_vars/resolver.py` | KEEP if it's a class with one staticmethod the resolver pipeline uses; this feature does not refactor the resolver layer |

### 1.2 Backend Python functions / methods

| Function | File | Disposition |
|---|---|---|
| `build_env_vars_post_rendering_patches` | `services/env_vars/patch_builder.py` | DELETE |
| `ApplicationBuilder.build_env_vars_post_rendering_patches` | `agent/.../builders/application.py` | DELETE method |
| The `target_patches.extend(self.build_env_vars_post_rendering_patches())` call inside `ApplicationBuilder.build()` | `agent/.../builders/application.py` | DELETE invocation |
| `effective_inject_flag(..., "env_vars")` callers + the `"env_vars"` entry in `_INJECT_FIELDS` | `context/resolvers.py` | DELETE the "env_vars" entry from `_INJECT_FIELDS`; the function itself stays for other inject flags |

### 1.3 GraphQL surface

| Schema element | Disposition |
|---|---|
| `EnvVarCollision` Strawberry type | DELETE |
| `DeploymentTimelineEntry.envVarCollisions: [EnvVarCollision!]!` field | DELETE |
| `PostRenderInjectionInput.envVars: Boolean` (Strawberry input field) | DELETE |
| `Deployment.envVars`, `Deployment.componentEnvVars`, `Environment.envVars`, `ApplicationDriverVersion.envVars` | KEEP — operator-facing query surface stays |
| `ComponentEnvVars.isOrphaned` | KEEP |

### 1.4 Test files

| Test | Disposition |
|---|---|
| `backend/tests/unit/services/env_vars/test_patch_builder.py` | DELETE entire file |
| `backend/tests/unit/agent/test_application_builder_env_vars.py` (env-vars-injection assertions only) | MODIFY — delete the injection assertions; keep non-injection assertions (or delete the whole file if it had no other content) |
| `backend/tests/functional/graphql/test_env_vars_propagation.py` (rows for `DeploymentTimelineEntry.envVarCollisions` and `PostRenderInjection.envVars`) | MODIFY — delete those propagation rows; keep all other rows |

### 1.5 SDK + frontend

| Surface | Disposition |
|---|---|
| `python_sdk/src/styrmin_sdk/graphql/_generated/*` | AUTO-REGEN via `uv run invoke generate` after schema deletion |
| `frontend/src/generated/graphql.ts` | AUTO-REGEN |
| Any hand-written SDK / frontend code referencing the removed types | The codegen failure surfaces these; update each call site to remove the references |

## 2. Preserved entities (untouched)

The following stay exactly as 008+009 left them:

### 2.1 Configuration model

```python
# context/models/config.py — UNCHANGED in 010
class EnvironmentConfig(BaseConfigSection):
    env_vars: dict[str, str] | None = None  # field validator runs validate_env_vars_dict
    # ... other fields ...

class DeploymentConfig(ClusterConfig, EnvironmentConfig):
    env_vars: dict[str, str] | None = None  # same
    # ... other fields ...

# components.py — UNCHANGED
class ResolvedComponentEnvVars(BaseModel):
    config: dict[str, str]
    provenance: dict[str, ProvenanceLevel] = Field(default_factory=dict)
    is_orphaned: bool = False

class ComponentContext(BaseModel):
    env_vars: ResolvedComponentEnvVars | None = None
    # ... other fields ...
```

### 2.2 Validation pipeline

`backend/styrmin_backend/services/env_vars/validator.py` — every function stays. Name regex, size caps, duplicate detection, risky-name soft warning. The validators don't care that the consumption mechanism changed; they validate operator inputs at the API boundary.

### 2.3 Resolution pipeline

`_merge_env_vars` (env→dep→comp deepest-wins), `EnvVarsResolver.resolve_for_deployment`, `_extract_environment_slice_from_context`, `_deployment_already_at_config` (009's per-deployment no-op detection), `_populate_component_env_vars` (or its renamed equivalent inside `services/context.py`) — all stay. The resolved env vars now flow into the rendering context (which already worked) instead of into `build_env_vars_post_rendering_patches` (which is deleted).

### 2.4 GraphQL read surface

```graphql
extend type Environment { envVars: [EnvVar!]! }                        # KEEP
extend type Deployment {                                                # KEEP
  envVars: [EnvVar!]!
  componentEnvVars: [ComponentEnvVars!]!
}
extend type ApplicationDriverVersion { envVars: [DriverEnvVarDoc!]! }  # KEEP
type EnvVar { name: String!, value: String! }                           # KEEP
type ComponentEnvVars { component: String!, envVars: [EnvVar!]!, isOrphaned: Boolean! }  # KEEP
type DriverEnvVarDoc { name, description, level, components }          # KEEP
```

### 2.5 Mutation surface

`Mutation.updateEnvironment(environmentId, input: UpdateEnvironmentInput!)` from 009 stays. The `UpdateEnvironmentInput.envVars: [EnvVarInput!]` field stays. The `PostRenderInjectionInput.envVars: Boolean` field is removed (the only nested-input change in this feature).

### 2.6 Frontend

The 009 Configuration tab + env-vars edit form work unchanged. `EnvironmentConfigurationTab.tsx`, `EnvVarsForm.tsx`, `RedeployConfirmDialog.tsx` are untouched. The form's `buildFullReplacementInput` continues to map env vars from the JSON config dict; nested-clearing block from 009's review pass continues to apply.

## 3. New entities (none, structurally — only documentation)

### 3.1 Documented template-context surface (FR-001 + FR-002)

The driver template's Jinja context exposes:

```text
instance.config.env_vars: dict[str, str] | absent
    Deployment-effective env vars (env→dep merge applied).
    Absent when no env vars are set at any scope; non-empty dict otherwise.
    Driver authors handle absence with `instance.config.env_vars or {}`.

components[<name>].env_vars.config: dict[str, str] | absent
    Per-component effective env vars (env→dep→comp merge applied).
    Absent when the component has no env vars set anywhere; non-empty dict otherwise.
    Driver authors handle absence with `(components[name].env_vars.config if components[name].env_vars else {})`.
```

This isn't a NEW field — both already exist on `GlobalContext` post-008. This feature documents them as the canonical consumption surface. The model_dump-based exposure path (`render_value_template` → `context.model_dump(exclude_none=True)` → Jinja) is unchanged.

### 3.2 New documentation files

| File | Purpose |
|---|---|
| `dev/guides/driver-env-var-consumption.md` | Driver-author guide (FR-021/FR-022) |
| `dev/adr/adr-021-driver-env-var-consumption.md` | Durable record of the pivot |

`dev/knowledge/backend/deployment-env-vars.md` (created in 008's polish phase) gets a paragraph rewrite — the "post-render injection" section becomes a "driver-side consumption" section.

## 4. State transitions

### 4.1 Operator sets env var → pod has it (the load-bearing flow)

```text
T0: operator submits updateDeployment(config: { env_vars: { LOG_LEVEL: "debug" } })
T1: validation runs (typed errors at GraphQL boundary unchanged)
T2: env-config row persists; per-deployment redeploy fanout dispatches a Task per affected deployment (009)
T3: each Task generates a new ApplicationInstance whose context resolves env vars
    via _merge_env_vars and populates instance.config.env_vars + components[*].env_vars.config
T4: ApplicationBuilder.build() renders values via render_value_template,
    feeding instance.config.env_vars into the simple-app values.j2.yml's `env:` block
T5: rendered HelmRelease applied to the cluster
T6: kubelet runs pods with the env entry on container[0] (and any other containers
    the chart's env-list field populates)
```

The path differs from 008+009 only at T4: previously, the values template was rendered *without* env vars and a separate `EnvVarsPatch` post-render-patched them in (clobbering chart env). Now the values template renders WITH env vars and the chart's own templating handles the rest.

### 4.2 Driver author writes a values template that consumes env vars

```text
T0: driver author reads dev/guides/driver-env-var-consumption.md
T1: in values.j2.yml, the author adds an `env:` block consuming `instance.config.env_vars`
T2: chart's container template references `.Values.env` (or whatever the chart already supports)
T3: driver registers; the loader validates the values template parses (008's existing check)
T4: when an operator deploys this driver and sets env vars, T3-T6 from §4.1 run
```

### 4.3 Driver author writes a values template that does NOT consume env vars

```text
T0: a driver template predating this feature renders values without referencing env vars
T1: an operator sets envVars on a deployment using this driver
T2: env-config row persists; redeploy fanout runs (009 path); ApplicationInstance regenerates
T3: render_value_template runs but the template ignores env_vars in the context
T4: rendered chart values contain no env entries from operator-set env vars
T5: pods run with whatever env entries the chart sets by itself (no operator-set entries)
T6: operator queries Deployment.envVars and sees their input — but the pods don't reflect it.
    This is the spec-defined opt-out behaviour: drivers consume operator-set env vars
    only when their templates do so explicitly. (Migration responsibility on the driver author.)
```

## 5. Errors

No new error types. The validation pipeline preserved from 008+009 produces:

| Error | Code | When |
|---|---|---|
| `InvalidEnvVarNameError` | `INVALID_ENV_VAR_NAME` | name regex fails |
| `EnvVarSizeLimitExceededError` | `ENV_VAR_SIZE_LIMIT_EXCEEDED` | per-value or per-scope cap exceeded |
| `DuplicateEnvVarNameError` | `DUPLICATE_ENV_VAR_NAME` | duplicate name in input list |
| `UnknownComponentEnvVarError` | `UNKNOWN_COMPONENT_ENV_VAR` | mutation references unknown component |

All four codes survive the GraphQL boundary intact (008 / H1 fix from review; 009 preserves it).

## 6. Storage

No schema changes. No migrations. Existing `Environment.config` / `ApplicationInstance.context` JSON columns carry the same shape. The `ApplicationDriverVersion.env_vars` JSON column added in 008/US4 stays — driver authors continue to declare doc-only env vars with `spec.env_vars`, and the loader continues to validate.
