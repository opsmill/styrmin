# Phase 1 Data Model: Delete Deployments

## Entities & changes

### Deployment (modified)

`styrmin_backend.domain.models.Deployment` and
`styrmin_backend.db.models.Deployment`.

New/modified fields:

| Field | Type | Nullable | Notes |
| --- | --- | --- | --- |
| `status` | `DeploymentState` | No | Extended enum (see below) |
| `deleted_at` | `datetime` | Yes | Set when record enters `DELETED` terminal state. Indexed for efficient filtering. |

Domain invariants:

- A deployment in `DELETED` MUST have `deleted_at` set.
- A deployment not in `DELETED` MUST have `deleted_at == None`.
- `DELETION_*` states and `DELETED` are terminal with respect to
  other mutation workflows — no non-reconciliation write is permitted
  on a deployment in these states.

### DeploymentState (modified enum)

`styrmin_backend.domain.models.DeploymentState` mirrored in
`styrmin_backend.db.models.DeploymentState`.

Existing values: `PENDING`, `DEPLOYING`, `RUNNING`, `FAILED`.

New values (appended):

- `DELETION_REQUESTED` — delete mutation accepted; DELETE_INSTANCE Task
  created; Prefect flow submitted.
- `DELETION_IN_PROGRESS` — Prefect flow is running and CRD deletion
  intent has been declared; operator is tearing down resources.
- `DELETED` — terminal tombstone. All owned resources are removed;
  `deleted_at` is set; backups either removed (REMOVE disposition)
  or retained and reassociated (RETAIN disposition).

### State transitions

```
PENDING        ──┐
DEPLOYING      ──┤
RUNNING        ──┼──► DELETION_REQUESTED ──► DELETION_IN_PROGRESS ──► DELETED
FAILED         ──┘                                                ╲
                                                                   └──► FAILED (deletion failure)
```

Rules:

- A deployment can transition to `DELETION_REQUESTED` from any
  non-terminal state that passes the concurrency guard (no running
  mutation Tasks).
- `FAILED` during deletion is represented as the deployment
  remaining in `DELETION_IN_PROGRESS` with a failed
  `DELETE_INSTANCE` Task; retry replays the workflow.
  (We deliberately do not add a separate `DELETION_FAILED` state —
  the failed Task + stuck `DELETION_IN_PROGRESS` state is the
  observable signal, matching how deploy failures are already
  modelled.)
- Transition to `DELETED` is driven by the operator's terminal
  status on the `StyrminDeployment` CRD, reported back into the
  DeploymentStatus record which the reconciliation loop consumes.

### DeploymentState Postgres enum

Migration adds the three new enum values in-place (no column
rewrite). Ordering in the enum is append-only.

### BackupDisposition (new enum)

Input enum on the GraphQL mutation and the service method.

```
BackupDisposition:
  - RETAIN   # backups survive deletion, remain associated to the tombstoned deployment
  - REMOVE   # backups are deleted as part of teardown; deployment reaches DELETED only after all backup removals succeed
```

Not persisted on its own — the chosen value is recorded as part of
the `DELETE_INSTANCE` Task's parameters so the timeline shows what
the operator chose.

### Task (unchanged schema, reused)

`styrmin_backend.db.models.Task`.

- `TaskType.DELETE_INSTANCE` already exists; no enum change.
- Task row records `prefect_flow_run_id`, `status` (PENDING → RUNNING
  → SUCCESS / FAILED), and `failure_reason`.
- Task parameters carry `backup_disposition: "RETAIN" | "REMOVE"`.

### ApplicationInstance (unchanged)

No schema change. On deletion, the active instance is cleared from
`Deployment.active_application_instance_id` (set NULL) once the
operator confirms teardown.

### Backup (behavioural change only, no schema change)

`styrmin_backend.db.models.Backup`.

- RETAIN path: on deployment transition to `DELETED`, backup rows
  remain; they stay queryable by `deployment_id` through the
  historical join (backup → instance → deployment).
- REMOVE path: the `delete_instance` flow invokes the existing
  backup-deletion service method for each backup associated with the
  deployment's instance(s) before declaring CRD deletion intent. A
  backup failing to delete causes the Task to fail; retrying the
  deletion retries the pending backup removals.

### DeploymentStatus (CRD snapshot, unchanged schema)

The existing `DeploymentStatus` record tracks the CRD's reported
phase. The reconciliation loop consumes its `phase` field to
transition `Deployment.status` from `DELETION_IN_PROGRESS` to
`DELETED` when the operator reports terminal teardown success.

### DeploymentTimelineEntry (no model change)

Timeline auto-includes `DELETE_INSTANCE` Tasks. No new entry type.

## Relationships summary

```
Deployment (tombstone)
  ├── DELETE_INSTANCE Task (in timeline)
  │     └── prefect_flow_run_id
  ├── DeploymentStatus (CRD status mirror — used by reconciliation)
  └── ApplicationInstance(s) [historical]
        └── Backup(s) [RETAIN: kept; REMOVE: deleted]
```

## Validation rules (enforced in service layer)

1. `deleteDeployment(deployment_id, backup_disposition)` MUST error
   with `DEPLOYMENT_NOT_FOUND` if no deployment matches.
2. MUST error with `DEPLOYMENT_ALREADY_DELETED` if status is any of
   `DELETION_REQUESTED`, `DELETION_IN_PROGRESS`, `DELETED`.
3. MUST error with `DEPLOYMENT_MUTATION_IN_PROGRESS` if any Task for
   this deployment is `PENDING` or `RUNNING`, including in-flight
   backup tasks.
4. `backup_disposition` MUST be provided (no defaulting).

## Migration outline

Single Alembic revision:

- Add enum values `DELETION_REQUESTED`, `DELETION_IN_PROGRESS`,
  `DELETED` to the Postgres `deploymentstate` type
  (`ALTER TYPE … ADD VALUE IF NOT EXISTS …`).
- Add column `deployments.deleted_at TIMESTAMP WITH TIME ZONE NULL`
  with an index.

Downgrade:

- Drop the `deleted_at` column.
- Postgres does not support enum value removal cleanly; downgrade is
  a no-op on the enum and documented as such in the migration's
  `downgrade()` docstring.
