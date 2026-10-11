# ADR-065: Back Up Neo4j Community by Pausing It While Velero Copies Its Data Volume

**Status**: Accepted
**Date**: 2026-10-08
**Source**: [issue #263](https://github.com/opsmill/styrmin/issues/263)

## Context

The `neo4j` backup kind runs `neo4j-admin database backup` in its pre-backup hook, and
`STOP DATABASE` plus `neo4j-admin database restore` in its post-restore hook. Both are
Neo4j Enterprise features. The Infrahub chart deploys Neo4j Community (`neo4j:2026.05.0`
with chart 4.33.2), so every backup of the example `infrahub` driver ended
`PartiallyFailed`, and its restore hook fails with `'STOP DATABASE' is not supported in
community edition`. The `infrahub-enterprise` driver runs the Enterprise image, and its
backup E2E passes with `kind: neo4j`.

Neo4j Community has no online backup. Its offline tool, `neo4j-admin database dump`,
needs the database stopped, and Community cannot stop a database while the server runs.
In the official image, PID 1 is `tini -g`, which runs the JVM as its child and exits when
the JVM exits, so stopping the JVM restarts the container.

Decision drivers:

- A restored backup must start and contain whole transactions only.
- Neo4j must not stay paused if the backup fails partway.
- `kind: neo4j` and the `infrahub-enterprise` driver must keep working.
- The public example driver must not need an Enterprise license.

## Decision

Add a `neo4j-community` backup kind (`Neo4jCommunityBackupStrategy`):

1. The pre-backup hook reads the JVM process ID from `/var/lib/neo4j/run/neo4j.pid` and
   records it with the process start time, starts a watchdog that resumes the JVM after
   the backup timeout (`DEFAULT_BACKUP_TIMEOUT`, 3600 s), and pauses the JVM with `SIGSTOP`.
   `SIGSTOP` is the hook's last command, so no later command can fail the hook while Neo4j
   is paused.
2. Velero copies the component's `data` volume (or the volume named in `backup.volume`)
   with file-system backup. The copy holds the files as they were at the pause, the same
   state a killed process leaves.
3. The post-backup hook stops the watchdog and resumes the JVM with `SIGCONT`. Velero 1.18
   runs post hooks only after the pod's PodVolumeBackups finish. The hook exits non-zero,
   and the backup ends `PartiallyFailed`, unless the recorded process was still paused
   when the hook ran and `SIGCONT` reached it. The process is no longer paused when the
   watchdog resumed it, when Neo4j restarted (a restart also wipes the record in `/tmp`),
   or when another backup of the same pod resumed it first.
4. The restore has no hook. Velero restores the volume before the Neo4j container starts,
   and Neo4j replays its transaction logs on startup.
5. After the backup, Styrmin fails it when no PodVolumeBackup exists for the data volume,
   and fails the component's step when Velero reports failed hooks, since only the
   post-backup hook can fail once the volume is backed up. The hook's own message is in
   Velero's backup log only, so the step gives the `velero backup logs` command.

`kind: neo4j` stays the Enterprise online backup. The example `infrahub` driver moves its
`database` component to `neo4j-community`.

Tested before deciding: in Docker with `neo4j:2026.05.0` under write load, a copy of
`/data` taken while the JVM was paused started, ran recovery, kept whole transactions
only, and passed `neo4j-admin database check`.

## Alternatives considered

- **Offline dump**, the method `infrahub-backup` uses. It sends `SIGTERM` to the JVM. A
  watchdog binary that it copies into the container sends `SIGSTOP` to the JVM when the JVM
  deletes its PID file during shutdown, so the container keeps running while
  `neo4j-admin database dump` reads the stopped database. `SIGCONT` then lets the JVM exit,
  and the container restarts. A Velero exec hook has only the image's shell tools, and
  `neo4j-admin database dump` refuses a paused, running copy until recovery has run. The
  two methods produce different backups: `infrahub-backup` restores its dump with
  `neo4j-admin database load`, and Styrmin restores the volume through Velero.
- **Copy `/data` into the `backup` emptyDir while paused.** The pause would last only for a
  local copy. Restore would have to replace the store under a running server: pause the
  JVM, replace the files, and kill the container from the hook.
- **Detect the edition at run time under `kind: neo4j`.** Enterprise backs up the `backup`
  volume and Community the `data` volume. The `backup.velero.io/backup-volumes` annotation
  is set when the deployment is rendered, so the driver has to choose.
- **Switch the example driver to the Enterprise image.** No platform change, but every real
  deployment would need an Enterprise license.

## Consequences

- Good: Neo4j Community deployments can be backed up and restored. The restore needs no
  hook and no container restart.
- Good: `kind: neo4j` and the `infrahub-enterprise` driver are unchanged.
- Bad: Neo4j answers no queries while Velero uploads the whole data volume, so Infrahub
  requests wait or time out for the length of the backup. The pause grows with the volume
  size and the upload speed to the backup storage location.
- Bad: a backup that takes longer than 3600 s is resumed by the watchdog and fails. The
  limit is the backup timeout (`NEO4J_MAX_PAUSE_SECONDS` is `DEFAULT_BACKUP_TIMEOUT`), not
  a setting. When Velero skips the post hook, for example because Velero restarted, Neo4j
  stays paused until the watchdog fires. The remedy for longer backups is Neo4j Enterprise
  with `kind: neo4j`.
- Bad: two backups that overlap on the same pod share one pause. The first post hook
  resumes Neo4j, so the backup that ends last fails.
- Bad: the strategy depends on the official image (process ID file path, `sh`, `kill`, `sleep`)
  and on Velero running post hooks after pod volume backups finish. A Velero release that
  changes that order would produce inconsistent backups without any error.
- Bad: Velero's file-system backup skips `hostPath` volumes (for example from the
  `local-path` provisioner) with only a warning. On such a storage class the backup fails,
  because Styrmin finds no PodVolumeBackup for the data volume.
- Bad: the backup holds the whole volume (store files, transaction logs, server logs)
  instead of a compressed dump, so it is larger.

Confirmation: `test_strategies.py::TestNeo4jCommunityPauseScripts` runs the rendered hook
scripts against a stand-in process, and `test_infrahub_backup_and_restore_lifecycle`
backs up and restores the community Infrahub stack end to end and checks that Velero ran
every hook without a failure.
