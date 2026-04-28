# Phase 1 Data Model

The feature touches one Pydantic model and adds no new entities, no new database tables, no new GraphQL types.

## `IngressServiceConfig` — extended shape

**Location**: `backend/styrmin_backend/context/models/config.py:8-23`

**Existing fields (unchanged)**:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `type` | `str` | `"LoadBalancer"` | Kubernetes Service type. |
| `annotations` | `dict[str, str] \| None` | `None` | Service-level annotations (e.g., for cloud-LB reuse). |
| `load_balancer_ip` | `str \| None` | `None` | Static IP for `LoadBalancer` Services. |
| `external_traffic_policy` | `str \| None` | `None` | `Cluster` or `Local`. |

**New fields**:

| Field | Type | Default | Validation | Purpose |
|-------|------|---------|------------|---------|
| `ip_families` | `list[Literal["IPv4", "IPv6"]] \| None` | `None` | When set: non-empty, no duplicates. | Pin the Service to a specific IP family or families. Renders to chart key `service.ipFamilies`. |
| `ip_family_policy` | `Literal["SingleStack", "PreferDualStack", "RequireDualStack"] \| None` | `None` | (Literal enforces value set.) | Express the dual-stack policy. Renders to chart key `service.ipFamilyPolicy`. |
| `node_port` | `int \| None` | `Field(default=None, ge=1, le=65535)` | When set, requires `type == "NodePort"`. | Fixed NodePort applied to **both** Traefik entrypoints (`web` and `websecure`). |

`model_config = ConfigDict(extra="forbid")` is already set on `IngressServiceConfig` and stays unchanged — adding three known fields is the only extension.

## Validators

### `_validate_ip_families` (field-scoped)

```python
@field_validator("ip_families", mode="after")
@classmethod
def _validate_ip_families(cls, v: list[Literal["IPv4", "IPv6"]] | None) -> list[Literal["IPv4", "IPv6"]] | None:
    if v is None:
        return v
    if len(v) == 0:
        raise ValueError("ip_families must not be empty when set; remove the field to use the cluster default.")
    if len(set(v)) != len(v):
        raise ValueError(f"ip_families must not contain duplicates; got {v!r}.")
    return v
```

Triggered cases (from FR-004 / Edge Cases):

- `[]` → `ValueError` ("must not be empty…").
- `["IPv6", "IPv6"]` → `ValueError` ("must not contain duplicates…").
- `["foo"]` → Pydantic's own `Literal` enforcement raises before this validator runs (the input value is not a member of the Literal).

### `_validate_node_port_requires_nodeport_type` (model-scoped)

```python
@model_validator(mode="after")
def _validate_node_port_requires_nodeport_type(self) -> "IngressServiceConfig":
    if self.node_port is not None and self.type != "NodePort":
        raise ValueError(
            f"node_port is only valid when type == 'NodePort'; "
            f"got type={self.type!r} with node_port={self.node_port}."
        )
    return self
```

Triggered case (FR-006): `type="LoadBalancer"` + `node_port=30443` → `ValueError`. The reverse — `type="NodePort"` + `node_port=None` — passes, preserving the "let Kubernetes pick" path.

The `ge=1, le=65535` constraint on `node_port` is enforced by `Field(...)` at the field level and runs before either of the above validators.

## Merge precedence (inherited; no new logic)

`IngressServiceConfig` is reachable via:

- `ClusterConfig.dedicated_ingress.service`
- `EnvironmentConfig.dedicated_ingress.service`
- `DeploymentConfig.dedicated_ingress.service` (multiply-inherits both)

The merge is performed at the surrounding `DedicatedIngressConfig` / cluster-vs-environment level using `model_dump(exclude_none=True)` followed by dict-merge — see the existing test `TestConfigMergePrecedence` (`backend/tests/unit/services/test_ingress_controller.py:202-247`). Because the new fields default to `None`, they are excluded from `model_dump(exclude_none=True)` until set, so:

- An environment-level config that sets `ip_families` overrides the cluster-level value.
- A cluster-level config that sets `node_port` is preserved when the environment doesn't touch the field.
- A `None` at every level renders as "key absent" in the chart values.

This behavior is automatic from the existing merge mechanism. **No new merge code is added**; tests should assert the inherited behavior (one new test in `TestConfigMergePrecedence` per new field is sufficient).

## Field docstring guidance (FR-012)

The model docstring on `IngressServiceConfig` is updated to document the two canonical scenarios:

- `ip_families: ["IPv6"]` + `ip_family_policy: "SingleStack"` — pin to IPv6 on a dual-stack cluster.
- `ip_family_policy: "RequireDualStack"` — only on clusters that have both families configured; use `PreferDualStack` to opt into dual-stack with single-family fallback.

The docstring also notes that `node_port` is only meaningful when `type == "NodePort"` and that it applies to **both** Traefik entrypoints.

## Out of scope

- Per-entrypoint NodePort split (`{web: int, websecure: int}`) — explicit follow-up per FR-010 and the spec Assumptions.
- Cluster-side topology pre-validation (e.g., refusing `RequireDualStack` on a single-family cluster) — Kubernetes is the source of truth at apply time.
- Pre-validation of cluster-configured NodePort range — cluster-configurable, not safely knowable at config load.
