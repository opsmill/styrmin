# Operator Contracts: Kubernetes Events

**Branch**: `001-k8s-operator` | **Date**: 2026-04-05

## Overview

The operator exposes reconciliation status via Kubernetes Events emitted on the HelmRelease resource. No new API endpoints or GraphQL mutations are introduced.

## Kubernetes Event Schema

### Event: ReconcileSucceeded

Emitted when all utility resources for a deployment match their desired state.

```yaml
apiVersion: v1
kind: Event
metadata:
  name: <helmrelease-name>.<hash>
  namespace: <deployment-namespace>
involvedObject:
  apiVersion: helm.toolkit.fluxcd.io/v2
  kind: HelmRelease
  name: <helmrelease-name>
  namespace: <deployment-namespace>
reason: ReconcileSucceeded
message: "All utility resources in sync for deployment <release-reference>"
type: Normal
source:
  component: styrmin-operator
```

### Event: DriftDetected

Emitted when the operator detects a change to a managed utility resource that differs from desired state.

```yaml
apiVersion: v1
kind: Event
metadata:
  name: <helmrelease-name>.<hash>
  namespace: <deployment-namespace>
involvedObject:
  apiVersion: helm.toolkit.fluxcd.io/v2
  kind: HelmRelease
  name: <helmrelease-name>
  namespace: <deployment-namespace>
reason: DriftDetected
message: "Drift detected on <resource-kind>/<resource-name>: <change-type>"
type: Normal
source:
  component: styrmin-operator
```

**Change types**: `modified`, `deleted`

### Event: ReconcileFailed

Emitted when the operator fails to reconcile a utility resource.

```yaml
apiVersion: v1
kind: Event
metadata:
  name: <helmrelease-name>.<hash>
  namespace: <deployment-namespace>
involvedObject:
  apiVersion: helm.toolkit.fluxcd.io/v2
  kind: HelmRelease
  name: <helmrelease-name>
  namespace: <deployment-namespace>
reason: ReconcileFailed
message: "Failed to reconcile <resource-kind>/<resource-name>: <error-message>"
type: Warning
source:
  component: styrmin-operator
```

## REST API (Existing - No Changes)

The operator consumes the existing REST endpoint. No modifications needed.

### GET /deployments/{deployment_id}/context

**Used by**: Operator state resolution (`operator/state.py`)

**Response**: `GlobalContext` JSON (existing schema, unchanged)

**Error handling**:
- `404`: Deployment not found (operator stops managing this deployment)
- `5xx`: Backend unavailable (operator retries with exponential backoff)

## Labels & Annotations Contract

### New Labels (Added to Existing Scheme)

| Label | Applied To | Set By | Value |
|-------|-----------|--------|-------|
| `styrmin.io/operator-managed` | HelmRelease, NetworkPolicy | Prefect flow (HelmRelease), Operator (NetworkPolicy) | `"true"` |
| `styrmin.io/deployment-id` | HelmRelease | Prefect flow | `"<uuid>"` |

### New Annotations

| Annotation | Applied To | Set By | Value | Lifecycle |
|------------|-----------|--------|-------|-----------|
| `styrmin.io/deployment-in-progress` | HelmRelease | Prefect flow | `"true"` | Set before deployment, removed after completion |

### Existing Labels (Unchanged)

| Label | Applied To | Set By |
|-------|-----------|--------|
| `app.kubernetes.io/managed-by` | All utility resources | `UtilityResourceBuilder` |
| `styrmin.io/utility-kind` | All utility resources | `UtilityResourceBuilder` |
| `styrmin.io/release-reference` | All utility resources | `UtilityResourceBuilder` |
