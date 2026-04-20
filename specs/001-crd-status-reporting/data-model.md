# Data Model: CRD Status Reporting

## Entities

### DeploymentCrdStatus (new)

Stores the latest StyrminDeployment CRD status snapshot per deployment.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | PK, auto-generated | Unique identifier (inherited from StyrminModel) |
| deployment_id | UUID | FK -> Deployment.id, UNIQUE, NOT NULL | One-to-one with Deployment |
| phase | string | NOT NULL | CRD phase: Pending, CreatingPrerequisites, CreatingHelmRelease, CreatingServices, Ready, Failed, Deleting |
| message | string | nullable | Optional status message from the CRD |
| conditions | JSON | nullable | List of condition objects (type, status, reason, message, lastTransitionTime) |
| managed_resource_counts | JSON | nullable | Dict of resource type counts (networkPolicies, secrets, helmReleases, services, middlewares) |
| last_polled_at | datetime | NOT NULL | Timestamp of the last poll that observed this CRD |
| created_on | datetime | NOT NULL, auto | Record creation timestamp (inherited) |
| updated_on | datetime | NOT NULL, auto | Record update timestamp (inherited) |

**Unique constraint**: `deployment_id` — one CRD status record per deployment (upsert semantics).

**Cascade**: DELETE on Deployment deletion.

### Deployment (existing, modified)

Add relationship: `crd_status` -> DeploymentCrdStatus (one-to-one, cascade delete-orphan).

Status field updated by CRD phase mapping:

| CRD Phase | Deployment Status |
|-----------|------------------|
| Pending | pending |
| CreatingPrerequisites | pending |
| CreatingHelmRelease | pending |
| CreatingServices | pending |
| Ready | running |
| Failed | failed |
| Deleting | (no change) |

## Relationships

```text
Deployment (1) ---- (0..1) DeploymentCrdStatus
```

## conditions JSON Schema

```json
[
  {
    "type": "HelmReleaseReady",
    "status": "True",
    "reason": "ReconcileSucceeded",
    "message": "All resources in sync",
    "lastTransitionTime": "2026-04-15T12:00:00Z"
  }
]
```

## managed_resource_counts JSON Schema

```json
{
  "networkPolicies": 1,
  "secrets": 2,
  "helmReleases": 1,
  "services": 3,
  "middlewares": 1
}
```
