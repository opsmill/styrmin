# Data Model: Agent Status Reporting

## Entities

### PodStatus (new)

Stores the latest polled status snapshot for a single Kubernetes pod managed by Styrmin.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | PK, auto-generated | Unique identifier (inherited from StyrminModel) |
| deployment_id | UUID | FK -> Deployment.id, NOT NULL | The deployment this pod belongs to |
| pod_name | string | NOT NULL | Kubernetes pod name |
| namespace | string | NOT NULL | Kubernetes namespace |
| phase | enum (PodPhase) | NOT NULL | Pod phase: Pending, Running, Succeeded, Failed, Unknown |
| ready | boolean | NOT NULL | Whether all containers are ready |
| restart_count | integer | NOT NULL, default 0 | Total restart count across all containers |
| container_statuses | JSON | nullable | Detailed per-container status |
| node_name | string | nullable | Node the pod is scheduled on |
| started_at | datetime | nullable | When the pod started running |
| last_polled_at | datetime | NOT NULL | Timestamp of the last poll that observed this pod |
| created_on | datetime | NOT NULL, auto | Record creation timestamp (inherited from StyrminModel) |
| updated_on | datetime | NOT NULL, auto | Record update timestamp (inherited from StyrminModel) |

**Unique constraint**: `(deployment_id, pod_name)` — ensures upsert semantics per pod per deployment.

**Cascade**: DELETE on Deployment deletion — when a deployment is removed, all associated pod statuses are removed.

### PodPhase (new enum)

| Value | Description |
|-------|-------------|
| PENDING | Pod accepted but containers not yet running |
| RUNNING | Pod bound to a node, at least one container running |
| SUCCEEDED | All containers terminated successfully |
| FAILED | All containers terminated, at least one with failure |
| UNKNOWN | Pod state cannot be determined |

### Deployment (existing, modified)

Add relationship: `pod_statuses` -> list of PodStatus (one-to-many, cascade delete-orphan)

### Environment (existing, unchanged)

Used for filtering — pod statuses can be queried by environment through the Deployment -> Environment relationship.

### Cluster (existing, unchanged)

Used for filtering — pod statuses can be queried by cluster through the Environment -> Cluster relationship.

## Relationships

```text
Cluster (1) ---- (*) Environment (1) ---- (*) Deployment (1) ---- (*) PodStatus
```

## State Lifecycle

```text
Poll cycle starts
  |-- For each active deployment namespace:
  |     |-- List pods via K8s API
  |     |-- For each pod:
  |     |     +-- Upsert PodStatus (match on deployment_id + pod_name)
  |     +-- Delete PodStatus records for pods no longer present
  +-- Poll cycle ends

Deployment deleted
  +-- Cascade deletes all associated PodStatus records
```

## container_statuses JSON Schema

```json
[
  {
    "name": "container-name",
    "ready": true,
    "state": "running",
    "restart_count": 0,
    "image": "registry/image:tag",
    "started_at": "2026-04-11T12:00:00Z"
  }
]
```
