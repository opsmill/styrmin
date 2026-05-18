# Phase 1: Data Model — external-dns endpoints-type

## Scope

This feature adds **one** field to one Pydantic config model. There are no new entities, no new database tables or columns, no new GraphQL types, and no new SDK types. The field rides through the existing `JSON`-column storage path and the existing `JSON | None` GraphQL input.

## Modified Entity

### `BaseConfigSection`

**Location**: `backend/styrmin_backend/context/models/config.py` (currently lines 315–340).

**Existing siblings the new field joins**:

| Field | Type | Default |
|-------|------|---------|
| `ingress_class` | `str \| None` | `None` |
| `db_size` | `str \| None` | `None` |
| `fqdn_suffix` | `str \| None` | `None` |
| `external_url_scheme` | `Literal["http", "https"] \| None` | `None` |
| `external_url_port` | `int \| None` (validated 1..65535) | `None` |
| `scheduling` | `SchedulingConfig \| None` | `None` |

**New field**:

| Field | Type | Default | Validation |
|-------|------|---------|------------|
| `external_dns_endpoints_type` | `Literal["NodeExternalIP", "ClusterIP"] \| None` | `None` | Pydantic-native `Literal` rejection at config-parse time; rejected values produce a `ValidationError` naming the field and listing accepted values. |

**Field placement**: alongside `external_url_port`, before `scheduling`. Insertion point keeps the ingress/external-routing fields visually grouped (`ingress_class`, `fqdn_suffix`, `external_url_scheme`, `external_url_port`, `external_dns_endpoints_type`).

**Docstring requirement (FR-006)**: The Pydantic `Field(...)` description on `external_dns_endpoints_type` MUST explain when an operator sets it — specifically that `"NodeExternalIP"` is the value required for IPv6 / dual-stack clusters where the published AAAA record must resolve to the node's external IP rather than the Service `ClusterIP`. The `BaseConfigSection` class docstring's `Attributes:` block MUST also be extended with a one-line entry for the field.

## Inheritance & Merge Behaviour

`BaseConfigSection` is the parent of:

```text
BaseConfigSection
├── ClusterConfig
├── EnvironmentConfig
└── DeploymentConfig (multi-inherits from ClusterConfig + EnvironmentConfig)
    └── ResolvedConfig
```

Because the field is declared on `BaseConfigSection` with `Optional` default `None`:

- It is accepted on every layer (cluster, environment, deployment) without per-layer plumbing.
- It is consumed at render time through `context.instance.config.external_dns_endpoints_type`, where `context.instance.config` is a `ResolvedConfig`.
- The Cluster → Environment → Deployment merge already in place for sibling fields propagates the deepest non-`None` value to `ResolvedConfig`. No merge code changes.

**Layer precedence** (deepest wins, matches `fqdn_suffix` / `ingress_class`):

```text
Deployment value (if not None)
    ↓ falls through to
Environment value (if not None)
    ↓ falls through to
Cluster value (if not None)
    ↓ falls through to
None  →  no annotation emitted
```

## Storage

**No DB migration.** The `Cluster.config`, `Environment.config`, and `Deployment.config` columns are already typed as `JSON`/`JSONB` (see `backend/styrmin_backend/db/models.py` lines 32, 59, 128, 194, 215). The new optional key round-trips through these columns transparently.

Backwards compatibility: rows written before this feature ships have config blobs that simply omit the key. Pydantic deserialisation treats the absent key as `None` (the default), and the renderer emits no annotation — fully consistent with FR-004.

## Wire Format

**No GraphQL schema change.** The `create_cluster` / `create_environment` / `create_deployment` mutations all declare `config: JSON | None = None`. The new field becomes a recognised key in that JSON blob, validated server-side when the blob is deserialised into `ClusterConfig` / `EnvironmentConfig` / `DeploymentConfig`.

Operator-facing JSON shape (cluster example):

```json
{
  "fqdn_suffix": "infrahub.cloud.example.com",
  "ingress_class": "traefik",
  "external_dns_endpoints_type": "NodeExternalIP"
}
```

Equivalent YAML (for operators editing config files directly):

```yaml
fqdn_suffix: infrahub.cloud.example.com
ingress_class: traefik
external_dns_endpoints_type: NodeExternalIP
```

## Validation Rules

| Rule | Source | Implementation |
|------|--------|----------------|
| Accepted values are exactly `"NodeExternalIP"`, `"ClusterIP"`, or `null`/missing. | FR-001, FR-005 | Pydantic `Literal["NodeExternalIP", "ClusterIP"] \| None`. |
| Rejection happens at config-parse time, before any reconcile or Kubernetes call. | FR-005, SC-003 | Pydantic raises `ValidationError` during `ClusterConfig(...)` / `EnvironmentConfig(...)` / `DeploymentConfig(...)` construction, which is invoked at the same point as the existing `external_url_scheme` validation. |
| `model_config = ConfigDict(extra="forbid")` applies (inherited). | Existing model invariant | An operator who misspells the field name (e.g. `external_dns_endpoint_type` — missing `s`) gets a `ValidationError` for the unknown key, not a silent no-op. |

## State Transitions

The field has no lifecycle of its own. It is read-only at render time and has no history, audit trail, or in-flight states. Operator changes it the same way they change any other config field: edit the cluster/environment/deployment config and reconcile.

## Out of Scope (explicitly)

- Additional external-dns endpoint types (`PodIP`, `HostIP`, …). The accepted set is exactly the two values needed for the IPv6/Cloudflare recipe (Assumptions §3 in spec).
- Auto-detection of cluster IP-family to set the field automatically. Out of scope; operator opts in explicitly.
- Exposing the field on `CreateEnvironmentDialog` and `CreateDeploymentDialog`. The Cluster-layer form control alone covers the IPv6/Cloudflare recipe documented in `quickstart.md`; per-environment / per-deployment overrides remain available via the JSON `config` payload accepted by the corresponding GraphQL mutations.
