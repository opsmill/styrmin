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
| `deletionRequested` | boolean | No (default `false`) | Set to `true` by the backend's `deleteDeployment` mutation to request operator-driven teardown. Immutable once `true` (CEL transition rule `oldSelf == false \|\| self == true` enforced by the API server). |

The context is embedded directly in the CRD (see ADR-006), making the operator autonomous — no backend API calls needed during reconciliation.

### Namespace co-location (load-bearing constraint)

The CRD is `scope: Namespaced` and lives **inside the deployment's own namespace** (`styrmin-{deployment_id}`). Deleting that namespace deletes the CR with it. Any state transition you want observed must complete BEFORE the namespace is gone, OR you must rely on a separate "DB DELETING + CR absent → infer terminal" path (this is what the agent's status reporter does for the platform-driven delete flow — see [`overview.md`](overview.md) → Status Reporter and `services/deployment_status.py`). New work that needs a phase change to land after namespace deletion will silently fail without this callout — design accordingly.

### Status

| Field | Description |
|-------|-------------|
| `phase` | `Pending` / `CreatingPrerequisites` / `CreatingHelmRelease` / `CreatingServices` / `Ready` / `Failed` / `Deleting` / `Deleted` |
| `displayState` | User-facing state surfaced to the UI: `Deploying` / `Running` / `Restoring` / `Error` / `Deleting` / `Deleted` |
| `conditions` | K8s-standard condition array: `NetworkPoliciesReady`, `SecretsReady`, `HelmReleaseReady`, `ServicesReady`, `MiddlewaresReady`, `Ready`, `Deleted` |
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

Two paths exist:

**Platform-driven (preferred)**: the backend's `deleteDeployment` mutation patches `spec.deletionRequested = true`. A `@kopf.on.update(field="spec.deletionRequested", new=True)` handler observes the flip and runs `_teardown_owned_resources` in reverse order (Services/Middlewares → HelmRelease → NetworkPolicies/Secrets), then issues a namespace delete. The periodic timer advances `phase` to `Deleted` once the namespace returns 404. Because the StyrminDeployment CR lives inside the deployment's own namespace, the CR is garbage-collected with the namespace; the agent's status reporter detects "DB DELETING + CR absent" and synthesises a final `displayState: Deleted` report so the DB is tombstoned race-free.

**Manual safety-net**: `kubectl delete styrmindeployment ...` triggers the existing `@kopf.on.delete` handler, which runs the same `_teardown_owned_resources` helper. This path does **not** produce a DB tombstone — it's a recovery mechanism for when the platform-driven path is unavailable.

After the platform-driven path completes, the StyrminDeployment CR remains in `phase: Deleted` for `DELETED_CR_TTL_HOURS` (default 6h, env-configurable) so operators can inspect cluster-side state. A `@kopf.timer` janitor in `operator/janitor.py` reaps CRs whose `Deleted` condition's `lastTransitionTime` is past the TTL. CRs stuck in `Deleting` are NEVER auto-reaped.

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
