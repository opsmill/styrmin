# Kubernetes Operator

<!-- Extracted from specs/001-k8s-operator and specs/001-deployment-crd on 2026-04-06 -->

## Overview

The operator is a kopf-based Kubernetes controller that runs alongside the Prefect agent in a single container, sharing one async event loop. It manages the full lifecycle of Kubernetes resources for Styrmin deployments through a custom `StyrminDeployment` CRD.

```text
┌──────────────────────────────────────────────────────────┐
│                  Combined Container                       │
│                                                          │
│  ┌─────────────────┐    ┌─────────────────────────────┐  │
│  │  Prefect Agent   │    │     Kopf Operator           │  │
│  │  (worker loop)   │    │  (CRD watcher + reconciler) │  │
│  └────────┬─────────┘    └──────────┬──────────────────┘  │
│           │                         │                     │
│           └────────┬────────────────┘                     │
│                    │                                      │
│           Shared asyncio event loop                       │
└──────────────────────────────────────────────────────────┘
```

The entrypoint uses `asyncio.gather(kopf.operator(...), run_prefect_worker())` to run both components concurrently. See ADR-004 for the rationale.

## StyrminDeployment CRD

The operator watches `StyrminDeployment` custom resources (`styrmin.io/v1alpha1`). These are created by Prefect flows and contain the full deployment specification.

**API Group**: `styrmin.io` | **Version**: `v1alpha1` | **Kind**: `StyrminDeployment` | **Short name**: `sd`

### Spec Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `deploymentId` | string (UUID) | Yes | Links to Styrmin database deployment |
| `releaseReference` | string | Yes | Kubernetes release reference |
| `appName` | string | Yes | Application name from driver |
| `appVersion` | string | Yes | Application version |
| `context` | object | Yes | Serialized GlobalContext (full deployment config) |
| `helm` | object | Yes | Chart and repository specs |
| `labels` | object | No | Custom labels for managed resources |
| `parameters` | object | No | User-provided parameters |

The context is embedded directly in the CRD (see ADR-006), making the operator autonomous — no backend API calls needed during reconciliation.

### Status

| Field | Description |
|-------|-------------|
| `phase` | `Pending` / `CreatingPrerequisites` / `CreatingHelmRelease` / `CreatingServices` / `Ready` / `Failed` / `Deleting` |
| `conditions` | K8s-standard condition array: `NetworkPoliciesReady`, `SecretsReady`, `HelmReleaseReady`, `ServicesReady`, `MiddlewaresReady`, `Ready` |
| `managedResources` | Counts by type (networkPolicies, secrets, helmReleases, services, middlewares) |

Printer columns for `kubectl get styrmindeployments`: Phase, App, Version, Age.

## Phase-Based Deployment

Resources are deployed in a guaranteed order using kopf sub-handlers (see ADR-007):

```text
StyrminDeployment Created
    │
    ├── Phase 1: NetworkPolicies + Secrets
    │   (HelmRelease is NOT created until all prerequisites are verified)
    │
    ├── Phase 2: HelmRelease
    │   (Wait for FluxCD Ready condition)
    │
    └── Phase 3: Services + Middlewares
         │
         └── phase: Ready
```

Sub-handlers provide automatic idempotency — completed phases are never re-executed on retry. If the operator restarts mid-deployment, it resumes from the last completed phase.

### Deletion

Reverse order: Services/Middlewares → HelmRelease (wait for termination) → NetworkPolicies/Secrets. kopf adds a finalizer to prevent garbage collection until all sub-handlers succeed. Owner references provide a safety net.

## Drift Detection and Reconciliation

A timer handler fires every 60s to compare desired vs actual state for all managed resource types. Drift on any resource is automatically corrected.

### Reconciliation States

| State | Condition |
|-------|-----------|
| `Ready` | All resources match desired state |
| `CreatingPrerequisites` / `CreatingHelmRelease` / `CreatingServices` | Deployment or update in progress |
| `Failed` | Reconciliation failed (API error, permission denied) |

## Managed Resources

The operator is the sole owner of all utility resources for CRD-managed deployments:

| Resource | API Version | Created By |
|----------|------------|------------|
| NetworkPolicy | `networking.k8s.io/v1` | Operator |
| Secret | `v1` | Operator |
| HelmRelease | `helm.toolkit.fluxcd.io/v2` | Operator (reconciled by FluxCD) |
| Service | `v1` | Operator |
| Middleware | `traefik.io/v1alpha1` | Operator |

### Labels

All resources created from a StyrminDeployment carry:

| Label | Value | Purpose |
|-------|-------|---------|
| `app.kubernetes.io/managed-by` | `styrmin` | Identifies Styrmin-managed resources |
| `styrmin.io/deployment-crd` | `<crd-name>` | Links to parent StyrminDeployment |
| `styrmin.io/release-reference` | `<release-ref>` | Links to deployment's release reference |
| `styrmin.io/resource-phase` | `prerequisites` / `helm` / `services` | Deployment phase that created this resource |

### Resource Naming

- NetworkPolicies: `{release_reference}-{policy_name}` (e.g., `abc123def-default-deny-egress`)
- NetworkPolicies per deployment: default-deny-egress, default-deny-ingress, allow-traefik-ingress, traefik-netpolicy-egress, prefect-netpolicy-egress, plus app-specific

## Kubernetes Events

The operator emits events on the StyrminDeployment resource for observability:

| Event | Type | When |
|-------|------|------|
| `ReconcileSucceeded` | Normal | All resources match desired state |
| `DriftDetected` | Normal | Resource modified or deleted unexpectedly |
| `ReconcileFailed` | Warning | Failed to reconcile a resource |

Events are visible via `kubectl describe styrmindeployment <name>`.

## Leader Election

Uses kopf's built-in peering with `ClusterKopfPeering` CRD (see ADR-005). Priority-based: the highest-priority operator instance runs while others pause. Peer records expire after a configurable lifetime (default 60s).

## Relationship to Prefect Flows

Prefect flows create/update/delete StyrminDeployment CRDs as a declaration of intent (see ADR-008). The operator then manages all Kubernetes resources. Driver pre/post hooks still execute via Prefect.

```text
Prefect Flow                          Operator
    │                                     │
    ├── Compute GlobalContext              │
    ├── Serialize into CRD spec            │
    ├── Create StyrminDeployment ─────────►├── Phase 1: Prerequisites
    │                                     ├── Phase 2: HelmRelease
    ├── Run driver hooks                  ├── Phase 3: Services
    ├── Update task status                └── Continuous drift detection
    │
```

Pre-existing deployments without a StyrminDeployment CRD continue to work unchanged (forward-only).
