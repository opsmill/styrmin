# ADR-063: Restoring a Backup of an Earlier Instance Keeps the Active Instance; Clients Confirm, the Server Refuses Deleted Deployments

**Status**: Accepted
**Date**: 2026-10-10
**Source**: [issue #304](https://github.com/opsmill/styrmin/issues/304), specs/archive/011-deployment-backup-history/spec.md (Assumptions, FR-008), and the review-round commits `d81320c2`, `1d8b0c3b` and `68da40c8`
**Amended by**: [ADR-087](0087-restore-of-earlier-instance-backup-activates-that-instance.md) (a restore of an earlier instance's backup makes that instance the active instance; decision 1 and the consequences about the active instance no longer hold)
**Related**: [ADR-008](0008-deployment-soft-delete-tombstoning.md) (amended here: a deleted deployment's backups can be listed but not restored into it), [ADR-062](0062-backup-history-derived-through-instances.md) (the backup history that makes these backups visible)

## Context

ADR-062 lists the backups of every instance a deployment has had. The Backups tab and `styrminctl backups restore --last` can therefore offer a backup taken before an upgrade or a config edit, at another application version than the one the deployment runs now.

An in-place restore runs Velero with `existingResourcePolicy: update` and includes the `StyrminDeployment` and the `HelmRelease`. The spec left the effect of restoring such a backup unknown and kept restores unchanged (FR-008: no check and no confirmation). The review of the first implementation found two problems:

- An operator could restore an earlier instance's backup, at another application version, with no warning. With `restore --last`, the operator does not choose the backup.
- A deleted deployment keeps its active instance, so `styrminctl` could resolve a restore target for it. The restore would recreate its resources and move it out of `DELETED` while `deleted_at` stays set.

## Decision

1. The server does not compare the backup's application version with the deployment's. A restore of an earlier instance's backup puts that instance's `StyrminDeployment` and `HelmRelease` back in the deployment's namespace, with that instance's application version and config. Styrmin does not change the deployment's active instance. The E2E test `test_backup_and_restore_lifecycle` checks this after an upgrade from 0.1.0 to 0.2.0: the application serves 0.1.0 again, and the deployment keeps its 0.2.0 active instance.
2. The clients warn before such a restore:
   - The Restore dialog on the Backups tab shows the backup's application version and the deployment's current one. It shows a warning when the backup was taken of an earlier instance or at another application version.
   - `styrminctl backups restore --last` prints both versions and asks for confirmation in the same cases. `--yes` skips the question. Without a terminal and without `--yes`, the command refuses the restore. A restore of a backup whose id the operator passes asks no question.
3. `restore --last` skips completed backups whose expiry date has passed, because Velero deletes them, and prints how many it skipped. The Backups tab marks such a backup as expired and disables its restore.
4. `create_restore` refuses a deleted deployment as the target with `DeletedDeploymentRestoreError` (`OPERATION_DENIED`). The Backups tab disables restore on a deleted deployment, and `restore --last` refuses it before it asks for confirmation.

## Consequences

- An operator can recover data from before an upgrade or a config edit, and is told before the restore that the application version will change.
- After such a restore, the deployment's active instance and the resources in the cluster describe different instances. The deployment page and `styrminctl` keep showing the active instance's application version.
- The restored `StyrminDeployment` carries the earlier instance's spec. The status reporter skips a status report whose `instanceId` does not match the active instance ([data-models.md](../knowledge/backend/data-models.md)). What this does to the deployment's status after such a restore is not known. No test covers it.
- Scripts that call `restore --last` without a terminal fail when the newest backup belongs to an earlier instance, until they pass `--yes`.
- ADR-008 lists "restore from a backup" among the reasons a deleted deployment keeps its backups. A restore into the deleted deployment itself is now refused. Restoring a deleted deployment's backup into another deployment is not supported.
- spec.md FR-008 and the spec's Out of Scope section say restores have no check and no confirmation. This ADR supersedes those statements.

## Alternatives Considered

- **Keep restores unchanged, as FR-008 and the PRD decided.** Rejected in the review: `restore --last` can choose a backup at another application version without the operator choosing it.
- **Refuse, on the server, a restore of a backup taken at another application version.** Not chosen: it would block recovering data from before an upgrade, which is the reason to list the history. What such a restore should do is an open question in the spec, recorded for a follow-up issue.
- **Change the deployment's active instance back to the backup's instance on restore.** Not chosen: restores were out of scope for #304, and no decision was made on how a restore should change a deployment's version.
- **Rely on the CLI to refuse a deleted deployment.** Rejected: other clients can call `createRestore` directly, so the service refuses the target.
