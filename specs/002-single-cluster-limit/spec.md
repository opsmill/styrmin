# Feature Specification: Enforce Single-Cluster Limit

**Feature Branch**: `002-single-cluster-limit`
**Created**: 2026-03-28
**Status**: Draft
**Input**: GitHub Issue #24 — "feat: Enforce single-cluster limit in API and frontend"

## Clarifications

### Session 2026-03-28

- Q: Should the cluster name field be visible/editable, hidden, or read-only in the creation dialog? → A: Visible and editable, pre-filled with "default".

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Prevent Creating a Second Cluster via API (Priority: P1)

An administrator attempts to create a new cluster through the GraphQL API when one already exists. The system rejects the request with a clear error message indicating that only one cluster is supported.

**Why this priority**: This is the core constraint. Without backend enforcement, the single-cluster invariant cannot be guaranteed regardless of frontend changes. The API is the authoritative boundary.

**Independent Test**: Can be fully tested by sending a `createCluster` mutation when a cluster already exists and verifying the request is rejected with an appropriate error.

**Acceptance Scenarios**:

1. **Given** a cluster already exists, **When** a user sends a `createCluster` mutation, **Then** the system returns an error indicating the single-cluster limit has been reached and no new cluster is created.
2. **Given** no cluster exists, **When** a user sends a `createCluster` mutation without specifying a name, **Then** the cluster is created with the name "default".
3. **Given** no cluster exists, **When** a user sends a `createCluster` mutation with a custom name, **Then** the cluster is created with that custom name.
4. **Given** a cluster exists and is then deleted, **When** a user sends a `createCluster` mutation, **Then** a new cluster is created successfully.

---

### User Story 2 - Hide Cluster Creation in the Frontend When a Cluster Exists (Priority: P2)

An administrator visits the Settings page and sees their single cluster displayed directly, without a "New Cluster" button or multi-cluster grid layout. The interface clearly communicates that this is the one and only cluster.

**Why this priority**: Prevents user confusion by removing UI affordances that suggest multiple clusters are supported. Depends on the backend constraint (P1) being in place for correctness, but provides the primary user-facing experience improvement.

**Independent Test**: Can be tested by loading the Settings page when a cluster exists and verifying the "New Cluster" button is hidden and the layout reflects single-cluster semantics.

**Acceptance Scenarios**:

1. **Given** a cluster already exists, **When** the user navigates to the Settings page, **Then** the "New Cluster" button is hidden or disabled.
2. **Given** a cluster already exists, **When** the user views the Settings page, **Then** the cluster is displayed in a single-item layout instead of a multi-column grid.
3. **Given** no cluster exists, **When** the user navigates to the Settings page, **Then** the "New Cluster" button is visible and functional.
4. **Given** no cluster exists, **When** the user opens the cluster creation dialog, **Then** the name field is pre-filled with "default" but remains editable.

---

### User Story 3 - Delete the Only Cluster (Priority: P3)

An administrator deletes the existing cluster. The system allows this action and the Settings page reverts to showing the cluster creation option.

**Why this priority**: Ensures the deletion flow remains functional and that the UI correctly adapts when transitioning between zero and one cluster states.

**Independent Test**: Can be tested by deleting the only cluster and verifying the Settings page returns to the empty state with the creation option available.

**Acceptance Scenarios**:

1. **Given** a single cluster exists, **When** the user deletes it, **Then** the deletion succeeds and the cluster is removed.
2. **Given** the cluster was just deleted, **When** the user views the Settings page, **Then** the "New Cluster" button is visible and the page reflects an empty state.

---

### Edge Cases

- What happens when two concurrent `createCluster` requests are sent simultaneously? Only one should succeed; the other should receive the single-cluster limit error.
- What happens if the cluster creation fails mid-operation (e.g., validation passes but persistence fails)? The system should not falsely block future creation attempts.
- What happens if a user bookmarks or deep-links to the cluster creation dialog? The dialog should check the constraint and show an appropriate message if a cluster already exists.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST reject cluster creation requests when a cluster already exists, returning a clear and specific error message.
- **FR-002**: System MUST allow cluster creation when no cluster exists (preserve existing behavior).
- **FR-003**: System MUST allow deletion of the only cluster (preserve existing behavior).
- **FR-004**: The Settings page MUST hide or disable the cluster creation affordance when a cluster already exists.
- **FR-005**: The Settings page MUST display a single cluster using a direct single-item layout instead of a multi-column grid when a cluster exists.
- **FR-006**: The Settings page MUST show the cluster creation option when no cluster exists.
- **FR-007**: The system MUST handle concurrent creation requests safely, ensuring only one cluster can ever exist.
- **FR-008**: The cluster name MUST default to "default" when no name is provided. The name field in the creation dialog MUST be pre-filled with "default" but remain editable.

### Key Entities

- **Cluster**: Represents a Kubernetes cluster managed by the platform. At most one cluster may exist at any given time. Key attributes include name (defaults to "default" if not specified), connection details, and status.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users cannot create more than one cluster via the API or the UI under any circumstances, including concurrent requests.
- **SC-002**: Users see a clear, actionable error message when attempting to create a second cluster.
- **SC-003**: The Settings page accurately reflects the current cluster state — showing creation options only when no cluster exists.
- **SC-004**: Existing cluster creation and deletion workflows continue to function correctly when the system has zero clusters.

## Assumptions

- The single-cluster constraint is a platform-wide limit, not a per-user or per-tenant limit.
- The GraphQL schema does not require changes — the constraint is enforced at the service layer.
- The `deleteCluster` mutation behavior remains unchanged.
- No data migration is needed — if multiple clusters already exist in a deployment, that is out of scope for this feature (the constraint applies to new creation only).
