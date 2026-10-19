# Data Model: An In-Place Restore Always Restores Into the Deployment Its Backup Was Taken Of

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-19

No table, column, index or migration changes. This change fixes how Styrmin fills two existing columns of `Restore`, and adds one in-memory value in the service layer.

## Restore (table `restore`, unchanged columns)

| Column | Type | Before | After |
|--------|------|--------|-------|
| `target_namespace` | `str`, not null | The value the caller passed. `createRestore` took it from the client verbatim. | Set by Styrmin: `styrmin-<id>` of the deployment that receives the data. For an in-place restore, that is the deployment of the backup's instance. For a cross-target restore, the counterpart. |
| `target_instance_id` | `UUID`, nullable | The value the caller passed, without a check. Empty for restores from the Backups tab. For a cross-target restore, the counterpart's active instance when the caller passed none. | Set by Styrmin: the active instance of the deployment that receives the data, or empty when that deployment has no active instance. |

Validation rules:

- An in-place restore's row satisfies `target_namespace == f"styrmin-{backup.instance.deployment_id}"` (FR-001).
- An in-place restore's row satisfies `target_instance_id == deployment.active_instance.id` when the deployment has an active instance (FR-004).
- For every restore created after this change, `target_namespace != f"styrmin-{source deployment id}"` exactly when the restore is cross-target. So the Velero Restore, which compares namespaces, and the restore flow, which compares deployment ids, agree.

Rows from earlier releases keep the values they recorded and are not migrated. The in-flight restore guard keeps finding such a row while it is `PENDING` or `IN_PROGRESS` ([research R-005](research.md#r-005-the-in-flight-restore-guard-does-not-change)).

The GraphQL `Restore` type keeps `targetNamespace: String!` and `targetInstanceId: UUID` (FR-005).

## RestoreTarget (new, in memory, service layer)

The result of `resolve_restore_target` in `services/backup/service.py` ([research R-001](research.md#r-001-one-service-function-decides-where-a-restore-lands)). It is a frozen dataclass and is never stored.

| Field | Type | Value |
|-------|------|-------|
| `deployment` | `DeploymentEntity` | The deployment that receives the data. |
| `namespace` | `str` | `get_kubernetes_reference(deployment.id)`, that is `styrmin-<deployment id>`. |
| `instance_id` | `UUID \| None` | `deployment.active_instance.id`, or `None`. |

Inputs and errors:

| Input | Deployment chosen | Error when it cannot be found |
|-------|-------------------|-------------------------------|
| `backup`, no `target_deployment_id` (in-place) | The deployment of `backup.instance_id` | `BackupNotFoundError` (instance missing, instance without a deployment, or deployment missing), as today |
| `backup`, `target_deployment_id` (cross-target, environment clone only) | The counterpart | `DeploymentNotFoundError`, as today |

## Terms

- **In-place restore**: defined in [`CONTEXT.md`](../../CONTEXT.md) by this change.
- **Cross-target restore**: unchanged ([ADR-056](../../dev/adr/0056-environment-clone-record-and-cross-target-restore.md)).
