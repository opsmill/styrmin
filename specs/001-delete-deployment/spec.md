# Feature Specification: Delete Deployments

**Feature Branch**: `001-delete-deployment`  
**Created**: 2026-04-20  
**Status**: Draft  
**Input**: User description: "https://github.com/opsmill/styrmin/issues/94"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Delete a deployment from the UI (Priority: P1)

An operator no longer needs a previously deployed application. From the
deployment detail page, they invoke a delete action, confirm the
destructive intent in a dialog that names the deployment and asks
whether to retain or remove its backups, and Styrmin tears down every
cluster resource it owns. The operator sees the deletion progress in
the deployment timeline and is returned to a sensible landing page
once the deployment is gone; the deployment record itself remains
viewable as a tombstone for audit.

**Why this priority**: This is the primary user-facing outcome of the
feature and the only one most users will interact with. Without it,
operators cannot retire applications without manual cluster cleanup.

**Independent Test**: Provision a test deployment, click the delete
action from its detail page, confirm in the dialog, and verify that
(a) all owned Kubernetes resources are removed from the cluster, (b)
the deployment no longer appears in the active deployments list, and
(c) the timeline reflects the full deletion lifecycle.

**Acceptance Scenarios**:

1. **Given** an active deployment, **When** the operator clicks
   "Delete", chooses whether to retain or remove backups, and
   confirms, **Then** teardown begins asynchronously, the UI
   reflects an in-progress deletion state, and the timeline records
   the deletion start event along with the backup choice.
2. **Given** a deletion is in progress, **When** teardown of all owned
   Kubernetes resources completes, **Then** the deployment is marked
   as deleted (tombstoned) in the backend, any backups are retained
   or removed per the operator's choice, and the UI navigates the
   operator to the parent environment or deployments list.
3. **Given** the confirmation dialog is open, **When** the operator
   cancels, **Then** no teardown is initiated and no state changes.
4. **Given** a deployment has been deleted, **When** an operator or
   auditor navigates to it (e.g., via a link in the timeline or a
   filter that includes deleted deployments), **Then** the record
   is viewable in a read-only tombstoned state with its full history.

---

### User Story 2 - Delete a deployment via the GraphQL API (Priority: P1)

A platform automation or SDK consumer deletes a deployment
programmatically through the GraphQL API to integrate retirement into
higher-level workflows (e.g., environment cleanup jobs, ephemeral
preview environments, GitOps orchestrators).

**Why this priority**: Styrmin is API-first. Automation and SDK
consumers must have a first-class, supported path to delete a
deployment; the UI story is built on the same API.

**Independent Test**: Using the GraphQL API (or SDK), invoke the
delete operation for a known deployment and verify the API response,
the eventual cluster state (no owned resources remain), and the
backend state transition.

**Acceptance Scenarios**:

1. **Given** a valid deployment identifier and an explicit backup
   disposition (retain or remove), **When** the delete mutation is
   called, **Then** the API returns immediately, the deployment
   transitions into a deletion lifecycle state, and teardown
   proceeds asynchronously with status observable via the
   deployment's state and timeline.
2. **Given** a non-existent or already-deleted deployment, **When**
   the delete mutation is called, **Then** the API returns a clear
   error rather than silently succeeding.
3. **Given** another workflow is actively mutating the deployment,
   **When** the delete mutation is called, **Then** the API either
   rejects the request with a clear reason or safely queues the
   deletion until the in-flight workflow completes.

---

### User Story 3 - Observe deletion lifecycle in the timeline (Priority: P2)

Operators and auditors review the deployment timeline to understand
what happened to a deployment, including when deletion was requested,
by whom, and whether teardown succeeded or failed.

**Why this priority**: Visibility into destructive operations is a
baseline expectation for a platform that manages production
infrastructure, but operators can still complete the primary delete
task without it. P1 stories deliver the capability; this story
delivers accountability.

**Independent Test**: Delete a deployment, then open its timeline and
verify that the sequence of deletion events (requested, in progress,
individual teardown milestones where relevant, completed or failed)
is visible with actor and timestamp.

**Acceptance Scenarios**:

1. **Given** a deletion has been requested, **When** an operator
   views the deployment timeline, **Then** a "deletion requested"
   event appears with the requester and timestamp.
2. **Given** teardown completes successfully, **When** the timeline
   is viewed, **Then** a "deletion completed" event is present and
   the final timeline state is terminal.
3. **Given** teardown fails partway, **When** the timeline is viewed,
   **Then** a failure event describes which teardown step failed.

---

### Edge Cases

- **Concurrent mutation**: Another workflow (deploy, upgrade,
  reconfigure) is in flight for the same deployment when deletion is
  requested. System MUST either block deletion with a clear reason or
  queue it safely; it MUST NOT interleave deletion with another
  mutation.
- **Partial teardown failure**: A subset of Kubernetes resources
  (e.g., a HelmRelease, a namespace with finalizers) fails to delete.
  Deployment MUST enter a clearly labelled failure state that an
  operator can retry, and orphaned resources MUST be surfaced rather
  than silently ignored.
- **Cluster unreachable**: The target cluster is unreachable at
  deletion time. Request MUST be accepted and teardown MUST resume
  when connectivity is restored, or MUST fail fast with a clear
  retryable error — whichever matches the decided sync/async policy
  (see clarifications).
- **Already-deleted deployment**: A delete request is issued against
  a deployment that is already deleted or in the process of deletion.
  API MUST return a clear, idempotent-friendly response rather than
  double-invoking teardown.
- **Navigation during deletion**: The operator has the deployment
  detail page open when deletion completes. UI MUST navigate away
  from the now-gone deployment rather than displaying a broken state.
- **Resources not owned by Styrmin**: Cluster resources in the
  deployment's namespace that were not created by Styrmin MUST NOT be
  removed by deletion.

## Requirements *(mandatory)*

### Functional Requirements

#### API and lifecycle

- **FR-001**: System MUST expose a GraphQL operation that deletes a
  deployment identified by its unique identifier.
- **FR-002**: System MUST extend the deployment lifecycle with states
  that represent "deletion requested", "deletion in progress", and a
  terminal state reflecting the retention policy (see FR-012).
- **FR-003**: System MUST prevent a deletion from starting while
  another workflow is actively mutating the same deployment, either
  by rejecting the request with an actionable error or by safely
  queuing it until the in-flight workflow completes.
- **FR-003a**: Conversely, System MUST reject any non-reconciliation
  mutation (`update_deployment`, `update_deployment_version`, and any
  future mutation in `services/deployment.py`) targeting a deployment
  that is already in `DELETION_REQUESTED`, `DELETION_IN_PROGRESS`, or
  `DELETED`. Without this guard a sibling mutation that calls
  `set_status(PENDING)` would silently revive a tombstone and break
  the deletion-lifecycle invariant in `data-model.md`.
- **FR-004**: System MUST be idempotent for repeated delete requests
  on the same deployment — a second request MUST NOT trigger a second
  teardown and MUST return a clear status.

#### Cluster teardown

- **FR-005**: System MUST tear down every Kubernetes resource it
  owns for the deployment, including driver-managed custom
  resources, HelmReleases, utility resources, and the deployment's
  namespace when Styrmin created it.
- **FR-006**: System MUST NOT delete Kubernetes resources that were
  not created by Styrmin as part of the deployment.
- **FR-007**: System MUST drive teardown through the existing
  reconciliation and workflow mechanisms, consistent with how deploy
  and upgrade are executed today.
- **FR-008**: System MUST surface partial teardown failures (e.g., a
  resource stuck on finalizers) as an actionable failure state the
  operator can observe and retry, rather than silently leaving the
  deployment in an inconsistent state.

#### Observability

- **FR-009**: System MUST emit timeline events for the deletion
  lifecycle, including at minimum: deletion requested (with actor),
  deletion completed, and deletion failed (with reason).
- **FR-010**: System MUST continue to make the timeline of a deleted
  deployment viewable for as long as the deployment record is
  retained under the chosen retention policy.

#### Frontend

- **FR-011**: Users MUST be able to initiate deletion from the
  deployment detail page through a clearly labelled action placed
  alongside the existing deployment actions. The action MUST open a
  confirmation dialog that (a) names the deployment, (b) states that
  the operation is irreversible, and (c) presents an explicit choice
  to retain or remove associated backups. The UI MUST reflect an
  in-progress deletion state and navigate gracefully once the
  deployment is gone; tombstoned (deleted) deployments MUST remain
  reachable for audit but MUST NOT appear in default active-deployment
  listings.

#### Retention, backups, and execution model

- **FR-012**: System MUST soft-delete deployments: once teardown
  completes, the deployment record persists in a terminal "deleted"
  state (tombstone) with its full timeline and history retained
  indefinitely so the record remains viewable and auditable. Listings
  of active deployments MUST exclude deleted records by default but
  MUST allow them to be surfaced on request (e.g., via a filter).
- **FR-013**: The delete confirmation flow MUST let the operator
  choose whether to retain or remove backups associated with the
  deployment. The choice MUST be expressed as an explicit option in
  the confirmation dialog and as a required parameter on the GraphQL
  delete operation. When "retain" is chosen, backups MUST survive
  the deployment and remain restorable/listable; when "remove" is
  chosen, backups MUST be removed as part of the teardown.
- **FR-014**: The delete operation MUST be asynchronous. The
  GraphQL mutation MUST return as soon as the request has been
  accepted and the deployment has entered the deletion lifecycle;
  teardown progress and terminal outcome MUST be observable through
  the deployment's lifecycle state and timeline events (polling or
  subscription), not through the mutation response itself.

#### Testing

- **FR-015**: Tests MUST cover the new GraphQL operation (including
  both backup-disposition paths), the teardown behaviour against a
  representative set of owned resources, the concurrency guard
  (FR-003), idempotency (FR-004), partial-failure surfacing
  (FR-008), the async lifecycle observable via state + timeline
  (FR-014), the tombstoned record's post-deletion visibility
  (FR-012), and the UI delete flow end to end.

### Key Entities *(include if feature involves data)*

- **Deployment**: The orchestration record that represents an
  application instance managed by Styrmin. Gains new lifecycle
  states for deletion and persists as a tombstone (soft-deleted)
  record after teardown, retained indefinitely for audit and
  history.
- **Deployment Timeline Event**: Chronological record of lifecycle
  transitions for a deployment. Extended with deletion-related event
  types.
- **Owned Kubernetes Resources**: The set of cluster-side objects
  (driver custom resources, HelmReleases, utility resources,
  namespace) whose lifetime is bound to the deployment and which
  must be torn down on deletion.
- **Deployment Backup**: Backup artifacts associated with a
  deployment. On deletion, the operator chooses per-deployment
  whether these are retained (and become independently
  manageable, attached to the tombstoned deployment) or removed as
  part of teardown.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of cluster resources created by Styrmin for a
  deployment are removed once a deletion reaches its terminal
  success state.
- **SC-002**: 0% of cluster resources not created by Styrmin are
  removed by a deployment deletion (verified in tests against a
  namespace containing foreign objects).
- **SC-003**: Operators can complete the full delete flow from the
  UI — locate deployment, confirm, and observe terminal state — in
  under 2 minutes of human interaction time for a deployment of
  representative size, excluding the wall-clock time of cluster
  teardown itself.
- **SC-004**: 100% of delete requests issued while another workflow
  is in flight are either rejected with a human-readable reason or
  queued; none are allowed to interleave.
- **SC-005**: 100% of deletion lifecycles produce a visible, ordered
  sequence of timeline events (requested → in progress → completed
  or failed) with actor and timestamp metadata.
- **SC-006**: Support tickets and escalations requesting manual
  cluster cleanup of retired Styrmin deployments drop to zero after
  rollout.

## Assumptions

- Deletion is an operator-initiated action; there is no automatic
  deletion of deployments based on age, inactivity, or external
  triggers in the scope of this feature.
- The existing authorization model that governs deploy and upgrade
  operations also governs delete; no new permission surface is
  introduced by this feature.
- Deletion targets a single deployment at a time; bulk delete is out
  of scope.
- The existing reconciliation and workflow mechanisms are the
  correct execution substrate for teardown, consistent with how
  deploy and upgrade already work.
- Timeline infrastructure already supports adding new event types
  without structural changes.
