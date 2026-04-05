# Data Model: StyrminDeployment CRD

**Branch**: `001-deployment-crd` | **Date**: 2026-04-05

## Overview

This feature introduces a single new Kubernetes Custom Resource Definition (CRD): `StyrminDeployment`. No database schema changes are needed. The CRD replaces the HelmRelease as the primary Kubernetes artifact created by Prefect flows.

## Entities

### StyrminDeployment CRD

**API Group**: `styrmin.io`  
**Version**: `v1alpha1`  
**Kind**: `StyrminDeployment`  
**Plural**: `styrmindeployments`  
**Short name**: `sd`  
**Scope**: Namespaced

#### Spec Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `deploymentId` | string (UUID) | Yes | Links back to the Styrmin database deployment record |
| `releaseReference` | string | Yes | Kubernetes release reference (deterministic from deployment ID) |
| `appName` | string | Yes | Application name from the driver |
| `appVersion` | string | Yes | Application version being deployed |
| `context` | object (preserve-unknown-fields) | Yes | Serialized GlobalContext containing all deployment configuration |
| `helm` | object | Yes | Helm chart and repository specifications |
| `helm.chart` | object | Yes | Chart spec (name, version, values_template) |
| `helm.repository` | object | Yes | Repository spec (url) |
| `labels` | object | No | Custom labels to apply to all managed resources |
| `parameters` | object | No | User-provided parameters |

#### Status Fields

| Field | Type | Description |
|-------|------|-------------|
| `phase` | string (enum) | Current deployment phase: `Pending`, `CreatingPrerequisites`, `CreatingHelmRelease`, `CreatingServices`, `Ready`, `Failed`, `Deleting` |
| `message` | string | Human-readable status message |
| `conditions` | array | Kubernetes-standard condition array |
| `managedResources` | object | Counts of managed resources by type |

#### Status Conditions

| Condition Type | Description |
|----------------|-------------|
| `NetworkPoliciesReady` | All NetworkPolicies created and verified |
| `SecretsReady` | All Secrets created and verified |
| `HelmReleaseReady` | HelmRelease created and FluxCD reports Ready |
| `ServicesReady` | All Services created and verified |
| `MiddlewaresReady` | All Middlewares created and verified |
| `Ready` | Overall deployment is healthy (all above are True) |

Each condition has: `type`, `status` (True/False/Unknown), `reason`, `message`, `lastTransitionTime`

## State Transitions

### Deployment Lifecycle

```
StyrminDeployment Created (by Prefect flow)
    │
    ├── phase: Pending
    │
    ├── Phase 1: Create NetworkPolicies + Secrets
    │   ├── phase: CreatingPrerequisites
    │   ├── Set NetworkPoliciesReady condition
    │   └── Set SecretsReady condition
    │
    ├── Phase 2: Create HelmRelease (BLOCKED until Phase 1 complete)
    │   ├── phase: CreatingHelmRelease
    │   ├── Create HelmRelease CRD
    │   └── Wait for FluxCD Ready → Set HelmReleaseReady condition
    │
    ├── Phase 3: Create Services + Middlewares (BLOCKED until Phase 2 complete)
    │   ├── phase: CreatingServices
    │   ├── Set ServicesReady condition
    │   └── Set MiddlewaresReady condition
    │
    └── phase: Ready (all conditions True)
         │
         ├── [Steady State: Drift Detection]
         │   ├── Timer fires every 60s
         │   ├── Compare desired vs actual for all resource types
         │   └── Reconcile any drift
         │
         ├── [Spec Update: Re-reconcile]
         │   ├── phase: CreatingPrerequisites (restart from Phase 1)
         │   └── Progress through phases again
         │
         └── [Deletion]
              ├── phase: Deleting
              ├── Delete Services + Middlewares
              ├── Delete HelmRelease (wait for termination)
              └── Delete NetworkPolicies + Secrets
```

### Failure States

| Failure Point | Phase | Behavior |
|---------------|-------|----------|
| NetworkPolicy creation fails | CreatingPrerequisites → Failed | HelmRelease NOT created. CRD status shows error. kopf retries. |
| Secret creation fails | CreatingPrerequisites → Failed | Same as above. |
| HelmRelease never reaches Ready | CreatingHelmRelease | CRD stays in CreatingHelmRelease. Timer checks FluxCD status periodically. |
| Service creation fails | CreatingServices → Failed | HelmRelease remains running. CRD status shows which Service failed. |
| Operator restart mid-deployment | Any phase | kopf resumes from last recorded sub-handler state. Completed phases are not re-executed. |

## Relationships

```
StyrminDeployment CRD (styrmin.io/v1alpha1)
    │
    ├── owns → NetworkPolicy (1:N)     [Phase 1, owner reference]
    ├── owns → Secret (1:N)            [Phase 1, owner reference]
    ├── owns → HelmRelease (1:1)       [Phase 2, owner reference]
    │            └── managed by FluxCD → Deployment/StatefulSet/etc
    ├── owns → Service (1:N)           [Phase 3, owner reference]
    └── owns → Middleware (1:N)        [Phase 3, owner reference]

Prefect Flow
    └── creates → StyrminDeployment CRD (1:1 per deployment)
```

## Labels Applied to Managed Resources

All resources created by the operator from a StyrminDeployment carry:

| Label | Value | Purpose |
|-------|-------|---------|
| `app.kubernetes.io/managed-by` | `styrmin` | Identifies Styrmin-managed resources |
| `styrmin.io/deployment-crd` | `<crd-name>` | Links resource to parent StyrminDeployment |
| `styrmin.io/release-reference` | `<release-ref>` | Links to deployment's release reference |
| `styrmin.io/resource-phase` | `prerequisites` / `helm` / `services` | Identifies which deployment phase created this resource |
