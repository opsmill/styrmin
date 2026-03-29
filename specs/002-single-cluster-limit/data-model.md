# Data Model: Enforce Single-Cluster Limit

**Feature**: `002-single-cluster-limit` | **Date**: 2026-03-28

## Entities

### Cluster (existing — no schema changes)

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | UUID | PK, auto-generated | Inherited from StyrminModel |
| name | str | UNIQUE, NOT NULL | Default value "default" (new — applied at service/API layer, not DB) |
| config | dict \| None | JSON column | Cluster configuration (ingress, storage, runtime, etc.) |
| created_on | datetime | auto-populated | Inherited from StyrminModel |
| updated_on | datetime | auto-updated | Inherited from StyrminModel |

**Relationships**:
- One-to-many → Environment (back_populates="cluster")

**Invariant (new)**: At most one Cluster row may exist at any time. Enforced at the service layer via `ClusterLimitReachedError`.

### State Transitions

```text
[No Cluster] --createCluster--> [One Cluster]
[One Cluster] --createCluster--> ERROR: ClusterLimitReachedError
[One Cluster] --deleteCluster--> [No Cluster]
```

## New Error Types

### ClusterLimitReachedError

| Property | Value |
|----------|-------|
| Class | `ClusterLimitReachedError(ServiceError)` |
| error_code | `"CLUSTER_LIMIT_REACHED"` |
| default_message | `"Only one cluster is allowed. Delete the existing cluster before creating a new one."` |
| Module | `backend/styrmin_backend/services/exceptions.py` |

**GraphQL behavior**: Raised as a GraphQL error with `extensions.code = "CLUSTER_LIMIT_REACHED"`. Clients can match on this code to display a specific message.

## Validation Rules

- **Name default**: If `name` is not provided to `createCluster`, use `"default"`.
- **Name uniqueness**: Existing UNIQUE constraint on `name` column preserved.
- **Cluster limit**: Before creating, check if any cluster exists. If yes, raise `ClusterLimitReachedError`.
- **Config validation**: Existing `validate_cluster_config()` unchanged.
