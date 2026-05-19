# Data Model — Hierarchical Pod Scheduling & Resource Configuration

This document captures the Pydantic / storage shape of the new configuration section. All types are defined in `backend/styrmin_backend/context/models/config.py` (added to the existing file) and re-exported from `styrmin_backend.services.scheduling.models` for API-side consumers. Every model uses `ConfigDict(extra="forbid")` unless explicitly noted.

## Overview

The feature adds a single optional field, `scheduling: SchedulingConfig | None`, to the existing `BaseConfigSection` and therefore to all of its subclasses (`ClusterConfig`, `EnvironmentConfig`, `DeploymentConfig`, `ResolvedConfig`). Component-level scheduling sits under the `scheduling` key inside the existing `Component.config` JSON column. No database migration is required.

```text
BaseConfigSection
  └── scheduling: SchedulingConfig | None = None     # NEW
        ├── pod_affinity: AffinityBlock | None
        ├── pod_anti_affinity: AffinityBlock | None
        ├── node_affinity: AffinityBlock | None
        ├── topology_spread_constraints: list[TopologySpreadConstraint] | None
        ├── resources: ResourceRequirements | None
        ├── tolerations: list[Toleration] | None
        ├── runtime_class: str | None
        └── inject: PostRenderInjection | None
```

---

## Entities (new)

### 1. SchedulingConfig

The root of the feature's configuration section. Present on every level (environment, deployment, component); absent fields inherit from shallower levels.

```python
class SchedulingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pod_affinity: AffinityBlock | None = None
    pod_anti_affinity: AffinityBlock | None = None
    node_affinity: AffinityBlock | None = None
    topology_spread_constraints: list[TopologySpreadConstraint] | None = None
    resources: ResourceRequirements | None = None
    tolerations: list[Toleration] | None = None
    runtime_class: str | None = None
    inject: PostRenderInjection | None = None
```

**Validation rules**:
- If `runtime_class` is set, it MUST be a non-empty DNS-1123 subdomain (`^[a-z0-9]([a-z0-9-.]*[a-z0-9])?$`).
- `inject` is only meaningful at Deployment and Component scopes (Environment-scope `inject` is accepted but ignored by the resolver; we document this rather than reject it, to keep the schema uniform).

### 2. AffinityBlock

Represents one affinity kind (`podAffinity`, `podAntiAffinity`, or `nodeAffinity`) at one level.

```python
class AffinityBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: list[AffinityTerm] = []
    preferred: list[WeightedAffinityTerm] = []
    replace: bool = False
```

**Merge behaviour**:
- `required` terms from all levels are concatenated (ANDed by the scheduler).
- `preferred` terms are merged into a single weighted list preserving each level's weights.
- `replace: true` at a level MUST discard all shallower-level terms for that affinity-kind for the affected component(s). Levels deeper than the one that set `replace: true` continue to accumulate on top of the replacement unless they also set `replace: true`.
- `replace` is scoped per-affinity-kind — setting it on `pod_affinity` does not affect `pod_anti_affinity` or `node_affinity`.

### 3. AffinityTerm

A single affinity term — may carry either a raw Kubernetes-style `labelSelector` (escape hatch) OR a platform-level `deployment_ref` that the resolver expands into a label selector.

```python
class AffinityTerm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topology_key: str                                           # required for pod affinity/anti-affinity
    namespaces: list[str] | None = None
    namespace_selector: LabelSelector | None = None
    label_selector: LabelSelector | None = None
    deployment_ref: DeploymentReference | None = None           # mutually exclusive with label_selector
    match_label_keys: list[str] | None = None
    mismatch_label_keys: list[str] | None = None

    @model_validator(mode="after")
    def _require_one_selector(self) -> "AffinityTerm":
        if (self.label_selector is None) == (self.deployment_ref is None):
            raise ValueError("Exactly one of label_selector or deployment_ref must be set.")
        return self
```

For `nodeAffinity`, `topology_key` is unused and MUST be set to the empty string or a node-label key; a separate `NodeAffinityTerm` variant will be introduced if downstream needs diverge (see Note below). A Pydantic `model_validator` on `SchedulingConfig.node_affinity` accepts `topology_key == ""` to avoid forcing operators to invent a meaningless value; downstream patch builders MUST ignore `topology_key` on node-affinity terms regardless of its value.

**Validation**: `deployment_ref` is rejected at configuration time (`UnresolvableAffinityReferenceError`) if the target deployment cannot be found in the environment (FR-001d).

> **Note on node affinity**: node affinity uses `nodeSelectorTerms` / `matchExpressions`, which are shaped differently from pod affinity terms. For v1 the `AffinityBlock` reused by `node_affinity` accepts a restricted `AffinityTerm` whose `topology_key` is ignored and whose `label_selector` is interpreted as a node-label selector. A dedicated `NodeAffinityTerm` type can replace this if operator feedback justifies the complexity.

### 4. WeightedAffinityTerm

```python
class WeightedAffinityTerm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weight: int                      # 1..100 per Kubernetes API
    term: AffinityTerm

    @field_validator("weight")
    @classmethod
    def _weight_range(cls, v: int) -> int:
        if not 1 <= v <= 100:
            raise ValueError("weight must be between 1 and 100.")
        return v
```

### 5. DeploymentReference

```python
class DeploymentReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deployment_id: UUID | None = None                # one or the other
    deployment_name: str | None = None
    components: list[str] | None = None              # optional narrowing

    @model_validator(mode="after")
    def _require_one_identifier(self) -> "DeploymentReference":
        if (self.deployment_id is None) == (self.deployment_name is None):
            raise ValueError("Exactly one of deployment_id or deployment_name must be set.")
        return self
```

Resolver behaviour (FR-001c, FR-001d): at resolve time the reference is expanded into:

```yaml
labelSelector:
  matchLabels:
    styrmin/deployment_id: "<resolved-uuid>"
    # if `components` is set, additionally match on the component label:
    # styrmin/component: <component-name>   (one term per listed component, joined via matchExpressions)
```

Re-evaluated every reconciliation; does not cache the selector.

### 6. LabelSelector

```python
class LabelSelector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_labels: dict[str, str] | None = None
    match_expressions: list[LabelSelectorRequirement] | None = None

class LabelSelectorRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    operator: Literal["In", "NotIn", "Exists", "DoesNotExist"]
    values: list[str] | None = None
```

### 7. TopologySpreadConstraint

```python
class TopologySpreadConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_skew: int
    topology_key: str
    when_unsatisfiable: Literal["DoNotSchedule", "ScheduleAnyway"]
    label_selector: LabelSelector | None = None
    min_domains: int | None = None
    node_affinity_policy: Literal["Honor", "Ignore"] | None = None
    node_taints_policy: Literal["Honor", "Ignore"] | None = None
    match_label_keys: list[str] | None = None
```

**Merge**: union across levels keyed by `(topology_key, when_unsatisfiable)`; deepest-level entry wins per key (FR-010b).

### 8. ResourceRequirements, ResourceSpec, Quantity

```python
class ResourceRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests: ResourceSpec | None = None
    limits: ResourceSpec | None = None

class ResourceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cpu: str | None = None                     # parseable Kubernetes quantity, e.g. "100m", "2"
    memory: str | None = None                  # e.g. "256Mi", "2Gi"
    ephemeral_storage: str | None = None
    extended: dict[str, str] = {}              # hugepages, vendor resources; values are quantities

    @model_validator(mode="after")
    def _validate_quantities(self) -> "ResourceSpec":
        for name, value in self._iter_quantities():
            _parse_k8s_quantity(value)         # raises ValueError on invalid input
        for key, value in self.extended.items():
            _validate_extended_key(key)        # non-empty, no whitespace, allows "domain/name"
            _parse_k8s_quantity(value)
        return self
```

**Merge**: `requests` and `limits` are structs — deepest-level-wins at the individual field level. `extended` maps are merged key-by-key (deepest wins per key; no deletion at shallower levels via this merge).

### 9. Toleration

```python
class Toleration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str | None = None
    operator: Literal["Exists", "Equal"] | None = None
    value: str | None = None
    effect: Literal["NoSchedule", "PreferNoSchedule", "NoExecute"] | None = None
    toleration_seconds: int | None = None
```

**Merge**: union across levels (FR-009). De-duplication compares the full tuple `(key, operator, value, effect, toleration_seconds)`.

### 10. PostRenderInjection

```python
class PostRenderInjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pod_affinity: bool = True            # covers both pod_affinity and pod_anti_affinity
    node_affinity: bool = True
    topology_spread: bool = True
    resources: bool = True
    tolerations: bool = True
    runtime_class: bool = True
```

**Scope**: valid on `DeploymentConfig.scheduling.inject` and per-component scheduling (via the component's `scheduling.inject`). Component-level flags override deployment-level flags for the affected component (FR-016).

---

## Entities (extended)

### BaseConfigSection (existing; EXTENDED)

Add: `scheduling: SchedulingConfig | None = None`.

### Component (existing; no schema change)

The existing `Component.config: dict` column already accepts arbitrary driver-section fields (`backup`, component `identifier`, etc.). Component-level scheduling lives under the `scheduling` key:

```json
{
  "identifier": {"label": {"infrahub/service": "infrahub-server"}},
  "scheduling": { /* SchedulingConfig */ }
}
```

The `ArbitrarySectionModel` (`context/models/components.py:36–44`) already has `ConfigDict(extra="allow")` so `scheduling` is accepted today; the resolver is what changes.

### GlobalContext.components[*] (existing; EXTENDED via resolver output)

Post-resolution, each `ComponentContext` exposes two new fields (via a new `ResolvedComponentScheduling` wrapper):

```python
class ResolvedComponentScheduling(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: SchedulingConfig                                           # effective merged config
    provenance: dict[str, Literal["environment", "deployment", "component"]]
```

The `ComponentContext` (existing) gains a new optional attribute:

```python
class ComponentContext(BaseModel):
    # existing fields:
    config: ArbitrarySectionModel
    name: str
    enabled: bool
    # NEW:
    scheduling: ResolvedComponentScheduling | None = None
```

### InstanceContext.config (ResolvedConfig) (existing; EXTENDED)

`ResolvedConfig.scheduling` is the fully merged scheduling configuration at the Deployment scope (no per-component overrides applied). Drivers that do not declare components still get a usable resolved value.

---

## State Transitions (resolver)

Given the four inputs:
- `env: EnvironmentConfig.scheduling | None`
- `dep: DeploymentConfig.scheduling | None`
- `comp: SchedulingConfig | None` (pulled from `Component.config["scheduling"]`)
- `driver_components: list[str]` (FR-005 validation)

The resolver produces, for each declared component:

1. **Scalar / struct fields** (`runtime_class`, `resources.requests.cpu`, …): deepest-level-wins.
2. **Tolerations**: union with dedup by full tuple.
3. **TopologySpreadConstraints**: union keyed by `(topology_key, when_unsatisfiable)`; deepest wins per key.
4. **Affinity blocks** (pod, pod-anti, node): per-kind accumulate → if any level for that kind sets `replace: true`, discard all shallower terms for that kind at that point in the walk, then continue accumulating deeper levels.
5. **Inject flags**: component value (if set) overrides deployment value (if set) overrides default `True`.

Determinism (FR-011) is ensured by:
- Iterating levels in a fixed order (`env → dep → comp`).
- Using deterministic list operations (concatenation, not `set`; dedup preserves first occurrence).
- Sibling components are resolved independently.

---

## Error model

New `ServiceError` subclasses (registered in `backend/styrmin_backend/services/exceptions.py`):

| Error | `error_code` | Raised when |
|---|---|---|
| `InvalidSchedulingConfigError` | `VALIDATION_ERROR` | Any Pydantic `ValidationError` while parsing the `scheduling` payload (shape, quantity syntax, weight range, DNS-1123 runtime-class name). |
| `UnknownComponentInConfigError` | `VALIDATION_ERROR` | A component-level scheduling payload references a name not declared by the driver (FR-005). |
| `UnresolvableAffinityReferenceError` | `VALIDATION_ERROR` | `DeploymentReference` at config-time resolves to no visible deployment in the environment (FR-001d). |

> Note: a `RuntimeClassNotFoundError` was originally defined to reject runtime-class names not installed on the cluster. That check was removed after the feature shipped — `runtime_class` now passes through validation and an unknown name surfaces later as a Pending pod with a scheduler error.

The resolver surfaces per-field error paths in `error_metadata` so the GraphQL `StructuredErrorExtension` (`api/errors.py:39–66`) forwards them on `extensions.metadata.path`.

---

## Relationships diagram

```text
Environment.config.scheduling ─┐
                                ├─► (merge) ─► ResolvedConfig.scheduling ──► InstanceContext.config.scheduling
Deployment.config.scheduling  ─┘                                                                │
                                                                                                 ▼
Component.config.scheduling  ──► (merge with Resolved) ─► ComponentContext.scheduling (per-component effective config + provenance)
                                                                                                 │
                                                                                                 ▼
                                                           scheduling.patch_builder ─► list[TargetPatch] ─► HelmRelease.postRenderers
```

---

## Invariants

- **I1**: For every field, if no level sets it, the effective value is `None` / absent (spec Edge Cases: "Removing a level's configuration" — clearing propagates to absence).
- **I2**: The resolved `scheduling` for a deployment without `Component` overrides equals the merge of environment + deployment alone. This is what `InstanceContext.config.scheduling` holds.
- **I3**: Changing a shallower-level value causes the next reconcile to produce a different `ResolvedConfig`, which triggers a new HelmRelease render (FR-019).
- **I4**: `inject` flags control only the post-renderer. The global context still exposes the full resolved configuration regardless — drivers that want to read opted-out fields can still do so (Story 5).
