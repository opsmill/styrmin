# Research: StyrminDeployment CRD for Operator-Driven Resource Lifecycle

**Branch**: `001-deployment-crd` | **Date**: 2026-04-05

## R1: Kopf Custom CRD Handler Patterns

**Decision**: Use `@kopf.on.create('styrmin.io', 'v1alpha1', 'styrmindeployments')` decorator syntax for all CRD handlers.

**Rationale**: kopf accepts three positional args `(group, version, plural)` for custom CRDs. This is the most explicit form and matches the CRD definition. The `@kopf.subhandler(id='...')` pattern provides idempotent phased execution with automatic tracking.

**Key findings**:
- Sub-handler return values are stored in `status.<parent_handler_id>.<subhandler_id>` automatically
- Already-succeeded sub-handlers are never re-executed on retry (idempotent by design)
- `kopf.TemporaryError(message, delay=N)` causes a retry after N seconds without re-running succeeded sub-handlers
- `patch.status` is automatically sent to the `/status` subresource endpoint when the CRD has `subresources: { status: {} }` enabled

## R2: CRD Spec Design — Embedding GlobalContext

**Decision**: Embed the serialized GlobalContext (or its essential fields) directly in the StyrminDeployment CRD spec using `x-kubernetes-preserve-unknown-fields: true`.

**Rationale**: The Prefect flow already computes the GlobalContext before creating resources. Embedding it in the CRD spec makes the operator fully autonomous — it doesn't need to call the backend API during reconciliation. This eliminates the API availability as a runtime dependency for the operator.

**Alternatives considered**:
- Store only deployment_id and fetch context from API: Adds latency and failure mode. Rejected because it makes reconciliation fragile.
- Store a rendered resource manifest: Too large and couples the CRD to specific resource shapes. Rejected for maintainability.

**CRD spec fields** (derived from GlobalContext):
- `deploymentId`: UUID linking back to the Styrmin database
- `releaseReference`: Kubernetes release reference (deterministic from deployment ID)
- `context`: Serialized GlobalContext (full deployment configuration)
- `helm`: Helm chart and repository specifications (rendered)

## R3: Phase-Based Deployment Pattern

**Decision**: Use kopf sub-handlers for the initial deployment flow and a timer for ongoing drift detection.

**Rationale**: Sub-handlers give us:
1. Automatic idempotency tracking (no re-execution of completed phases)
2. Native retry with `kopf.TemporaryError`
3. Phase ordering via status checks between sub-handlers
4. Resume-from-interruption for free (kopf tracks handler state on the resource)

The timer provides convergence guarantee and drift detection post-deployment.

**Phase sequence**:
1. `phase-1-prerequisites`: Apply NetworkPolicies + Secrets → verify all created
2. `phase-2-helmrelease`: Create HelmRelease → wait for FluxCD Ready condition
3. `phase-3-services`: Apply Services + Middlewares → verify all created

## R4: Ordered Deletion

**Decision**: Use sub-handlers in `@kopf.on.delete` for reverse-order cleanup, combined with `kopf.adopt()` owner references as a safety net.

**Rationale**: kopf adds a finalizer when a delete handler is registered. The resource cannot be garbage-collected until all sub-handlers succeed. Owner references provide eventual cleanup if the operator misses a deletion.

**Deletion phases**:
1. Delete Services and Middlewares
2. Delete HelmRelease (wait for termination)
3. Delete NetworkPolicies and Secrets

## R5: Prefect Flow Refactoring

**Decision**: Replace direct resource management in `create_instance`, `update_instance`, `upgrade_instance` with StyrminDeployment CRD create/update/delete operations.

**What the Prefect flow does after refactoring**:
1. Compute GlobalContext from deployment configuration
2. Render Helm chart/repository specifications
3. Serialize context into StyrminDeployment CRD spec
4. Create/update the CRD via kubernetes-asyncio API
5. (Optional) Poll CRD status until Ready
6. Run driver pre/post hooks (unchanged — these are imperative actions)
7. Callback to update task status (unchanged)

**What is removed from Prefect**:
- Direct HelmRelease creation/update
- Direct utility resource creation/update (`install_utility`, `update_utility`)
- Namespace label management (operator handles it)
- HelmRelease polling (operator watches it)

## R6: CRD Status Design

**Decision**: Use Kubernetes-standard condition arrays plus a `phase` summary field.

**Conditions** (each has type, status, reason, message, lastTransitionTime):
- `NetworkPoliciesReady`
- `SecretsReady`
- `HelmReleaseReady`
- `ServicesReady`
- `MiddlewaresReady`
- `Ready` (overall)

**Phase values**: `Pending`, `CreatingPrerequisites`, `CreatingHelmRelease`, `CreatingServices`, `Ready`, `Failed`, `Deleting`

**Additional printer columns** for `kubectl get styrmindeployments`:
- Phase
- App name
- Age
