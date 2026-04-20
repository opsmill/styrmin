# Implementation Plan: Kubernetes Operator for Deployment Reconciliation

**Branch**: `001-k8s-operator` | **Date**: 2026-04-05 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-k8s-operator/spec.md`

## Summary

Extend the existing Kubernetes agent to include a kopf-based operator that continuously reconciles utility resources (NetworkPolicies, Services, Secrets, Traefik Middlewares) for managed deployments. NetworkPolicy lifecycle management moves from Prefect flows to the operator for new deployments. The kopf operator and Prefect worker run together in a single container as a unified async process using `asyncio.gather()`, with kopf owning signal handling and bridging shutdown to the Prefect worker via cleanup handlers.

## Technical Context

**Language/Version**: Python 3.14 (matches current project)  
**Primary Dependencies**: kopf (operator framework), prefect 3.6.x (existing), httpx (existing, for API calls), kubernetes client (existing)  
**Storage**: PostgreSQL (existing, via Styrmin backend API - operator queries REST endpoint, does not access DB directly)  
**Testing**: pytest with pytest-asyncio (existing), kopf.testing module for operator handler testing  
**Target Platform**: Kubernetes cluster (same as current agent deployment)  
**Project Type**: Web application (backend extension)  
**Performance Goals**: Utility resource drift corrected within 60 seconds of detection  
**Constraints**: Must not modify existing Prefect task execution logic; single container for operator + Prefect worker  
**Scale/Scope**: Same cluster as managed deployments; operator watches HelmRelease resources across namespaces

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | **PASS** | The operator embodies this principle - reconciling desired vs current state for utility resources. Reconciliation is idempotent. |
| II. Driver-Based Deployment | **PASS** | Operator derives desired state from the same GlobalContext/driver definitions. No ad-hoc deployment logic. |
| III. Layered Architecture | **PASS** | Operator queries the backend REST API (`GET /deployments/{id}/context`) through the service layer. No direct DB access. |
| IV. Type Safety and Typed Errors | **PASS** | Operator code will use type hints (enforced by ty). Error handling follows project patterns. |
| V. Test-First Development | **PASS** | Unit tests for handlers, integration tests for reconciliation logic, e2e tests against Kind cluster. |
| VI. Format and Lint Before Commit | **PASS** | Standard `uv run invoke format lint` workflow. |

**Governance Gates triggered:**
- **New dependency**: `kopf` - required by spec (user-specified choice)
- **No DB schema changes**: Operator uses existing REST API
- **No GraphQL schema changes**: Status exposed via Kubernetes Events, not GraphQL

**Post-Phase 1 re-check**: All gates still pass. The operator is additive to the existing architecture and reuses existing resource builders and context resolution through the REST API.

## Project Structure

### Documentation (this feature)

```text
specs/001-k8s-operator/
├── spec.md              # Feature specification
├── plan.md              # This file
├── research.md          # Phase 0: research findings
├── data-model.md        # Phase 1: data model
├── quickstart.md        # Phase 1: quickstart guide
├── contracts/           # Phase 1: API contracts
│   └── operator-events.md  # Kubernetes Event schema
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
backend/
├── styrmin_backend/
│   ├── operator/                    # NEW: kopf operator module
│   │   ├── __init__.py
│   │   ├── handlers/               # kopf event handlers
│   │   │   ├── __init__.py
│   │   │   ├── helmrelease.py      # HelmRelease create/update/delete watchers
│   │   │   └── utility_resources.py # Utility resource drift handlers
│   │   ├── reconciler.py           # Core reconciliation logic
│   │   ├── state.py                # Desired state resolution (API client)
│   │   ├── events.py               # Kubernetes Event emission
│   │   └── config.py               # Operator configuration
│   ├── entrypoint/                  # NEW: unified process entrypoint
│   │   ├── __init__.py
│   │   └── combined.py             # asyncio.gather(kopf, prefect) main()
│   ├── agent/
│   │   ├── tasks/
│   │   │   ├── orchestration.py    # MODIFIED: skip NetworkPolicy for operator-managed deployments
│   │   │   └── extra.py            # MODIFIED: skip NetworkPolicy utility for operator-managed deployments
│   │   └── service/kubernetes/resources/
│   │       └── builders/
│   │           └── utility.py      # MODIFIED: add operator-managed label for new deployments
│   └── ...

tests/
├── unit/
│   └── operator/
│       ├── test_handlers.py
│       ├── test_reconciler.py
│       └── test_state.py
├── integration/
│   └── operator/
│       └── test_reconciliation.py
```

**Structure Decision**: The operator is a new top-level module under `styrmin_backend/operator/` since it represents a distinct runtime component (kopf handlers) that is architecturally separate from the Prefect-based agent. The unified entrypoint lives in `styrmin_backend/entrypoint/` to coordinate both components. Existing agent code is modified minimally - only to skip NetworkPolicy creation for operator-managed deployments.

## Complexity Tracking

No constitution violations to justify.

## Design Decisions

### D1: Shared Async Event Loop (Pattern A)

**Decision**: Use `asyncio.gather(kopf.operator(...), run_prefect_worker())` in a single event loop.

**Rationale**: kopf's `operator()` coroutine snapshots all pre-existing asyncio tasks at startup and ignores them during shutdown. This means the Prefect worker task survives kopf's internal cleanup. Both components share one event loop with no thread coordination needed.

**Alternatives rejected**:
- Separate threads (Pattern B): More complex, requires thread-safe bridging between kopf and Prefect event loops. Not needed since both are async-native.
- Separate containers: Contradicts spec requirement for single container.

### D2: Signal Handling & Graceful Shutdown

**Decision**: Let kopf own SIGTERM/SIGINT handlers. Use `@kopf.on.cleanup()` to set a shared `asyncio.Event` that signals the Prefect worker to stop.

**Rationale**: kopf registers its own signal handlers in `spawn_tasks()`, overwriting any previously registered handlers. Fighting over signal registration creates race conditions. Instead, kopf's cleanup handler provides a reliable shutdown bridge.

**Shutdown sequence**:
1. SIGTERM received → kopf's internal `signal_flag` set
2. kopf begins shutdown, runs `@kopf.on.cleanup()` handlers
3. Cleanup handler sets shared `_shutdown` asyncio.Event
4. Prefect worker detects event, cancels task group, runs teardown
5. Both coroutines complete, `asyncio.gather()` returns

### D3: Operator Discovers Deployments via HelmRelease Watch

**Decision**: The operator watches `HelmRelease` resources (FluxCD CRD) with Styrmin ownership labels. When a new HelmRelease appears with the operator-managed label, the operator creates the corresponding NetworkPolicies.

**Rationale**: HelmRelease is the primary Kubernetes artifact created by Prefect flows. Watching it provides a reliable trigger for the operator to act. No custom CRD needed.

**Label-based filtering**: The operator watches HelmReleases with label `app.kubernetes.io/managed-by: styrmin`. A new label `styrmin.io/operator-managed: "true"` distinguishes new deployments (operator manages NetworkPolicies) from pre-existing ones (Prefect-managed).

### D4: Desired State via REST API

**Decision**: The operator calls `GET /deployments/{deployment_id}/context` to obtain GlobalContext, then uses existing `UtilityResourceBuilder` and `IngressUtility` to compute desired resource specs.

**Rationale**: This REST endpoint already exists and returns the complete GlobalContext. The operator reuses the same resource builders used by Prefect flows, ensuring consistency. No separate state store needed.

**Deployment ID extraction**: The `styrmin.io/release-reference` label on the HelmRelease maps to the deployment's Kubernetes reference. The operator resolves this to a deployment ID via the existing label scheme or a lightweight API lookup.

### D5: Forward-Only Adoption

**Decision**: Only deployments created after the operator is running get the `styrmin.io/operator-managed: "true"` label. The Prefect flow adds this label when creating the HelmRelease. Pre-existing deployments retain their current behavior.

**Rationale**: User chose forward-only to avoid disrupting existing deployments. The Prefect flow's `ApplicationHelmReleaseBuilder` is modified to add the operator-managed label, signaling the operator to take ownership.

### D6: Drift Detection Strategy

**Decision**: Use kopf's resource watching (`@kopf.on.update`, `@kopf.on.delete`, `@kopf.timer`) to detect changes to utility resources that have Styrmin ownership labels.

**Approach**:
- **For NetworkPolicies (operator-created)**: `@kopf.on.update` and `@kopf.on.delete` handlers on `NetworkPolicy` resources with label `styrmin.io/operator-managed: "true"`. On drift, immediately reconcile.
- **For other utilities (Prefect-created, operator-reconciled)**: `@kopf.on.update` and `@kopf.on.delete` handlers on `Service`, `Secret`, `Middleware` with label `app.kubernetes.io/managed-by: styrmin`.
- **Periodic full reconciliation**: `@kopf.timer` handler on HelmRelease runs every 60 seconds to catch any missed events and ensure convergence.

### D7: Conflict Avoidance with Prefect Flows

**Decision**: The operator checks for an "in-progress" annotation on the HelmRelease before reconciling. Prefect flows set `styrmin.io/deployment-in-progress: "true"` before modifying resources and remove it after completion.

**Rationale**: This prevents the operator from fighting with an active deployment flow. The annotation acts as a lightweight mutex visible to both the operator (via kopf watch) and the Prefect flow (via the existing `apply_kubernetes_resource` primitives).

### D8: Status via Kubernetes Events

**Decision**: The operator emits Kubernetes Events on the HelmRelease resource for status reporting.

**Event types**:
- `Normal` / `ReconcileSucceeded`: All utility resources in sync
- `Normal` / `DriftDetected`: Drift detected, reconciliation starting
- `Warning` / `ReconcileFailed`: Reconciliation failed (with error details)

**Rationale**: User chose Kubernetes Events over API callbacks. Events are native, require no additional API surface, and are visible via `kubectl describe helmrelease/<name>`.
