# ADR-062: A Deployment's Backup History Is Read Through Its Instances

**Status**: Accepted
**Date**: 2026-10-10
**Source**: [issue #304](https://github.com/opsmill/styrmin/issues/304) and specs/archive/011-deployment-backup-history/research.md (R1, R3, R4, R5, R6), plus the review-round commit `d81320c2`
**Related**: [ADR-008](0008-deployment-soft-delete-tombstoning.md) (a deleted deployment keeps its backups), [ADR-028](0028-deployment-history-derived-from-existing-data.md) (the deployment timeline is also derived from existing rows), [ADR-031](0031-dual-identifier-resolution-service-layer.md) (the "exactly one identifier" rule)

## Context

Each backup belongs to one instance (`Backup.instance_id`). An upgrade, a config edit, a refresh and an environment config change each give the deployment a new active instance. The Backups tab, `styrminctl backups list`, `styrminctl backups restore --last` and the `backups(instanceId:)` query listed only the backups of the active instance, so any of these four operations hid every earlier backup. The backups still existed and could still be restored by id.

`ApplicationInstance.deployment_id` is a non-null foreign key, and no code path deletes an `ApplicationInstance` row. Every backup a deployment ever had is therefore two hops away from the deployment.

## Decision

1. A deployment's backup history is every backup of any of its instances, found by joining `Backup.instance_id` to `ApplicationInstance.id` and filtering on `ApplicationInstance.deployment_id` (`BackupRepository.get_by_deployment_id`). It is not stored. The backup row keeps its link to one instance.
2. The history is ordered by `created_on` descending, then `id` descending, so `restore --last` picks the same backup when two backups share a timestamp.
3. The `backups` query takes `deploymentId` next to `instanceId`. A call passes exactly one of them. `get_backups` in the backup service raises `AmbiguousIdentifierError` (`VALIDATION_ERROR`) for both or neither, before it opens the unit of work, as ADR-031 places the rule.
4. `backups(deploymentId:)` returns `[]` for an id that matches no deployment, as `backups(instanceId:)` and `backupSchedules(deploymentId:)` do. It also returns `[]` for an internal deployment, because `deployment(deploymentId:)` hides internal deployments.
5. The application version of a backup is read from its instance (`Backup.instance.applicationVersion`). The `Backup` type does not change. `Backup.instance` is resolved through the `application_instances` data loader, so a list of N backups reads their instances with one query.

## Consequences

- Backups stay listed after any operation that creates an instance, including operations added later, as long as they keep the instance's `deployment_id`.
- A deleted deployment keeps its history (ADR-008). A new deployment that reuses a deleted deployment's name starts with an empty history, because the history is listed by deployment id, not by name. A counterpart deployment created by an environment clone does not list the source deployment's backups.
- No database change and no Alembic revision were needed.
- `applicationinstance.deployment_id` has no index. Every operation that creates an instance adds a row to the joined table. An index needs an Alembic revision and was deferred.
- `backups(instanceId:)` returns the same results as before, and an existing operation that declares `$instanceId: UUID!` still validates, because a non-null variable is allowed in a nullable argument.
- The SDK's `list_backups` also checks the "exactly one id" rule and raises `ValueError` before it sends a request (commit `07eb24a3`). Research R6 and ADR-031 leave this rule to the server. Both checks now exist.

## Alternatives Considered

- **Link each backup to its deployment (`Backup.deployment_id`).** Rejected: it needs a schema change and a backfill, and the link through the instance already exists and is non-null on both hops.
- **Collect the deployment's instance ids, then list the backups of each instance.** Rejected: one query per instance, and a merge sort in Python for what one join does.
- **A `Deployment.backups` field or a separate `deploymentBackups` query.** Rejected: ADR-031 prefers one field with optional identifiers over more fields, and the PRD excluded a `Deployment.backups` field.
- **Check the two arguments in the resolver.** Rejected by ADR-031 and Constitution §III: the service layer owns the rule.
- **A flat `Backup.applicationVersion` field.** Rejected: it repeats a field that already exists one hop away and would need its own propagation test.
