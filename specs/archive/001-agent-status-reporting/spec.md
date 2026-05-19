# Feature Specification: Agent Status Reporting

**Feature Branch**: `001-agent-status-reporting`  
**Created**: 2026-04-11  
**Status**: Extracted  
**Input**: [GitHub Issue #61](https://github.com/opsmill/styrmin/issues/61) — Add periodic deployment status polling from Kubernetes agents  

## User Scenarios & Testing *(mandatory)*

### User Story 1 - View Current Pod Health for a Deployment (Priority: P1)

As a platform operator, I want to query the current health status of all pods belonging to a Styrmin-managed deployment so that I can assess workload health without logging into the cluster directly.

**Why this priority**: This is the core value proposition — providing visibility into running workloads after the initial deployment completes. Today, once a deployment task finishes, there is no ongoing health visibility in Styrmin.

**Independent Test**: Can be fully tested by deploying an application through Styrmin, waiting for a poll cycle, then querying the status via the GraphQL API. The returned data should reflect the actual pod states in the cluster.

**Acceptance Scenarios**:

1. **Given** a deployment is running in a Styrmin-managed namespace, **When** the agent completes a poll cycle, **Then** the latest pod status (phase, readiness, restart count, container statuses) is available via the GraphQL API.
2. **Given** a pod in a managed deployment restarts, **When** the next poll cycle completes, **Then** the updated restart count and status are reflected in the API response.
3. **Given** a deployment has multiple pods, **When** a user queries the deployment's workload status, **Then** status for all pods is returned with per-pod detail.

---

### User Story 2 - Agent Periodically Reports Status to Backend (Priority: P1)

As the Styrmin platform, the agent running in each Kubernetes cluster must automatically and periodically collect pod and workload status for all Styrmin-managed resources and report it back to the central backend.

**Why this priority**: This is the data collection mechanism that makes all other stories possible. Without the agent polling and reporting, there is no status data to query.

**Independent Test**: Can be tested by running the agent against a cluster with Styrmin-managed namespaces and verifying that the backend database receives status updates at the configured interval.

**Acceptance Scenarios**:

1. **Given** the agent is running in a cluster with Styrmin-managed deployments, **When** the configured polling interval elapses, **Then** the agent collects pod status for all managed namespaces and reports it to the backend.
2. **Given** the polling interval is configured to 30 seconds, **When** the agent runs, **Then** status reports arrive approximately every 30 seconds.
3. **Given** a cluster has no Styrmin-managed deployments, **When** a poll cycle runs, **Then** the agent completes without errors and reports an empty status set.

---

### User Story 3 - Filter Workload Status by Scope (Priority: P2)

As a platform operator managing multiple clusters and environments, I want to filter workload status by cluster, environment, or specific deployment so that I can focus on the scope relevant to my investigation.

**Why this priority**: Filtering is essential for usability at scale but is secondary to having the data available at all.

**Independent Test**: Can be tested by deploying applications across multiple environments, then querying status with different filter parameters and verifying correct scoping of results.

**Acceptance Scenarios**:

1. **Given** deployments exist across multiple environments, **When** a user queries status filtered by a specific environment, **Then** only pods in that environment's namespace are returned.
2. **Given** multiple clusters are connected, **When** a user queries status filtered by cluster, **Then** only pods from that cluster are returned.
3. **Given** a specific deployment, **When** a user queries its workload status, **Then** only pods belonging to that deployment are returned.

---

### User Story 4 - Configurable Polling Interval (Priority: P3)

As a platform administrator, I want to configure the polling interval per agent so that I can balance freshness of data against resource consumption based on cluster size and criticality.

**Why this priority**: Sensible defaults cover most cases; configurability is a refinement for advanced operators.

**Independent Test**: Can be tested by setting different polling interval values and verifying the agent adjusts its collection frequency accordingly.

**Acceptance Scenarios**:

1. **Given** the polling interval environment variable is set to 120 seconds, **When** the agent starts, **Then** it polls at approximately 120-second intervals.
2. **Given** no polling interval is configured, **When** the agent starts, **Then** it uses the default interval of 60 seconds.

---

### Edge Cases

- What happens when the Kubernetes API is temporarily unreachable during a poll cycle? The agent should log the error and retry on the next cycle without crashing.
- What happens when a namespace is deleted between poll cycles? The agent should handle the missing namespace gracefully and remove stale status data.
- What happens when a pod is in a transient state (e.g., `ContainerCreating`, `Terminating`)? These states should be reported as-is and updated on the next cycle.
- What happens when the backend is unreachable during status reporting? The agent should retry on the next cycle; the latest successful report remains visible.
- What happens when a deployment is deleted from Styrmin but pods still exist? Stale status records should be cleaned up when the associated deployment is removed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The agent MUST periodically collect pod-level status for all pods in Styrmin-managed namespaces only (no cluster-wide watches).
- **FR-002**: Collected status MUST include at minimum: pod name, pod phase, ready condition, restart count, container statuses, and the timestamp of collection.
- **FR-003**: The agent MUST report collected status to the backend via an internal API mechanism.
- **FR-004**: The backend MUST store only the latest status snapshot per resource — no historical data is retained.
- **FR-005**: The backend MUST expose the latest workload status through the public GraphQL API, associated with the relevant deployment or application instance.
- **FR-006**: Users MUST be able to filter workload status by cluster, environment, or specific deployment.
- **FR-007**: The polling interval MUST be configurable via an environment variable, with a default of 60 seconds.
- **FR-008**: The agent MUST only poll resources in namespaces derived from the Styrmin environment-to-namespace mapping — it must not scan arbitrary namespaces.
- **FR-009**: Status collection MUST NOT interfere with the agent's primary responsibilities (deployment orchestration and drift detection).
- **FR-010**: Stale status records MUST be cleaned up when the associated deployment or application instance is removed from Styrmin.

### Key Entities

- **WorkloadStatus**: The latest polled status snapshot for a single pod, linked to an ApplicationInstance or Deployment. Key attributes: pod name, pod phase, ready condition, restart count, container statuses, last polled timestamp.
- **ApplicationInstance** (existing): The deployed instance of an application — workload status is associated with this entity.
- **Deployment** (existing): The top-level deployment record — workload status can be queried through this entity.
- **Environment** (existing): Defines the namespace mapping used to scope which Kubernetes namespaces to poll.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Operators can query the current pod health of any Styrmin-managed deployment through the API without inspecting the cluster directly.
- **SC-002**: Status data is no older than the configured polling interval (default 60 seconds) under normal operating conditions.
- **SC-003**: Status collection adds negligible overhead — polling completes within 5 seconds for clusters with up to 500 managed pods.
- **SC-004**: 100% of Styrmin-managed pods are covered by status reporting — no gaps in visibility across managed namespaces.
- **SC-005**: Stale status records are cleaned up within one poll cycle after a deployment is removed.

## Assumptions

- The agent already has Kubernetes API access with sufficient RBAC permissions to list pods in managed namespaces (it currently creates and manages resources in those namespaces).
- The existing agent architecture (combined Prefect worker + Kopf operator in a single async event loop) can accommodate an additional periodic task without architectural changes.
- The environment-to-namespace mapping is already available to the agent through the existing configuration and context mechanisms.
- This feature covers backend and API only — frontend display of workload status will be delivered in a separate PR.
- Helm release status and CRD status are already partially tracked through the operator's existing phase and condition mechanism. This feature adds pod-level runtime visibility as a complement.

## Out of Scope

- Frontend UI for displaying workload status (separate PR).
- Historical status data or time-series tracking.
- Alerting or notification based on workload status changes.
- Helm release or CRD-level status reporting beyond what the operator already tracks.
- Metrics export (Prometheus, etc.).
