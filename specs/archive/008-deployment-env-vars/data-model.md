# Data Model: Deployment Env Vars

## 1. Pydantic configuration models

### 1.1 `EnvVarsConfig` field — added to existing config sections

A `dict[str, str] | None` field named `env_vars` is added to:

- `EnvironmentConfig` (`backend/styrmin_backend/context/models/config.py`)
- `DeploymentConfig` (inherits from `ClusterConfig` + `EnvironmentConfig`; gains the field)
- **Per-component slot**: the field lives on the **deployment-side context model** at `backend/styrmin_backend/context/models/components.py` — specifically, the user-set per-component config block stored under `DeploymentConfig.components[<name>].env_vars`. The data path is the existing component-config JSON sub-block carried by `ApplicationInstance.context`. The driver-side `ArbitrarySectionModel` (in `backend/styrmin_backend/services/driver/models/resources/driver.py`) is **not** touched here: driver-side components carry only the doc-only `DriverEnvVarDoc` declarations on `Specification.env_vars` (see §3 below). User-set values never live on the driver model.

```python
# context/models/config.py (additions, condensed)
class EnvironmentConfig(BaseConfigSection):
    ip_whitelist: list[str] | None = None
    dedicated_ingress: DedicatedIngressConfig | None = None
    env_vars: dict[str, str] | None = None  # ← NEW
```

#### Validation rules (enforced by Pydantic field validators on the dict)

| Rule | Carrier | Error |
|---|---|---|
| Name regex `^[A-Za-z_][A-Za-z0-9_]*$` | per-key validator on the dict | `InvalidEnvVarNameError(name=...)` |
| Per-value cap 64 KiB (UTF-8 bytes) | per-value validator | `EnvVarSizeLimitExceededError(name=..., bytes=..., cap=65536)` |
| Per-scope dict ≤ 100 entries | dict-level validator | `EnvVarSizeLimitExceededError(scope=..., entries=..., cap=100)` |
| Per-scope dict serialised ≤ 256 KiB | dict-level validator | `EnvVarSizeLimitExceededError(scope=..., bytes=..., cap=262144)` |
| Empty-string values | accepted | — |
| Duplicate-name in input list before dict construction | input-shape validator | `DuplicateEnvVarNameError(name=..., scope=...)` |
| Resolved per-component dict ≤ 256 KiB; total resolved bytes per deployment ≤ 1 MiB | resolver post-merge check (FR-008a) | `EnvVarSizeLimitExceededError(scope="resolved", component=..., bytes=...)` |
| Soft-warn (no rejection) on names matching the risky family `^(PATH|LD_.*|PYTHONPATH|RUBYLIB|NODE_PATH|JAVA_TOOL_OPTIONS)$` | per-key validator | `logger.warning("env_var_potentially_risky_name", name=..., scope=...)` |

### 1.2 `PostRenderInjection.env_vars` flag

```python
class PostRenderInjection(BaseModel):
    pod_affinity: bool | None = None
    node_affinity: bool | None = None
    topology_spread: bool | None = None
    resources: bool | None = None
    tolerations: bool | None = None
    runtime_class: bool | None = None
    env_vars: bool | None = None  # ← NEW; default behaviour True
```

Three-valued: `None` inherits from the next shallower level (or defaults to `True` at the top); `False` opts the component out; `True` is the default behaviour. Resolved through the existing `_merge_inject_flags` machinery.

## 2. Resolved per-component model

### 2.1 `ResolvedComponentEnvVars`

```python
# context/models/components.py (addition)
class ResolvedComponentEnvVars(BaseModel):
    """Per-component effective env vars plus provenance.

    Mirrors :class:`ResolvedComponentScheduling`.
    """

    model_config = ConfigDict(extra="forbid")

    config: dict[str, str]
    provenance: dict[str, ProvenanceLevel] = Field(default_factory=dict)
    is_orphaned: bool = False
```

`ComponentContext` gains `env_vars: ResolvedComponentEnvVars | None = None` (mirroring its existing `scheduling: ResolvedComponentScheduling | None`).

### 2.2 Merge semantics — `_merge_env_vars`

Per-key deepest-wins. Pseudo-code:

```python
def _merge_env_vars(
    env: dict[str, str] | None,
    dep: dict[str, str] | None,
    comp: dict[str, str] | None,
) -> tuple[dict[str, str], dict[str, ProvenanceLevel]]:
    config: dict[str, str] = {}
    provenance: dict[str, ProvenanceLevel] = {}
    for src, level in [(env, "environment"), (dep, "deployment"), (comp, "component")]:
        if not src:
            continue
        for k, v in src.items():
            config[k] = v          # later layers overwrite; deepest wins per key
            provenance[k] = level
    return config, provenance
```

When the driver declares no components, the resolver still computes a single "broad" effective dict from `_merge_env_vars(env, dep, None)` and the patch builder applies it without a label selector.

### 2.3 Orphan detection

```python
def detect_orphans(
    stored: list[ComponentEnvVarsBlock],
    driver_components: set[str],
) -> list[ResolvedComponentEnvVars]:
    return [
        ResolvedComponentEnvVars(
            config=block.env_vars,
            provenance={k: "component" for k in block.env_vars},
            is_orphaned=block.component not in driver_components,
        )
        for block in stored
    ]
```

Orphaned blocks are exposed via the GraphQL `ComponentEnvVars.isOrphaned` field and skipped during patch generation.

## 3. Driver-side documentation models

```python
# services/driver/models/resources/env_vars.py (NEW)
class DriverEnvVarLevel(str, Enum):
    DEPLOYMENT = "deployment"
    COMPONENT = "component"


class DriverEnvVarDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="POSIX env var name")
    description: str
    level: DriverEnvVarLevel
    components: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not _ENV_VAR_NAME_RE.match(v):
            raise ValueError(
                f"env var name '{v}' must match ^[A-Za-z_][A-Za-z0-9_]*$",
            )
        return v

    @model_validator(mode="after")
    def _validate_components_for_component_level(self) -> Self:
        if self.level is DriverEnvVarLevel.COMPONENT and not self.components:
            raise ValueError(
                "level='component' requires a non-empty `components` list",
            )
        if self.level is DriverEnvVarLevel.DEPLOYMENT and self.components:
            raise ValueError(
                "level='deployment' env var docs MUST NOT name components",
            )
        return self
```

Cross-field validation (every `components` entry exists in the driver's component map) runs in `services/driver/validators.py` because it requires access to the parent `Specification`. The validator is invoked from the driver loader; failure causes registration to abort.

## 4. GraphQL types

### 4.1 Read types

```graphql
type EnvVar {
  name: String!
  value: String!
}

type ComponentEnvVars {
  component: String!
  envVars: [EnvVar!]!
  isOrphaned: Boolean!
}

type DriverEnvVarDoc {
  name: String!
  description: String!
  level: DriverEnvVarLevel!
  components: [String!]!
}

enum DriverEnvVarLevel {
  DEPLOYMENT
  COMPONENT
}
```

### 4.2 Field additions

```graphql
extend type Deployment {
  envVars: [EnvVar!]!                  # effective deployment-level dict
  componentEnvVars: [ComponentEnvVars!]!  # effective per-component dicts (incl. orphans)
}

extend type ApplicationDriverVersion {
  envVars: [DriverEnvVarDoc!]!
}

extend type DeploymentTimelineEntry {
  envVarCollisions: [EnvVarCollision!]!  # per-task chart-vs-user collisions
}

type EnvVarCollision {
  component: String
  container: String!
  name: String!
  chartValue: String!
  userValue: String!
}
```

`Environment.envVars: [EnvVar!]!` is added in parallel for symmetry (FR-020).

### 4.3 Inputs

No new input types. Env vars travel through the existing `config: JSON` argument on `deploy()` / `updateDeployment()` and `update_environment_config()` — see Research §1.

## 5. State transitions

### 5.1 Set / update env var (write-path)

```text
Operator
  → updateDeployment(config: { ..., env_vars: { LOG_LEVEL: "debug" } })
  → mutation handler calls update_deployment service
  → service validates DeploymentConfig (Pydantic field validators run all rules in §1.1)
  → repository persists ApplicationInstance.context (existing JSON column)
  → Prefect reconcile flow runs
  → resolver computes ResolvedConfig + per-component ResolvedComponentEnvVars
  → context-embedding (ADR-006) carries resolved env vars into the deployment CRD
  → agent/ApplicationBuilder reads context, calls build_env_vars_post_rendering_patches
  → FluxCD HelmRelease.spec.postRenderers gains the env-injection patch
  → next reconcile renders pods with env entries
```

> **v1 patch shape:** the env-injection patch is a JSON-patch ``replace`` against ``/spec/template/spec/containers/0/env`` (CronJob: ``/spec/jobTemplate/spec/template/spec/containers/0/env``), matching :class:`ResourcesPatch`. Strategic-merge has no wildcard semantic for container ``name``, so v1 narrows to container[0] — the common single-container case. Multi-container per-pod fan-out (emitting one patch per declared container in the rendered manifest) is tracked as a follow-up iteration; today's component-level label-selector scoping remains the way to narrow by workload kind.

### 5.2 Driver upgrade with component renamed

```text
Operator
  → updateDeploymentVersion(driver_version: "v2")
  → service stores new driver_version on ApplicationInstance
  → reconcile runs
  → resolver detects componentEnvVars["worker"] but driver v2 has no "worker"
  → ResolvedComponentEnvVars(is_orphaned=True) emitted
  → patch builder skips orphaned blocks
  → context_diff (existing machinery) records the orphan transition on the upgrade Task
  → DeploymentTimelineEntry exposes the change once
  → subsequent reconciles: orphan persists, no new timeline entries (no new task per reconcile)
```

### 5.3 Chart-collision warning (v1: deferred per FR-028)

The original design called for the patch builder to walk rendered container env entries at render time, record `ChartEnvCollision` per name overlap, and emit a structured warning log. **This is not implemented in v1**: the backend has no line-of-sight into the post-rendered manifest at the patch layer (the JSON-patch is processed by Kustomize on-cluster). Per FR-028 the conflict-detection path is allowed to degrade fully — no detection runs and no warnings are emitted. The operator-set value still wins (post-render replaces chart entries on `container[0]`).

The forward-compatible flow that lands when a real detection seam is added:

```text
Future (post-apply rendered-manifest fetch + diff path):
  agent fetches rendered manifest after FluxCD apply
  → for every name overlap between chart env and operator-set env vars:
    → record ChartEnvCollision per collision
    → emit logger.warning("env_var_chart_collision", ...) per collision
  → agent attaches collisions to the Task for this reconcile
  → DeploymentTimelineEntry.envVarCollisions surfaces them in API/UI
```

In v1, `DeploymentTimelineEntry.envVarCollisions` always returns `[]`; the `EnvVarCollision` Strawberry type and `ChartEnvCollision` dataclass shape ship for forward-compatibility. See [ADR-019](/dev/adr/adr-019-deployment-env-vars.md) §3.

## 6. Storage

| Field | Storage location |
|---|---|
| `EnvironmentConfig.env_vars` | `Environment.config` JSON column (existing) |
| `DeploymentConfig.env_vars` | `ApplicationInstance.context` JSON column (existing) |
| `DeploymentConfig.component_env_vars` | same JSON column under `components.<name>.env_vars` |
| `ResolvedComponentEnvVars` | not persisted — recomputed per reconcile from stored config |
| `DriverEnvVarDoc` | parsed from driver YAML at load time; persisted as a dedicated `ApplicationDriverVersion.env_vars` JSON column (added by migration `d0e1f2a3b4c5` during US4 implementation — see [ADR-019](/dev/adr/adr-019-deployment-env-vars.md) §2). The original spec assumed a `spec_yaml` column would carry the data; in practice no such column exists, and the dedicated-column shape mirrors the existing `parameters` / `services` / `components` JSON columns on `ApplicationDriverVersion`. |
| `EnvVarCollision` | not persisted as a first-class entity in v1 — derived from per-task agent reports; presented through `DeploymentTimelineEntry.envVarCollisions` |

No new database columns for the **deployment-side** env-var storage (FR-022) — the existing `Environment.config` / `ApplicationInstance.context` JSON columns absorb the new fields automatically. The **driver-side** doc surface added in US4 introduced a single new column on `ApplicationDriverVersion` (see the row above) with a corresponding migration `d0e1f2a3b4c5`; that deviation is documented in [ADR-019](/dev/adr/adr-019-deployment-env-vars.md) §2.

## 7. Errors

| Error | When | HTTP/GraphQL code |
|---|---|---|
| `InvalidEnvVarNameError` | name regex fails (operator input or driver doc) | `INVALID_ENV_VAR_NAME` |
| `DuplicateEnvVarNameError` | duplicate name in input list within a single scope | `DUPLICATE_ENV_VAR_NAME` |
| `EnvVarSizeLimitExceededError` | per-value, per-dict-entry-count, or per-dict-bytes cap | `ENV_VAR_SIZE_LIMIT_EXCEEDED` |
| `UnknownComponentEnvVarError` | mutation references a component the driver does not declare | `UNKNOWN_COMPONENT_ENV_VAR` |
| `DriverEnvVarDocComponentMismatchError` | driver doc references unknown component | `DRIVER_ENV_VAR_DOC_COMPONENT_MISMATCH` (raised at driver load) |
| `DriverEnvVarDocLevelMismatchError` | `level=component` with empty `components`, or `level=deployment` with non-empty `components` | `DRIVER_ENV_VAR_DOC_LEVEL_MISMATCH` |

All errors subclass `ServiceError` (Constitution §IV); the `StructuredErrorExtension` middleware projects them onto `extensions.code`.
