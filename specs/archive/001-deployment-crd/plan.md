# Implementation Plan: StyrminDeployment CRD for Operator-Driven Resource Lifecycle

**Branch**: `001-deployment-crd` | **Date**: 2026-04-05 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-deployment-crd/spec.md`

## Summary

Introduce a StyrminDeployment Custom Resource Definition (CRD) that serves as the single declarative intent for a deployment. The kopf operator watches this CRD and deploys resources in a guaranteed order: NetworkPolicies/Secrets first, then HelmRelease (only after prerequisites are verified), then Services/Middlewares. Prefect flows are refactored to create/update/delete the CRD instead of managing Kubernetes resources directly. The operator becomes the sole owner of all utility resources.

## Technical Context

**Language/Version**: Python 3.14 (matches current project)  
**Primary Dependencies**: kopf 1.x (existing), kubernetes-asyncio (existing), prefect 3.6.x (existing)  
**Storage**: PostgreSQL (existing, via Styrmin backend API — operator queries REST endpoint)  
**Testing**: pytest with pytest-asyncio (existing), kopf.testing  
**Target Platform**: Kubernetes cluster (same as current)  
**Project Type**: Web application (backend extension)  
**Performance Goals**: Ordered deployment completes within 5 minutes for standard applications; drift correction within 60 seconds  
**Constraints**: Must not break pre-existing deployments; Prefect task execution logic unchanged  
**Scale/Scope**: Same cluster; CRD per deployment namespace

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | **PASS** | The CRD IS the desired state declaration. Operator reconciles desired vs current. |
| II. Driver-Based Deployment | **PASS** | CRD spec carries the GlobalContext derived from drivers. No ad-hoc logic. |
| III. Layered Architecture | **PASS** | Prefect flow creates CRD via K8s API (not direct DB). Operator reads CRD spec. |
| IV. Type Safety and Typed Errors | **PASS** | Python type hints enforced by ty. |
| V. Test-First Development | **PASS** | Tests required for all new functionality. |
| VI. Format and Lint Before Commit | **PASS** | Standard ruff workflow. |

**Governance Gates triggered:**
- **No new dependencies**: Uses existing kopf and kubernetes-asyncio
- **No DB schema changes**: CRD is a Kubernetes resource, not a database table
- **No GraphQL schema changes**: Status exposed via CRD, not GraphQL

**Post-Phase 1 re-check**: All gates still pass. The CRD is a natural extension of the existing operator architecture.

## Project Structure

### Documentation (this feature)

```text
specs/001-deployment-crd/
├── spec.md
├── plan.md              # This file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/           # Phase 1
│   └── crd-schema.md    # StyrminDeployment CRD spec/status schema
└── tasks.md             # Phase 2 (/speckit.tasks)
```

### Source Code (repository root)

```text
backend/
├── styrmin_backend/
│   ├── operator/
│   │   ├── crd/                         # NEW: CRD-related models and utilities
│   │   │   ├── __init__.py
│   │   │   ├── schema.py                # CRD spec/status Python models
│   │   │   └── status.py                # Status condition helpers
│   │   ├── handlers/
│   │   │   ├── styrmin_deployment.py     # NEW: StyrminDeployment CRD handlers (create/update/delete/timer)
│   │   │   ├── helmrelease.py           # MODIFIED: Remove direct HelmRelease create handler (now driven by CRD)
│   │   │   └── utility_resources.py     # MODIFIED: Drift handlers now apply to all utility types for CRD-managed deployments
│   │   ├── pipeline.py                  # NEW: Ordered deployment pipeline (phases 1-3)
│   │   ├── reconciler.py               # MODIFIED: Extended for all utility resource types
│   │   ├── state.py                     # MODIFIED: Build desired state from CRD spec instead of API
│   │   ├── events.py                    # EXISTING: Reused for CRD events
│   │   └── config.py                    # MODIFIED: Add CRD constants
│   ├── agent/
│   │   └── tasks/
│   │       ├── orchestration.py         # MODIFIED: Create/update/delete StyrminDeployment CRD instead of direct resource management
│   │       └── extra.py                 # MODIFIED: Remove utility resource application (operator handles it)

helm/styrmin/templates/
├── operator/
│   ├── kopf-peering.yaml               # EXISTING
│   └── styrmin-deployment-crd.yaml      # NEW: StyrminDeployment CRD definition

tests/
├── unit/operator/
│   ├── test_pipeline.py                # NEW
│   ├── test_styrmin_deployment.py       # NEW
│   └── test_crd_schema.py              # NEW
```

**Structure Decision**: The operator module is extended with a `crd/` subpackage for CRD-specific models and a new `pipeline.py` for the ordered deployment logic. The existing handler structure is preserved with a new `styrmin_deployment.py` handler file for the CRD lifecycle. The Prefect orchestration flows are simplified to CRD operations.

## Design Decisions

### D1: CRD Spec Carries Full Deployment Context

**Decision**: The StyrminDeployment CRD spec contains the serialized GlobalContext (or its essential fields) so the operator can derive all desired resources from the CRD alone, without calling the backend API.

**Rationale**: This eliminates the runtime dependency on the backend API during reconciliation. The Prefect flow already has the GlobalContext when it creates the CRD — embedding it in the spec makes the CRD self-contained and the operator fully autonomous.

**Alternatives rejected**:
- Operator queries backend API per reconciliation (current approach): Adds latency and failure mode on every reconciliation cycle.
- Store only a deployment ID in the CRD spec: Requires API availability for every reconciliation.

### D2: Sub-Handler Pattern for Ordered Deployment

**Decision**: Use kopf's `@kopf.subhandler(id='...')` pattern inside the create handler for phased deployment. Each sub-handler's return value is tracked by kopf; later phases check earlier phases' results before proceeding.

**Rationale**: kopf natively tracks sub-handler completion. Already-succeeded sub-handlers are never re-executed on retry, giving us idempotent phased execution. This handles the "resume interrupted deployment" requirement (FR-010) automatically.

**Phases**:
1. `phase-1-prerequisites`: Create NetworkPolicies and Secrets
2. `phase-2-helmrelease`: Create HelmRelease (only after phase 1 succeeds)
3. `phase-3-services`: Create Services and Middlewares (only after phase 2 and HelmRelease is Ready)

### D3: Timer for Drift Detection + Phase Advancement

**Decision**: Use `@kopf.timer` on StyrminDeployment for both drift detection (when Ready) and phase advancement (when deploying). The timer checks the current phase and either advances to the next phase or reconciles drift.

**Rationale**: The timer provides the convergence guarantee. It fires every 60 seconds (configurable), catches missed events, and ensures the deployment eventually reaches Ready state even if individual handlers fail.

### D4: Ordered Deletion via Sub-Handlers

**Decision**: Use the same sub-handler pattern in `@kopf.on.delete` for reverse-order cleanup. Kopf's finalizer prevents garbage collection until all sub-handlers succeed.

**Deletion order**: Services/Middlewares → HelmRelease (wait for termination) → NetworkPolicies/Secrets

### D5: Owner References for Automatic Cleanup

**Decision**: Use `kopf.adopt()` to set owner references from the StyrminDeployment CRD to all child resources. This provides a safety net for cleanup if the operator misses a deletion event.

**Rationale**: Owner references are the Kubernetes-native mechanism for parent-child lifecycle. Combined with explicit ordered deletion sub-handlers, this gives us both ordered cleanup (sub-handlers) and eventual cleanup (garbage collection).

### D6: Prefect Flow Simplification

**Decision**: Refactor `create_instance`, `update_instance`, and `upgrade_instance` to create/update/delete a StyrminDeployment CRD instead of directly managing HelmReleases and utility resources. The flow's role becomes: compute GlobalContext, serialize it into CRD spec, apply the CRD.

**What Prefect still does**:
- Compute GlobalContext from deployment configuration
- Render Helm chart/repository specs
- Create/update the StyrminDeployment CRD
- Run driver pre/post hooks (these remain Prefect-managed as they are imperative actions)
- Callback to update task status

**What moves to the operator**:
- Create/manage HelmRelease CRD
- Create/manage all utility resources (NetworkPolicies, Secrets, Services, Middlewares)
- Resource ordering and readiness checking
- Drift detection and correction

### D7: CRD Status Conditions

**Decision**: The CRD status uses Kubernetes-standard condition arrays with types: `NetworkPoliciesReady`, `SecretsReady`, `HelmReleaseReady`, `ServicesReady`, `MiddlewaresReady`, and an overall `Ready` condition. Plus a `phase` field for quick status: `Pending`, `CreatingPrerequisites`, `CreatingHelmRelease`, `CreatingServices`, `Ready`, `Failed`, `Deleting`.

### D8: Backward Compatibility

**Decision**: Pre-existing deployments (without a StyrminDeployment CRD) continue to work via the existing operator handlers from 001-k8s-operator. The new CRD-based flow is forward-only for new deployments. The existing HelmRelease-watching handlers remain active for legacy deployments.

## Complexity Tracking

No constitution violations to justify.
