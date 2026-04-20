# Feature Specification: Kubernetes Operator for Deployment Reconciliation

**Feature Branch**: `001-k8s-operator`  
**Created**: 2026-04-05  
**Status**: Extracted  
**Input**: User description: "I want to extend the capabilities of the k8s agent to also work as an operator, the task execution logic with prefect shouldn't change but in addition I would like to build an operator that will track the deployments and that will ensure that the additional utility, network policy etc are always accurate. I want to use the library kopf to manage the k8s operator using Python."

## Clarifications

### Session 2026-04-05

- Q: Who manages NetworkPolicy lifecycle? → A: The operator manages NetworkPolicies moving forward, not the Prefect workflow. The Prefect flows will no longer create or update NetworkPolicies.
- Q: Deployment topology? → A: Single container running both the kopf operator and the Prefect agent together, not separate workloads.
- Q: Runtime model? → A: The combined agent/operator runs using async, with both components sharing a single async event loop.
- Q: How does the operator obtain desired state for NetworkPolicies? → A: The operator queries the Styrmin backend API/database to build GlobalContext and compute the desired NetworkPolicy specifications.
- Q: Should other utilities also migrate to operator control? → A: Only NetworkPolicies move to operator control now. The architecture should support migrating other utilities (Services, Secrets, Middlewares) in future iterations.
- Q: Should the operator adopt existing Prefect-created NetworkPolicies? → A: Forward-only. The operator manages NetworkPolicies only for new deployments created after the operator is running. Existing NetworkPolicies remain as-is.
- Q: How should the operator expose reconciliation status? → A: Kubernetes Events emitted on the HelmRelease resource, visible via kubectl describe.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Operator-Managed NetworkPolicy Lifecycle (Priority: P1)

As a platform operator, I want the kopf operator to be the sole owner of NetworkPolicy resources for managed deployments so that NetworkPolicies are created when deployments appear, updated when deployment configuration changes, and deleted when deployments are removed - all independently of the Prefect deployment flow.

**Why this priority**: Moving NetworkPolicy management to the operator ensures these critical security resources are continuously reconciled and never drift. This is the primary responsibility shift that defines the operator's role.

**Independent Test**: Trigger a new deployment via the standard Prefect flow, verify that the operator (not Prefect) creates the corresponding NetworkPolicy. Then modify the NetworkPolicy manually and verify the operator restores it.

**Acceptance Scenarios**:

1. **Given** a new application deployment is created via the Prefect flow after the operator is running, **When** the deployment's HelmRelease appears in the cluster, **Then** the operator detects it and creates the correct NetworkPolicy based on the deployment's configuration.
2. **Given** an operator-managed deployment has NetworkPolicies, **When** a NetworkPolicy is manually deleted or modified, **Then** the operator detects the change and restores the NetworkPolicy to its desired state.
3. **Given** an operator-managed deployment is being removed, **When** the HelmRelease is deleted, **Then** the operator cleans up the associated NetworkPolicies.
4. **Given** the operator is running, **When** it encounters a NetworkPolicy for a pre-existing deployment (created before the operator was deployed) or a NetworkPolicy without operator ownership labels, **Then** it ignores that resource and takes no action.

---

### User Story 2 - Continuous Reconciliation of Other Utility Resources (Priority: P2)

As a platform operator, I want the operator to continuously monitor and reconcile the remaining utility resources (Services, Secrets, Traefik Middlewares) generated alongside each deployment so that any drift from the desired state is automatically corrected.

**Why this priority**: While NetworkPolicies are the first resource type to move fully under operator control, the remaining utility resources also benefit from drift detection and reconciliation. This story extends the reconciliation pattern to all utility resource types.

**Independent Test**: Deploy an application with service discovery utilities enabled, manually modify a generated Service, and verify the operator detects the change and restores the resource.

**Acceptance Scenarios**:

1. **Given** an application is deployed with utility resources (Service, Secret, Middleware), **When** a utility resource is manually deleted from the cluster, **Then** the operator detects the deletion and re-creates the resource within the reconciliation interval.
2. **Given** an application is deployed with service discovery Services, **When** a Service's port configuration is manually altered, **Then** the operator corrects the Service back to the expected configuration.
3. **Given** the operator is running, **When** it encounters a resource it does not manage (no ownership labels), **Then** it ignores that resource.

---

### User Story 3 - Combined Agent/Operator Process (Priority: P3)

As a platform administrator, I want the kopf operator and Prefect agent to run together in a single container as a unified async process so that the deployment footprint is minimized and both components share the same runtime lifecycle.

**Why this priority**: Running both components in a single container simplifies deployment, reduces resource overhead, and ensures they start and stop together. The async runtime allows both to coexist without blocking each other.

**Independent Test**: Start the combined process, verify that both the Prefect agent picks up work and the kopf operator watches resources. Then gracefully shut down the container and verify both components stop cleanly.

**Acceptance Scenarios**:

1. **Given** the combined container starts, **When** the async event loop initializes, **Then** both the kopf operator and Prefect agent begin processing concurrently.
2. **Given** the combined process is running, **When** a Prefect flow is submitted while the operator is reconciling, **Then** both operations proceed without blocking each other.
3. **Given** the combined process receives a shutdown signal, **When** graceful shutdown begins, **Then** both the operator and agent stop cleanly without leaving resources in an inconsistent state.

---

### User Story 4 - Deployment Tracking and Status Reporting (Priority: P4)

As a platform operator, I want the operator to track the status of all managed deployments and their associated utility resources so that I have a real-time view of whether each deployment's full resource set is healthy and in sync with the desired state.

**Why this priority**: Without status visibility, operators cannot tell whether resources have drifted or whether the operator is functioning correctly. Tracking provides observability and builds confidence in the reconciliation system.

**Independent Test**: Deploy an application, verify the operator reports its status as healthy. Then introduce drift on a utility resource and verify the operator reports the resource as out-of-sync before correcting it.

**Acceptance Scenarios**:

1. **Given** the operator is watching a namespace with managed deployments, **When** all utility resources match their desired state, **Then** the operator reports the deployment's resource set as "in-sync."
2. **Given** the operator detects drift on a utility resource, **When** it begins reconciliation, **Then** the deployment's status reflects "reconciling" until the resource is restored.
3. **Given** the operator fails to reconcile a resource (e.g., permission denied, invalid spec), **When** the reconciliation attempt completes, **Then** the operator reports the failure with a meaningful error and does not continuously retry in a tight loop.

---

### Edge Cases

- What happens when a Prefect deployment flow and the operator both need to act on resources for the same deployment? Since NetworkPolicies are now operator-managed, the Prefect flow should not touch them. For other utility resources still created by Prefect, the operator should defer reconciliation while a deployment operation is in progress.
- What happens when a deployment is being deleted? The operator should clean up NetworkPolicies it owns and stop reconciling other utility resources for that deployment.
- What happens when the operator loses connectivity to the Kubernetes API? It should handle transient API failures gracefully and resume reconciliation when connectivity is restored.
- What happens when the operator cannot reach the Styrmin backend API? It should use exponential backoff and skip reconciliation for affected deployments until the backend is reachable again, rather than applying stale or empty state.
- What happens when a managed resource has been intentionally modified outside the operator (e.g., emergency hotfix)? The operator will revert it on the next reconciliation cycle. Operators should use the standard deployment flow for permanent changes.
- What happens when multiple operator replicas run simultaneously? Only one replica should actively reconcile at a time (leader election) to avoid conflicts.
- What happens if the kopf operator component crashes but the Prefect agent is healthy (or vice versa)? Since they share a container, both restart together.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a kopf-based Kubernetes operator that runs as a long-lived process, watching for changes to managed utility resources and HelmReleases.
- **FR-012**: The operator MUST query the Styrmin backend API to build GlobalContext for each managed deployment, using the same context model that the Prefect flows use to compute desired resource specifications.
- **FR-002**: The operator MUST be the sole owner of NetworkPolicy resources for new deployments created after the operator is running - creating, updating, and deleting them based on deployment lifecycle events. The Prefect workflow MUST no longer manage NetworkPolicies for new deployments. Pre-existing deployments' NetworkPolicies remain untouched.
- **FR-003**: The operator MUST detect when other managed utility resources (Services, Secrets, Traefik Middlewares) are modified or deleted and reconcile them back to their desired state.
- **FR-004**: The operator MUST NOT modify the existing Prefect-based task execution logic. Prefect flows remain the mechanism for HelmRelease deployment, updates, and upgrades.
- **FR-005**: The operator MUST identify managed resources using ownership labels or annotations to distinguish them from resources it should not touch.
- **FR-006**: The operator MUST implement leader election to ensure only one active reconciliation instance runs at a time in multi-replica deployments.
- **FR-007**: The operator and Prefect agent MUST run together in a single container as a unified async process, sharing the same event loop.
- **FR-008**: The operator MUST expose its reconciliation status (in-sync, reconciling, error) by emitting Kubernetes Events on the corresponding HelmRelease resource, making status visible via `kubectl describe`.
- **FR-009**: The operator MUST handle transient Kubernetes API failures gracefully with exponential backoff rather than tight retry loops.
- **FR-010**: The operator MUST log reconciliation actions (drift detected, resource restored, errors encountered) for auditability.
- **FR-011**: The combined process MUST support graceful shutdown, allowing both the operator and Prefect agent to stop cleanly.

### Key Entities

- **Managed Deployment**: A Styrmin deployment whose utility resources are tracked by the operator. Identified by ownership labels applied during the Prefect deployment flow.
- **Desired State**: The set of utility resource specifications derived from the deployment's GlobalContext and utility definitions. This is the source of truth the operator reconciles against.
- **Reconciliation Event**: An occurrence where the operator detects drift between actual and desired state and takes corrective action.
- **Utility Resource**: A Kubernetes resource (NetworkPolicy, Service, Secret, Middleware CRD) generated as part of a deployment. For new deployments, NetworkPolicies are created exclusively by the operator; other utilities are created by Prefect and reconciled by the operator. Pre-existing deployments retain their original resource ownership.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Drifted or deleted utility resources are automatically restored to their desired state within 60 seconds of the change being detected.
- **SC-002**: The operator correctly creates NetworkPolicies for all new deployments without requiring Prefect flow involvement.
- **SC-003**: Active Prefect deployment flows are never disrupted by operator reconciliation - zero conflicts between the operator and in-progress deployments.
- **SC-004**: The operator recovers from transient failures (API unavailability, network issues) without manual intervention.
- **SC-005**: Platform operators can determine the sync status of any managed deployment's utility resources at any time via Kubernetes Events on the HelmRelease.
- **SC-006**: The combined operator/agent process starts and stops as a single unit with no orphaned components.

## Assumptions

- The existing labeling/annotation scheme used by the utilities framework provides sufficient information to identify managed resources. If not, the labeling scheme will be extended as part of implementation.
- The operator will run in the same cluster as the managed deployments. Multi-cluster operator support is out of scope.
- The kopf library provides adequate primitives for leader election, resource watching, and handler registration needed by this feature.
- The operator obtains desired state by querying the Styrmin backend API to build GlobalContext, using the same context model and utility definitions as the Prefect deployment flow.
- The Styrmin backend API is available and reachable from the operator's network context within the cluster.
- Reconciliation of the main HelmRelease CRD is out of scope - FluxCD already handles HelmRelease reconciliation.
- The kopf async runtime and Prefect agent's async runtime can coexist on a shared event loop without interference.

## Scope Boundaries

### In Scope

- Kopf-based operator that creates and manages NetworkPolicies for all managed deployments
- Drift detection and automatic correction for all utility resource types (NetworkPolicies, Services, Secrets, Traefik Middlewares)
- Single-container deployment combining the kopf operator and Prefect agent in a unified async process
- Removal of NetworkPolicy management from the Prefect deployment flows
- Status reporting for managed deployments' utility resource sets
- Leader election for multi-replica operator deployments
- Graceful shutdown of the combined process

### Out of Scope

- Changes to the existing Prefect-based task execution logic (HelmRelease deployment, updates, upgrades)
- Reconciliation of HelmRelease CRDs (handled by FluxCD)
- Multi-cluster operator support
- Custom Resource Definitions (CRDs) for operator configuration (use ConfigMap/environment-based configuration)
- UI changes for operator status (can be added later)
- Operator installation via Helm chart (deployment manifests are sufficient initially)
- Migration of Services, Secrets, or Middleware creation from Prefect to operator in this iteration (only NetworkPolicies move now; others remain Prefect-created but operator-reconciled, with the architecture designed to support future migration)

## Dependencies

- **kopf**: Python framework for writing Kubernetes operators
- **Existing utilities framework**: The operator reuses the same utility resource builders (ingress, service_discovery) to derive desired state
- **Existing labeling conventions**: Resources must be labeled to identify operator-managed resources
- **FluxCD**: Continues to manage HelmRelease reconciliation independently
- **Styrmin backend API**: The operator queries the backend to build GlobalContext and compute desired resource specifications
