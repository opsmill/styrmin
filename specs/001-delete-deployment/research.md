# Phase 0 Research: Delete Deployments

This document records design decisions taken to resolve residual
technical unknowns before implementation. Functional open questions
from the source issue were already resolved during `/speckit.specify`
(soft-delete, operator-choice backups, asynchronous execution).

## R-001: Concurrency guard — reject vs. queue

**Decision**: Reject with a typed error
(`DeploymentMutationInProgressError`) when another workflow is
actively mutating the same deployment.

**Rationale**:
- Rejecting gives the operator an immediate, actionable signal
  ("wait for the in-flight action to finish, then retry"); queuing
  would hide the situation behind a promise that the system now has
  to keep.
- The repository layer already tracks tasks per deployment; a
  simple "any Task with status RUNNING or PENDING for this
  deployment" check is sufficient and follows the existing pattern
  used by other mutations.
- Queuing would require new durable state (a deletion-request queue),
  cancellation semantics, and replay on restart — substantial
  complexity for a user need that "try again in a minute" already
  addresses.

**Alternatives considered**:
- **Queue the delete**: Rejected above.
- **Silently wait inside the mutation**: violates Asynchronous
  execution model (FR-014) — mutation must return quickly.

**Implementation note**: The `ServiceError` subclass carries
`error_code = "DEPLOYMENT_MUTATION_IN_PROGRESS"` so frontends can
render a specific toast.

## R-002: How "deletion intent" is expressed on the `StyrminDeployment` CRD

**Decision**: The new `delete_instance` Prefect flow sets
`spec.intent = "delete"` (or equivalent field already owned by ADR-008)
on the `StyrminDeployment` CRD and does not itself touch owned
resources. The operator's existing `styrmin_deployment.py` handler
observes the intent, tears down driver CRs / HelmReleases / utility
resources / namespace, and reports progress via CRD status.

**Rationale**:
- Aligns with ADR-008: Prefect declares intent, operator owns the K8s
  lifecycle. Splitting responsibilities any other way duplicates
  teardown logic across two places.
- Re-runnable. If the operator restarts mid-teardown, it converges
  on the desired state.

**Alternatives considered**:
- **Prefect deletes resources directly**: Rejected — violates ADR-008.
- **Kubernetes-native owner references with cascade delete**: Rejected
  — ownership is split across namespaces and some objects
  (HelmRelease) manage external state that needs orderly teardown,
  not k8s garbage collection.

## R-003: Backup disposition semantics

**Decision**: The mutation takes `backupDisposition:
BackupDisposition!` with values `RETAIN` and `REMOVE`.
- `RETAIN`: backups remain in storage, reassociated to the tombstoned
  deployment (not orphaned). They remain listable and restorable
  into a new deployment.
- `REMOVE`: the `delete_instance` flow enqueues individual backup
  removals before declaring CRD deletion intent. Deletion of the
  deployment only reaches its terminal state once all backup
  removals complete (or fail, which propagates a failure).

**Rationale**:
- Matches operator mental model: "either keep or delete the
  backups" with no hidden third option.
- Tying terminal state to backup-removal completion avoids a
  half-cleaned state where the deployment shows DELETED but data
  lingers in backup storage.

**Alternatives considered**:
- **Orphan backups (no reassociation)**: Rejected — creates
  ownership ambiguity; users lose the ability to answer "what
  backups did deployment X have?" after deletion.
- **Remove backups in parallel with cluster teardown**: Rejected —
  harder to reason about failure. Serial (backups, then cluster)
  keeps error modes legible.

**Edge case**: If any backup is in `PENDING` or `IN_PROGRESS` status
at delete time, the mutation rejects under the concurrency guard
(R-001). Backup creation is a deployment-mutating workflow for
these purposes.

## R-004: Listing tombstoned deployments

**Decision**: Existing active-deployment queries exclude
`DELETED` records by default (via repository filter). Add a
`includeDeleted: Boolean = false` argument to the relevant list
query at the environment level. Deployment-by-id fetch continues to
work for tombstoned records (read-only view).

**Rationale**:
- Default-exclude keeps the active list uncluttered and avoids
  surprising regressions in existing UI flows.
- Opt-in surfacing is enough for audit — no separate "deleted
  deployments" page in scope.

**Alternatives considered**:
- **Separate `deletedDeployments` query**: Rejected — duplicates
  filtering logic; existing list query with a flag is simpler.
- **Hide tombstoned records entirely (require record ID to view)**:
  Rejected — undermines the audit motivation for soft-delete.

## R-005: Frontend post-deletion navigation

**Decision**: When the delete mutation succeeds (request accepted),
the UI optimistically transitions the page into an "in-progress
deletion" banner state. Once the deployment reaches `DELETED`
(observed via the existing 10s timeline/deployment refetch), the UI
navigates to the parent environment detail page. If the user
navigates away during teardown, no special handling is required —
the next visit to the deployment URL resolves to the tombstoned
read-only view.

**Rationale**:
- Reuses existing polling cadence — no new subscription required.
- Avoids routing the user away before they've had a chance to read
  the "deletion in progress" confirmation, which is important for
  trust on a destructive action.

## R-006: Migration strategy for new lifecycle states

**Decision**: Single Alembic migration:
1. Add `DELETION_REQUESTED`, `DELETION_IN_PROGRESS`, `DELETED` to the
   `DeploymentState` Postgres enum type.
2. Add a nullable `deployments.deleted_at` timestamp column (set when
   the deployment enters the `DELETED` terminal state; enables "sort
   by deletion time" and audit queries without scanning timeline).

**Rationale**:
- Existing deployments are unaffected (no data backfill).
- `deleted_at` is the cheapest soft-delete marker; lookups for
  tombstoned records remain a single indexed column comparison.

**Alternatives considered**:
- **Drop-and-recreate enum**: Rejected — rewrites every row, requires
  downtime on large tables.
- **Separate `deleted_deployments` table**: Rejected — breaks
  referential integrity with tasks, instances, timeline.

## R-007: Timeline events for deletion

**Decision**: Piggy-back on existing Task-driven timeline. The
`DELETE_INSTANCE` Task entry (already supported in `TaskType`)
represents "deletion requested / in progress / completed" via its
status field. No new event types added.

**Rationale**:
- Timeline is already built from Tasks + ApplicationInstances; adding
  a parallel event stream is unnecessary complexity.
- `TaskStatus` PENDING → RUNNING → SUCCESS/FAILED cleanly maps to
  the three required lifecycle transitions (FR-009).

**Failure reason propagation**: Task records store a `failure_reason`
when the Prefect flow or operator reports failure. The timeline entry
surfaces this for human diagnosis.

## Open items flagged for `/speckit.tasks`

- Confirm current presence/shape of `PrefectAction.DELETE_INSTANCE`
  registration in `workflows/catalogue.py` and decide whether the
  `delete_instance` flow module already exists or must be newly added.
- Confirm whether the operator handler
  (`operator/handlers/styrmin_deployment.py`) already observes a
  deletion intent field, or whether that contract needs to be added
  in this PR.
