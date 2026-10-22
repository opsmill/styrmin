# ADR-087: A Restore of an Earlier Instance's Backup Makes That Instance the Active Instance

**Status**: Accepted
**Date**: 2026-10-22
**Source**: [issue #426](https://github.com/opsmill/styrmin/issues/426) and its [reproduction comment](https://github.com/opsmill/styrmin/issues/426#issuecomment-6336584915)
**Related**: [ADR-063](0063-restore-of-earlier-instance-backup.md) (amended here: its decision 1 and its consequences about the active instance and the status reporter), [ADR-085](0085-restore-target-derived-from-the-backups-deployment.md) (the server decides where an in-place restore lands)

## Context

An in-place restore of the backup of an earlier instance puts that instance's `StyrminDeployment` and `HelmRelease` back in the deployment's namespace, so the cluster runs that instance's application version and config. ADR-063 decided that Styrmin does not change the deployment's active instance, and left open what such a restore should do to the deployment.

A reproduction on develop 704c71b7 (a restore of the backup taken at 0.1.0, after an upgrade to 0.2.0) shows three effects of that decision:

- The deployment page and `styrminctl` show 0.2.0 while the application serves 0.1.0.
- A backup taken right after the restore belongs to the 0.2.0 instance and is listed at 0.2.0, while the namespace serves 0.1.0.
- The next config edit, which asks for no version change, makes Styrmin build an instance from the deployment's recorded version (0.2.0) and apply it over the restored one. The application then serves 0.2.0 again.

## Decision

1. After a completed in-place restore, `execute_restore_workflow` calls `adopt_restored_instance`. When the deployment has an active instance and the backup's instance is not that instance, it sets the deployment's application version, config, parameters and driver version from that instance, and makes that instance the active instance.
2. When the instance is bound to another driver version than the deployment, the call also rebuilds the deployment's components from the instance's context and reconciles the deployed services against that driver version, keeping the service names the deployment has.
3. The call writes nothing to the cluster, and it starts no task and no hook. The cluster already runs the instance.
4. A cross-target restore, which is an environment clone, does not call it. The counterpart deployment keeps its own instance.
5. A deployment without an active instance is not given one by a restore, as ADR-085 and the user docs describe.
6. A failure of the call is logged and does not fail the restore, because the workloads were recovered and run.

## Consequences

- The deployment page, `styrminctl`, later backups and later updates agree with what runs after the restore.
- A later instance, such as the one the restore replaced, stays in the deployment's backup history and can be restored again.
- The status reporter skips a report whose instance id is not the active instance's. The restored `StyrminDeployment` carries the earlier instance's spec, so its reports name the instance that is now active. No test covers the reports after a restore.
- The Restore dialog and `styrminctl backups restore --last` still warn before a restore of an earlier instance, and now say that the active instance changes.
- If the call fails, the deployment keeps the previous active instance and the three effects above remain until the next restore or update. The server log has the error.
- An upgrade after such a restore runs the driver's upgrade action again. An action that calls `execute_commands` fails on the Job the first upgrade left ([issue #374](https://github.com/opsmill/styrmin/issues/374)); that issue is separate.

## Alternatives Considered

- **Refuse a restore of a backup at another application version.** Not chosen: it would block recovering data from before an upgrade, which is why the history lists these backups.
- **Restore the data only, and apply the active instance's `StyrminDeployment` and `HelmRelease` after Velero.** Not chosen: the application would run a later version on the earlier data, which can need a migration the operator did not ask for.
- **Create a new instance at the backup's version and config, and apply it with a task.** Not chosen: the task would run the upgrade hook and a second reconcile on a cluster that already runs that state.
