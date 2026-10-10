# ADR-070: Back Up Neo4j Community by Pausing It While Velero Copies Its Data Volume

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
In the official image the JVM is the container's main process, so stopping it restarts
the container.

Decision drivers:

- A restored backup must start and contain whole transactions only.
- Neo4j must not stay paused if the backup fails partway.
- `kind: neo4j` and the `infrahub-enterprise` driver must keep working.
- The public example driver must not need an Enterprise license.

## Decision

Add a `neo4j-community` backup kind (`Neo4jCommunityBackupStrategy`):

1. The pre-backup hook reads the JVM process ID from `/var/lib/neo4j/run/neo4j.pid`, starts a
   watchdog that resumes the JVM after 3600 s (the default backup timeout), and pauses the
   JVM with `SIGSTOP`.
2. Velero copies the component's `data` volume (or the volume named in `backup.volume`)
   with file-system backup. The copy holds the files as they were at the pause, the same
   state a killed process leaves.
3. The post-backup hook stops the watchdog and resumes the JVM with `SIGCONT`. Velero 1.18
   runs post hooks only after the pod's PodVolumeBackups finish. If the watchdog already
   resumed Neo4j, the hook exits non-zero and the backup ends `PartiallyFailed`.
4. The restore has no hook. Velero restores the volume before the Neo4j container starts,
   and Neo4j replays its transaction logs on startup.

`kind: neo4j` stays the Enterprise online backup. The example `infrahub` driver moves its
`database` component to `neo4j-community`.

Tested before deciding: in Docker with `neo4j:2026.05.0` under write load, a copy of
`/data` taken while the JVM was paused started, ran recovery, kept whole transactions
only, and passed `neo4j-admin database check`.

## Alternatives considered

- **Offline dump**, the method `infrahub-backup` uses. Community stops the database only
  by stopping the JVM, which ends the container. `infrahub-backup` copies a compiled
  watchdog binary into the container to pause the JVM after shutdown; a Velero exec hook
  has only the image's shell tools. `neo4j-admin database dump` refuses a paused copy until
  recovery has run.
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
  limit is a constant (`NEO4J_MAX_PAUSE_SECONDS`), not a setting.
- Bad: the strategy depends on the official image (process ID file path, `sh`, `kill`, `sleep`)
  and on Velero running post hooks after pod volume backups finish. A Velero release that
  changes that order would produce inconsistent backups without any error.
- Bad: Velero's file-system backup skips `hostPath` volumes (for example from the
  `local-path` provisioner). On such a storage class the backup completes with a Velero
  warning and without the database, like `kind: disk`.
- Bad: the backup holds the whole volume (store files, transaction logs, server logs)
  instead of a compressed dump, so it is larger.

Confirmation: `test_strategies.py::TestNeo4jCommunityPauseScripts` runs the rendered hook
scripts against a stand-in process, and `test_infrahub_backup_and_restore_lifecycle`
backs up and restores the community Infrahub stack end to end.
