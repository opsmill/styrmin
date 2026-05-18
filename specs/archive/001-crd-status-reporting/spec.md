# Feature Specification: CRD Status Reporting

**Feature Branch**: `001-crd-status-reporting`  
**Created**: 2026-04-15  
**Status**: Extracted  
**Input**: Update the reporting agent to also report the status of the StyrminDeployment CRD and use it to update the status of a Deployment  

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Deployment Status Reflects CRD Phase (Priority: P1)

As a platform operator, I want the Deployment status in the backend to accurately reflect the current phase of its StyrminDeployment CRD in Kubernetes, so that I can see whether a deployment is still being set up, is fully operational, or has failed — without inspecting the cluster directly.

Today, the Deployment status is only updated when a Prefect task completes (via the callback). Between task start and completion, there is no visibility into the CRD's progression through its phases (CreatingPrerequisites, CreatingHelmRelease, CreatingServices, Ready, Failed). This gap means operators cannot distinguish between "still deploying" and "stuck."

**Why this priority**: This is the core value proposition — closing the observability gap between task-initiated deployment and the actual CRD lifecycle.

**Independent Test**: Deploy an application, then query the Deployment status via the API while the CRD progresses through its phases. The Deployment status should update to reflect CRD phase transitions within one poll cycle.

**Acceptance Scenarios**:

1. **Given** a StyrminDeployment CRD is in phase `CreatingHelmRelease`, **When** the agent completes a poll cycle, **Then** the Deployment status in the backend reflects that the deployment is in progress (not yet ready).
2. **Given** a StyrminDeployment CRD transitions to phase `Ready`, **When** the agent completes a poll cycle, **Then** the Deployment status in the backend is updated to `running`.
3. **Given** a StyrminDeployment CRD transitions to phase `Failed`, **When** the agent completes a poll cycle, **Then** the Deployment status in the backend is updated to `failed`.
4. **Given** a StyrminDeployment CRD does not exist for a deployment (e.g., it was deleted outside of Styrmin), **When** the agent completes a poll cycle, **Then** the system handles the missing CRD gracefully without crashing or corrupting existing data.

---

### User Story 2 - View CRD Phase and Conditions via API (Priority: P1)

As a platform operator, I want to query the current CRD phase and condition details for any deployment through the API, so that I can understand exactly where in the deployment lifecycle a workload is and what sub-resources are ready.

**Why this priority**: Phase and condition data provides the diagnostic detail needed to understand deployment progress and troubleshoot issues. Without it, operators only see "pending" or "running" with no breakdown.

**Independent Test**: Deploy an application, then query the deployment's CRD status via the API. The response should include the current phase, all conditions with their statuses, and managed resource counts.

**Acceptance Scenarios**:

1. **Given** a deployment has a StyrminDeployment CRD with phase `CreatingServices` and conditions `NetworkPoliciesReady=True`, `SecretsReady=True`, `HelmReleaseReady=True`, `ServicesReady=False`, **When** a user queries the deployment's CRD status, **Then** the API returns the phase, all conditions with their status/reason/message, and managed resource counts.
2. **Given** a deployment has no CRD (e.g., freshly created, not yet submitted to K8s), **When** a user queries the deployment's CRD status, **Then** the API returns null or an empty status indicating no CRD data is available.

---

### User Story 3 - Agent Periodically Collects CRD Status (Priority: P1)

As the Styrmin platform, the existing status reporting agent must be extended to also collect StyrminDeployment CRD status alongside pod statuses, so that both data streams are reported to the backend on the same polling cadence.

**Why this priority**: This is the data collection mechanism that enables the other stories. The agent already polls pod statuses; extending it to also read CRD status is the natural integration point.

**Independent Test**: Run the agent against a cluster with StyrminDeployment CRDs and verify the backend receives CRD status updates at the configured polling interval.

**Acceptance Scenarios**:

1. **Given** the agent is running and a StyrminDeployment CRD exists, **When** the polling interval elapses, **Then** the agent reads the CRD status (phase, conditions, managed resources) and reports it to the backend.
2. **Given** a StyrminDeployment CRD is missing (namespace exists but CRD was deleted), **When** the agent polls, **Then** the agent logs a warning and skips the deployment without crashing.
3. **Given** a cluster has multiple StyrminDeployment CRDs, **When** the agent polls, **Then** CRD statuses for all deployments are reported in a single batch.

---

### Edge Cases

- What happens when the CRD exists but has no status field yet (just created)? The agent should treat it as phase "Pending" with no conditions.
- What happens when the CRD phase is "Deleting"? The system should not overwrite a deployment that is being intentionally removed. The deployment status should remain unchanged.
- What happens when the agent reports a CRD phase that contradicts the current Deployment status (e.g., CRD says "Ready" but Deployment is "failed" from a previous task)? The CRD phase should take precedence since it reflects the actual cluster state.
- What happens when the agent cannot reach the Kubernetes API during a poll cycle? Same behavior as pod status reporting — skip and retry on the next cycle.
- What happens when the CRD status has conditions with "Unknown" status? These should be stored and exposed as-is for diagnostic purposes.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The agent MUST read the StyrminDeployment CRD status (phase, conditions, managed resources) for each deployment during each poll cycle.
- **FR-002**: The agent MUST report CRD status to the backend alongside pod statuses, using the same polling cadence and transport mechanism.
- **FR-003**: The backend MUST store the latest CRD status snapshot per deployment — phase, conditions, managed resource counts, and the timestamp of the last observation.
- **FR-004**: The backend MUST update the Deployment's status based on the reported CRD phase using this mapping: CRD phases `Pending`, `CreatingPrerequisites`, `CreatingHelmRelease`, `CreatingServices` map to Deployment status `pending`; CRD phase `Ready` maps to `running`; CRD phase `Failed` maps to `failed`. CRD phase `Deleting` does not change the Deployment status.
- **FR-005**: The backend MUST expose the latest CRD status through the public API, associated with the relevant Deployment.
- **FR-006**: CRD status collection MUST NOT interfere with pod status collection — both should be reported in the same poll cycle.
- **FR-007**: When a StyrminDeployment CRD is missing for a deployment, the agent MUST skip CRD status collection for that deployment without error.
- **FR-008**: When a CRD has no status field yet, the system MUST treat it as phase "Pending" with empty conditions.
- **FR-009**: Stale CRD status records MUST be cleaned up when the associated Deployment is removed from Styrmin.

### Key Entities

- **DeploymentCrdStatus** (new): The latest CRD status snapshot for a deployment. Key attributes: deployment_id, phase, conditions (list of condition objects), managed_resource_counts, last_polled_at.
- **Deployment** (existing, modified): Status field now also updated based on CRD phase reports, not just task callbacks. CRD status queryable as a nested field.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Operators can see the current CRD phase and conditions of any Styrmin-managed deployment through the API without inspecting the cluster.
- **SC-002**: Deployment status in the backend reflects the actual CRD phase within one polling interval (default 60 seconds) under normal conditions.
- **SC-003**: The additional CRD status collection adds less than 2 seconds of overhead per poll cycle for clusters with up to 100 deployments.
- **SC-004**: 100% of StyrminDeployment CRDs are covered by status reporting — no gaps in visibility across managed deployments.

## Assumptions

- The agent already has RBAC permissions to read StyrminDeployment CRDs (it creates and manages them).
- The existing status reporter polling loop and backend communication mechanism (from the agent-status-reporting feature) are available and functional.
- The CRD status structure is stable and follows the schema defined in the operator's CRD status module.
- Updating Deployment status based on CRD phase is additive — it does not remove the existing task callback mechanism. Both can update the Deployment status; the most recent update wins.
- This feature is backend-only — frontend display of CRD conditions will be handled separately.

## Out of Scope

- Frontend UI for displaying CRD status details.
- Modifying the operator's CRD status-setting logic.
- Historical CRD status tracking or time-series data.
- Alerting based on CRD phase transitions.
- Changes to the task callback mechanism.
