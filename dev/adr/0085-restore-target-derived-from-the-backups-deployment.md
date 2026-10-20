# ADR-085: The Server Decides Where a Restore Lands, and the Caller Names Only the Backup

**Status**: Accepted
**Date**: 2026-10-20
**Decision-makers**: Fatih Acar
**Source**: specs/archive/031-inplace-restore-target/research.md (R-001 to R-006, R-010, R-016);
[spec 031](../../specs/archive/031-inplace-restore-target/spec.md) (Clarifications);
[issue #532](https://github.com/opsmill/styrmin/issues/532) and its
[PRD comment](https://github.com/opsmill/styrmin/issues/532#issuecomment-6267704797);
[PR #536](https://github.com/opsmill/styrmin/pull/536), review findings 3, 7 and 14
(specs/archive/031-inplace-restore-target/pr-notes.md)
**Related**: [ADR-056](0056-environment-clone-record-and-cross-target-restore.md) (cross-target
restore), [ADR-063](0063-restore-of-earlier-instance-backup.md) (restore of a backup of an earlier
instance), [ADR-073](0073-kubernetes-objects-named-and-found-by-record-id.md) (objects named after
the record's id), [ADR-086](0086-removed-graphql-arguments-explained-to-older-clients.md) (what a
client of another version is told)

## Context

Each deployment runs in its own namespace, `styrmin-<deployment id>`. An **in-place restore** puts
a backup back into the deployment it was taken of. A **cross-target restore** puts it into another
deployment, and only an environment clone starts one (ADR-056).

Before #532, the `createRestore` mutation took `targetNamespace` (required) and `targetInstanceId`
(optional) from the client. It passed both unchanged to the `create_restore` service, and the
namespace to the restore flow:

- `create_restore` found the deployment from the backup's instance, but stored the namespace and
  the instance it received without comparing them with that deployment.
- The restore flow deletes the namespace it receives, then Velero restores the backup into it.
- `styrminctl backups restore <backup of Y> --target-deployment X` therefore set deployment Y to
  `RESTORING`, deleted deployment X's namespace and restored Y's backup into it. This follows from
  the code; it was not run.
- A user with the `READ_WRITE` role could name any namespace, such as `kube-system`. With the agent
  chart's default values, the restore Job runs as `styrmin-service-account`, whose ClusterRole may
  delete any namespace (`changelog/532.security.md`).
- The Velero Restore treated a restore as cross-target when the namespaces differed, and the restore
  flow when the deployment ids differed. So an in-place restore into another namespace ended with no
  service aliases in that namespace, and reported no error.
- The environment restore and the environment clone each built `styrmin-<deployment id>`
  themselves, so three places derived a restore's namespace.

## Decision drivers

- A restore never deletes or writes a namespace other than the namespace of the deployment that
  receives it.
- One rule decides where every restore lands: an in-place restore from any client, the constituent
  restores of an environment restore, and the restores of an environment clone.
- No database migration. The `Restore` columns stay, and stay readable through GraphQL.
- No new server error code (PRD).

## Considered options

1. Keep both arguments, and refuse with a typed error a namespace or an instance that differs from
   the one the server computes.
2. Keep both arguments with a deprecation reason, and ignore them.
3. Remove both arguments. The server derives the namespace and the instance from the backup's
   deployment in one service function, and each caller reads them from the `Restore` row.
4. Compute the namespace in each caller (the mutation, the environment restore, the clone), and keep
   a `target_namespace` parameter on `create_restore`.

## Decision

We chose option 3.

- `resolve_restore_target(backup, uow, *, target_deployment_id=None)` in
  `services/backup/service.py` is the only function that decides where a restore lands. It returns
  a `RestoreTarget` with the deployment that receives the restore and that deployment's active
  instance, or `None` when it has none. Its `namespace` property is
  `get_kubernetes_reference(deployment.id)`. For an in-place restore, the deployment is the one of
  the backup's instance. For a cross-target restore, which only the environment clone starts, it is
  the counterpart named by `target_deployment_id`.
- `create_restore` takes no namespace and no instance. It records the target's namespace as
  `target_namespace` and the target's active instance as `target_instance_id` on the `Restore` row.
  The `createRestore` mutation, the environment restore and the clone flow dispatch
  `execute_restore_workflow` with `restore.target_namespace`, read from the row.
- The mutation is now `createRestore(backupId: UUID!)`. Both arguments are removed with no
  deprecation period, as #472 removed other input fields before version 1.0. The Python SDK's
  `create_restore(backup_id)` and `styrminctl backups restore` lose the matching parameters and the
  `--target-namespace` option. The `Restore` type keeps `targetNamespace` and `targetInstanceId` as
  readable fields.
- `execute_restore_workflow` keeps its `target_namespace` parameter, so the parameters of the
  Prefect deployment do not change (R-003). Before it builds or dispatches anything, the flow fails
  the restore unless the parameter and the namespace recorded on the `Restore` row are both
  `styrmin-<deployment_id>` (`_check_restore_namespace` in `workflows/templates/backup.py`). This
  covers a flow run started directly through the Prefect API, and a restore that an earlier release
  queued before the upgrade (review finding 3).
- `find_in_flight_restore(uow, deployment_id)` builds the namespace from the deployment id. It still
  finds a restore that an earlier release recorded with another namespace, through the deployment
  the restored backup was taken of (review finding 14, which replaces R-005).
- `styrminctl backups restore <backup-id>` restores the backup into the deployment it was taken of.
  `--target-deployment`, `--target-deployment-id`, `--target-instance-id` and `--environment` work
  only with `--last`, where they choose which backups the newest one is picked from. With a backup
  id, the command refuses them before it calls the server (R-010, review finding 7).

After this change, the namespaces of a restore differ exactly when its deployment ids differ, so the
Velero Restore and the restore flow agree on every restore (R-016).

Option 1 needs a new server error code, which the PRD rules out, and keeps an argument that every
caller must fill with a value the server already knows. With option 2, a client that sends another
namespace believes that the server used it. Option 4 is the design that allowed the defect: each
caller can build a namespace that differs from the one the service records.

## Consequences

- Good, because no request can make a restore delete or write the namespace of another deployment,
  or a namespace that no deployment owns.
- Good, because every in-place restore records the active instance of its deployment, including a
  restore of a backup of an earlier instance (ADR-063). Before, restores started from the Backups
  tab recorded no instance, and other clients could record an instance of another deployment.
- Good, because the Velero Restore and the restore flow agree on whether a restore is cross-target.
- Bad, because clients and server must be upgraded together. A client from before the change sends
  `targetNamespace` on every restore, `--last` included, and the new server refuses it. A server
  from before the change requires `targetNamespace`, and refuses a client from after the change.
  ADR-086 describes the messages that both sides show.
- Bad, because `styrminctl backups restore <backup-id> --target-deployment X`, the example that
  `cli/README.md` showed before the change, is refused, even when the backup belongs to X.
- Bad, because apart from an environment clone, Styrmin offers no way to restore a backup into
  another deployment until "deployment clone", a separate feature with no issue yet, ships.
- `Restore` rows from earlier releases keep the namespace and the instance they recorded, and are
  not migrated. The in-flight restore check keeps finding them while they are `PENDING` or
  `IN_PROGRESS`.
- The restore flow keeps a parameter that it now only checks.

## Confirmation

- `TestResolveRestoreTarget` in `backend/tests/unit/services/backup/test_restore.py`, including a
  backup of an earlier instance and a deployment without an active instance.
- `test_create_restore_records_the_namespace_and_active_instance_of_the_backups_deployment` and
  `test_create_restore_refuses_a_removed_target_argument` in
  `backend/tests/functional/graphql/test_create_restore.py`, the propagation test.
- `test_a_restore_into_another_namespace_fails_before_the_cluster_is_changed` in
  `backend/tests/unit/workflows/test_restore_workflow_failure_handler.py`.
- `test_backups_restore_backup_id_with_a_target_option_is_refused` and
  `test_backups_restore_target_namespace_is_an_unknown_option` in `cli/tests/test_backups.py`.
- The E2E test `test_backup_and_restore_lifecycle` (`shard_backup`, both variants) checks that the
  restore records `styrmin-<deployment id>` and the active instance, although the restored backup
  belongs to an earlier instance.
- The rule for new code is in
  [`dev/guidelines/backend/python.md`](../guidelines/backend/python.md#derive-the-namespace-that-a-flow-deletes-on-the-server-and-check-it-again-in-the-flow).

## More information

- `changelog/532.security.md` lists the affected versions: v0.1.19 to v0.1.50 with the agent chart's
  default service account, and v0.1.0 to v0.1.18, which checked no role on `createRestore`.
- Not decided: whether `styrminctl backups restore` prints the target namespace in its success line,
  so the user can view where the restore lands without `restore-get` (critique P2 of spec 031).
