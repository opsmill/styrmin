# Feature Specification: StyrminDeployment CRD for Operator-Driven Resource Lifecycle

**Feature Branch**: `001-deployment-crd`  
**Created**: 2026-04-05  
**Status**: Extracted  
**Input**: User description: "Expand how the operator is working by adding a new CRD to manage Styrmin Deployment, this new CRD will be used to trigger the deployment of the NetworkPolicy and the HelmChart as well. The HelmChart should only be deployed once the NetworkPolicies have been properly instantiated. Also update the operator to also manage the Secrets, Services and Middlewares. Update the Prefect task to create/manage the Deployment CRD instead of managing the HelmChart directly."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ordered Resource Deployment via StyrminDeployment CRD (Priority: P1)

As a platform operator, I want the system to deploy application resources in a guaranteed order — NetworkPolicies and Secrets first, then the HelmRelease, then Services and Middlewares — so that applications never start without their security boundaries and credentials in place, and service discovery is configured after the application is running.

**Why this priority**: The ordered deployment is the core value proposition of the CRD. Without it, applications can start without NetworkPolicies (security gap) or without Secrets (crash loops). This is the fundamental orchestration primitive that all other stories depend on.

**Independent Test**: Create a StyrminDeployment CRD in a namespace. Verify that NetworkPolicies and Secrets appear first, then the HelmRelease is created only after all NetworkPolicies report as applied, and finally Services and Middlewares are created after the HelmRelease is ready.

**Acceptance Scenarios**:

1. **Given** a StyrminDeployment CRD is created, **When** the operator processes it, **Then** it creates NetworkPolicies and Secrets before creating the HelmRelease.
2. **Given** NetworkPolicies and Secrets are being created, **When** one fails to apply, **Then** the HelmRelease is NOT created and the CRD status reports the failure with details.
3. **Given** all NetworkPolicies and Secrets are in place, **When** the operator creates the HelmRelease, **Then** it waits for the HelmRelease to reach a Ready state before proceeding to Services and Middlewares.
4. **Given** the full deployment sequence completes successfully, **When** all resources are healthy, **Then** the StyrminDeployment CRD status reports "Ready" with a summary of all managed resources.

---

### User Story 2 - Prefect Orchestration via CRD (Priority: P2)

As a platform operator, I want the Prefect deployment flows to create and update the StyrminDeployment CRD instead of directly managing HelmReleases and utility resources, so that the operator handles all Kubernetes resource lifecycle and the Prefect flow becomes a simple intent declaration.

**Why this priority**: This decouples the Prefect orchestration layer from direct Kubernetes resource management, making the system more maintainable and ensuring all resources go through the operator's ordered deployment pipeline.

**Independent Test**: Trigger a deployment via the standard Styrmin API. Verify that the Prefect flow creates a StyrminDeployment CRD and does NOT directly create HelmReleases, NetworkPolicies, Secrets, Services, or Middlewares. Verify that the operator then deploys all resources from the CRD.

**Acceptance Scenarios**:

1. **Given** a user triggers a new deployment via the Styrmin API, **When** the Prefect flow runs, **Then** it creates a StyrminDeployment CRD containing the full deployment specification (desired Helm values, utility configs, labels).
2. **Given** a user triggers a deployment update, **When** the Prefect flow runs, **Then** it updates the existing StyrminDeployment CRD spec, and the operator reconciles the changes.
3. **Given** a user triggers a deployment deletion, **When** the Prefect flow runs, **Then** it deletes the StyrminDeployment CRD, and the operator cleans up all associated resources in reverse order.

---

### User Story 3 - Full Utility Resource Management by Operator (Priority: P3)

As a platform operator, I want the operator to be the sole owner of ALL utility resources (NetworkPolicies, Secrets, Services, Middlewares) — not just NetworkPolicies — so that there is a single source of truth for resource lifecycle and drift on any utility resource is automatically corrected.

**Why this priority**: The previous iteration only moved NetworkPolicies to operator control. This story completes the migration by moving Secrets, Services, and Middlewares as well, eliminating the split-responsibility model between Prefect and the operator.

**Independent Test**: Create a StyrminDeployment CRD. Verify the operator creates all utility resource types. Manually delete or modify a Service, Secret, or Middleware and verify the operator restores it.

**Acceptance Scenarios**:

1. **Given** a StyrminDeployment is active, **When** a Secret managed by the operator is deleted, **Then** the operator detects the deletion and re-creates the Secret.
2. **Given** a StyrminDeployment is active, **When** a Service's port configuration is manually altered, **Then** the operator corrects the Service back to the desired state.
3. **Given** a StyrminDeployment is active, **When** a Traefik Middleware is modified, **Then** the operator restores it to the specification defined in the deployment context.

---

### User Story 4 - CRD Status and Observability (Priority: P4)

As a platform operator, I want the StyrminDeployment CRD to expose detailed status conditions showing the state of each resource phase (NetworkPolicies, Secrets, HelmRelease, Services, Middlewares) so that I can diagnose deployment issues without reading operator logs.

**Why this priority**: Status visibility is critical for operations but doesn't block core functionality. The deployment works without status reporting, but troubleshooting becomes difficult.

**Independent Test**: Create a StyrminDeployment CRD. Run `kubectl get styrmindeployments` and verify the status shows phase progression. Introduce a failure in one phase and verify the status reflects the error.

**Acceptance Scenarios**:

1. **Given** a StyrminDeployment is being processed, **When** the operator completes each phase, **Then** the CRD status conditions update to reflect the current phase and its outcome.
2. **Given** a StyrminDeployment has all resources deployed, **When** a user runs `kubectl describe styrmindeployment <name>`, **Then** they see conditions for each phase (NetworkPoliciesReady, SecretsReady, HelmReleaseReady, ServicesReady, MiddlewaresReady) with timestamps.
3. **Given** a phase fails, **When** a user inspects the CRD status, **Then** they see which phase failed, the error message, and which resources are affected.

---

### Edge Cases

- What happens if the operator is restarted mid-deployment (between NetworkPolicy creation and HelmRelease creation)? The operator should resume from the current state, not re-run completed phases.
- What happens if the StyrminDeployment CRD spec changes while the operator is mid-deployment? The operator should complete the current reconciliation cycle, then process the spec change on the next cycle.
- What happens if the HelmRelease never reaches Ready state? The operator should report the failure in CRD status and not proceed to Services/Middlewares. The HelmRelease itself has FluxCD retry logic.
- What happens during a rolling update (CRD spec changes)? The operator should update resources in the same ordered sequence: NetworkPolicies/Secrets first, then HelmRelease, then Services/Middlewares.
- What happens when the Prefect flow fails after creating the CRD but before the operator processes it? The CRD exists in the cluster and the operator will process it on its next reconciliation cycle — this is the desired behavior (declarative intent).
- What happens to pre-existing deployments that don't have a StyrminDeployment CRD? They continue to work as before. The CRD approach is forward-only for new deployments.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a StyrminDeployment Custom Resource Definition (CRD) that declaratively describes a complete deployment: desired Helm chart values, utility configurations, labels, and deployment metadata.
- **FR-002**: The operator MUST process StyrminDeployment CRDs and deploy resources in a guaranteed order: (1) NetworkPolicies and Secrets, (2) HelmRelease, (3) Services and Middlewares.
- **FR-003**: The operator MUST NOT create the HelmRelease until all NetworkPolicies and Secrets for the deployment have been successfully applied and verified.
- **FR-004**: The operator MUST be the sole owner of ALL utility resources (NetworkPolicies, Secrets, Services, Middlewares) for CRD-managed deployments. Prefect MUST NOT directly create, update, or delete these resources.
- **FR-005**: The Prefect deployment flows MUST be updated to create/update/delete StyrminDeployment CRDs instead of directly managing HelmReleases and utility resources.
- **FR-006**: The operator MUST continuously reconcile all resources associated with a StyrminDeployment, detecting and correcting drift on any managed resource type.
- **FR-007**: The StyrminDeployment CRD status MUST expose phase-level conditions (NetworkPoliciesReady, SecretsReady, HelmReleaseReady, ServicesReady, MiddlewaresReady) with timestamps and error details.
- **FR-008**: When a StyrminDeployment CRD is deleted, the operator MUST clean up all associated resources in reverse order: Services/Middlewares first, then HelmRelease, then NetworkPolicies/Secrets.
- **FR-009**: The operator MUST handle spec updates on existing StyrminDeployment CRDs by reconciling changes through the same ordered deployment sequence.
- **FR-010**: The operator MUST resume interrupted deployments from the current state rather than re-running completed phases.
- **FR-011**: Pre-existing deployments without a StyrminDeployment CRD MUST continue to function unchanged.

### Key Entities

- **StyrminDeployment CRD**: A custom Kubernetes resource that declares the complete desired state for a Styrmin deployment, including Helm chart configuration, utility specifications, labels, and deployment context. Serves as the single point of intent for the operator.
- **Deployment Phase**: A discrete stage in the ordered deployment sequence (NetworkPolicies, Secrets, HelmRelease, Services, Middlewares). Each phase has a readiness condition and must complete before the next phase begins.
- **Managed Resource**: Any Kubernetes resource (NetworkPolicy, Secret, HelmRelease, Service, Middleware) that is created and reconciled by the operator based on a StyrminDeployment CRD specification.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All new deployments follow the guaranteed ordering: NetworkPolicies/Secrets are verified as applied before HelmRelease creation begins, with zero exceptions.
- **SC-002**: The operator manages 100% of utility resources (NetworkPolicies, Secrets, Services, Middlewares) for CRD-managed deployments — Prefect directly manages zero Kubernetes resources beyond the CRD itself.
- **SC-003**: Drift on any managed resource (any of the five types) is detected and corrected within 60 seconds.
- **SC-004**: Platform operators can determine the deployment status of any CRD-managed deployment by inspecting the StyrminDeployment CRD status, without reading operator logs.
- **SC-005**: The Prefect deployment flow is simplified to CRD create/update/delete operations, with no direct HelmRelease or utility resource management.

## Assumptions

- The StyrminDeployment CRD contains sufficient information to derive the complete desired state for all resources (Helm values, utility specs, labels). This information is currently available in the GlobalContext.
- The kopf operator framework supports watching custom CRDs with the same handler patterns used for built-in resources.
- FluxCD continues to manage the actual Helm chart reconciliation from the HelmRelease CRD. The StyrminDeployment operator creates the HelmRelease and monitors its status but does not replace FluxCD.
- The Prefect flow callback mechanism (for task state updates) continues to work through the existing GraphQL mutation, independent of how Kubernetes resources are managed.
- This is a forward-only change. Pre-existing deployments retain their current behavior (direct HelmRelease management by Prefect).

## Scope Boundaries

### In Scope

- StyrminDeployment CRD definition with spec and status subresource
- Operator handlers for CRD create/update/delete lifecycle
- Ordered deployment pipeline (NetworkPolicies/Secrets → HelmRelease → Services/Middlewares)
- Full utility resource ownership by operator (all five types)
- Prefect flow refactoring to create CRDs instead of direct resource management
- CRD status conditions for each deployment phase
- Continuous drift reconciliation for all managed resource types
- Ordered cleanup on CRD deletion

### Out of Scope

- Migration of pre-existing deployments to CRD-based management
- UI changes for CRD status display
- Multi-cluster CRD management
- CRD versioning/migration strategy (v1alpha1 is sufficient for initial release)
- Helm chart packaging for the CRD (manual kubectl apply is sufficient initially)

## Dependencies

- **001-k8s-operator**: This feature builds on the kopf operator infrastructure established in the previous feature (operator module, combined entrypoint, reconciler, state client)
- **kopf**: Continues as the operator framework, now watching a custom CRD
- **FluxCD**: Continues to reconcile HelmRelease resources — the operator creates/monitors HelmReleases but FluxCD does the actual Helm chart deployment
- **Styrmin backend API**: The operator (or the CRD spec) must contain all information needed to derive desired resource state
