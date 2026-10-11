# Backup & Restore

## Overview

The backup/restore system provides component-level backup and restore operations for deployed application instances, built on top of Velero for Kubernetes-native volume snapshots. It supports multiple backup strategies per component and uses a two-worker architecture to separate orchestration from Kubernetes operations.

A coordinated **environment** scope sits on top of that per-instance machinery without modifying it — see [Environment-Level Backup & Restore](#environment-level-backup--restore).

```text
GraphQL Mutation (createBackup / createRestore)
        |
        v
  Service Layer (services/backup/)
        |
        v
  Prefect Action (EXECUTE_BACKUP / EXECUTE_RESTORE)
        |
        v
  INTERNAL Flow (execute_backup_workflow / execute_restore_workflow)
        |   - Builds Velero CRD specs
        |   - Dispatches to USER flow
        v
  USER Flow (execute_velero_backup / execute_velero_restore)
        |   - Creates Velero CRDs in K8s
        |   - Polls for completion
        |   - Records steps through recordStep (action token)
        v
  Prefect Variable (cross-worker result channel)
        |
        v
  INTERNAL Flow updates DB status
```

## Backup Strategies

Each component in a driver can define a backup kind. The strategy pattern maps kinds to implementations:

| Kind | Strategy | Mechanism |
|------|----------|-----------|
| `disk` | `DiskSnapshotStrategy` | Direct Velero volume snapshot |
| `postgres` | `PostgresBackupStrategy` | `pg_dump` to extra volume, then Velero snapshot |
| `mariadb` | `MariadbBackupStrategy` | `mariadb-dump` to extra volume, then Velero snapshot |
| `mongodb` | `MongodbBackupStrategy` | `mongodump` to extra volume, then Velero snapshot |
| `neo4j` | `Neo4jBackupStrategy` | `neo4j-admin dump` to extra volume, then Velero snapshot |
| `action` | `ActionBackupStrategy` | Custom driver action via Prefect (no Velero hooks) |

### Strategy Interface

All strategies implement three methods:

```python
class BackupStrategy(ABC):
    def get_hooks(self, namespace, component_name, config) -> list[VeleroBackupHook]: ...
    def get_restore_hooks(self, namespace, component_name, config) -> list[VeleroRestoreHook]: ...
    def get_backup_volumes(self, component_name, config) -> list[str]: ...
```

- **Disk:** No hooks needed, extracts volume names from `volume`/`volumes` config fields
- **Postgres / Mariadb / Mongodb / Neo4j:** Pre-backup hooks run a dump command (e.g. `pg_dump`, `mariadb-dump`, `mongodump`, `neo4j-admin dump`) into an extra volume mounted at `backup_mount_path` (default `/backup`); post-restore hooks run the corresponding restore command. Default backup volume is `"backup"`.
- **Action:** No hooks or volumes — backup is handled entirely by the driver's Prefect action

### Hook timeouts: `timeout` vs `execTimeout`

Backup and restore hooks do **not** share a field name for their timeout, and getting it wrong fails silently:

| Hook | Velero field | Dataclass attribute |
|------|--------------|---------------------|
| `VeleroBackupHookExec` | `timeout` | `timeout` |
| `VeleroRestoreHookExec` | `execTimeout` | `exec_timeout` |

The Restore CRD has a structural schema, so an unknown `timeout` key on a restore hook is pruned by the API server without an error and velero applies its own **30 s** default — a hook declaring `600s` shows up in the velero log as `hookTimeout="{30s}"` and any longer-running restore command is killed mid-flight. `backend/tests/unit/services/backup/test_strategies.py::test_restore_hooks_never_render_a_bare_timeout` guards every strategy against the regression.

`waitTimeout` is not modelled: unset means velero waits indefinitely for the container, and the hooks poll for readiness themselves.

### The postgres restore hook is fenced

A restore deletes and recreates the target namespace, and `build_velero_restore` sets `restorePVs: false` while `PostgresBackupStrategy.get_backup_volumes` only captures the `backup` volume — never PGDATA. Postgres therefore comes up on an **empty** data volume and initdb builds an empty database. The application that owns that database is restored into the same namespace at the same time, connects as soon as postgres is reachable, and starts running its own schema migrations against that empty database — concurrently with the post-restore `pg_restore`.

Interleaving the two corrupts the schema. The observed signature (`hooks.py`, Prefect's database):

```text
pg_restore: error: ... cannot drop constraint pk_work_queue ... because other objects depend on it
pg_restore: error: ... relation "work_pool" already exists
pg_restore: error: ... column "status" of relation "work_pool" does not exist
```

The last one is diagnostic: the dump has the column, the live table does not, because the table had just been recreated by an *older* Alembic revision. The window is small, so this surfaces as a rare `PartiallyFailed` restore rather than a consistent one — but the database is left neither the backup's schema nor the application's.

`postgres_restore_hooks()` closes it with three things:

1. **A readiness poll** instead of `sleep 5`. Velero's `waitForReady` only waits for the container's readiness probe, which bitnami satisfies while initdb is still creating the role and the database — the old `FATAL: role "..." does not exist` failure.
2. **A fence.** A background loop terminates every backend on the target database whose `application_name` is not the hook's own `PGAPPNAME` (`styrmin-restore`), so `pg_restore` is the only writer for the duration. A NULL `application_name` counts as a rival: `pg_stat_activity` hides that column for backends owned by another role. The statement is restricted with `pg_has_role(usesysid, 'MEMBER')` to backends the hook's role may signal — `pg_terminate_backend` raises an error on any other backend, and that error aborts the whole statement, so a single foreign-role connection (an autovacuum worker, a metrics exporter connecting as `postgres`) would otherwise disable the fence silently. No superuser is needed as long as the application connects as the same role the hook uses (`POSTGRES_USER`); database ownership by itself grants no right to signal other roles' backends, and those are left alone. The loop runs `while kill -0 "$$"`, i.e. only as long as the hook shell is alive, and is also killed by a `trap` on `EXIT INT TERM`. The liveness check matters: a shell killed by a signal (SIGPIPE once velero has closed the exec stream on `execTimeout`) runs no trap, and an orphaned fence would keep the database unusable until the pod restarts. A connection limit was rejected as the alternative: the application's connection pool simply takes the slot and holds it.
3. **`--single-transaction`.** Each attempt is all-or-nothing, so losing a race rolls back cleanly instead of leaving a half-restored schema, which in turn makes the bounded retry loop safe.

`--clean --if-exists` stays rather than `DROP SCHEMA public CASCADE`: on PostgreSQL 14 and older schema `public` is owned by `postgres`, and the hook runs as the database owner, not a superuser. PostgreSQL 15 hands `public` to `pg_database_owner`, which would allow the drop, but `--clean` works on every version.

The same race applies in principle to the mariadb, mongodb and neo4j hooks; only postgres has a documented occurrence and only postgres is fenced today.

### The mariadb and mongodb restore hooks retry the load

These hooks used to run `sleep 5` and then load the dump once, which failed as a `PartiallyFailed` restore whenever the database took longer to initialise (#412). The bitnami images initialise an empty data volume on a temporary server, create the users and the database on it, stop it, and start the final server. The chart's readiness probes (`mariadb-admin ping`, and an unauthenticated `db.hello()` for mongodb) pass against that temporary server, so velero's `waitForReady` runs the hook before the final server is up. Depending on the moment, the load then fails with:

- `ERROR 1045` or `ERROR 1044` (mariadb) or `(AuthenticationFailed)` (mongodb): the temporary server does not have the user or the database yet.
- `ERROR 2002 ... Can't connect to local server through socket`: the temporary server has stopped and the final server has not started.

`mariadb_restore_hooks()` and `mongodb_restore_hooks()` now rerun the load every 2 s until it succeeds, and fail after `_DB_LOAD_DEADLINE_SECONDS` (120 s). A rerun is safe because `mariadb-dump` writes `DROP TABLE IF EXISTS` before each table and `mongorestore --drop` drops each collection before restoring it. A load that completes on the temporary server is kept, because the final server starts on the same data directory. Velero's log for a successful restore can therefore show failed attempts before the one that succeeded.

`backend/tests/unit/services/backup/test_strategies.py::TestRetriedDatabaseLoad` runs the rendered scripts with fake clients. The race itself was reproduced against the bitnami images with the container limited to 0.08 CPU: the old hooks failed 3 of 3 runs (mariadb) and 1 of 3 runs (mongodb) with the errors from CI, and the new hooks restored the data in 5 of 5 runs each.

The fence is covered at unit level only: `backend/tests/unit/services/backup/test_strategies.py` asserts the rendered script's fence, role filter, liveness bound, atomicity and retry. There is deliberately no E2E for the race — the one scenario with a live writer against a `kind: postgres` component is the enterprise backup/restore lifecycle, and probing Prefect's schema from it was judged too heavy for what it proved.

## Data Models

### Status Enums

Both backups and restores follow the same lifecycle: `PENDING` -> `IN_PROGRESS` -> `COMPLETED` or `FAILED`

### Backup

```python
class Backup(StyrminModel, table=True):
    name: str                     # Unique backup name
    status: BackupStatus          # PENDING, IN_PROGRESS, COMPLETED, FAILED
    instance_id: UUID             # FK to ApplicationInstance
    schedule_id: UUID | None      # FK to BackupSchedule (for scheduled backups)
    environment_backup_id: UUID | None  # FK to EnvironmentBackup (constituent membership)
    started_at: datetime | None
    completed_at: datetime | None
    size_bytes: int | None
    error_message: str | None
    component_statuses: dict      # JSON: {component_name: {status, size_bytes, error}}
    metadata_: dict               # JSON: operation metadata (see below)
    restores: list[Restore]       # One-to-many relationship
```

`size_bytes` is the sum of `status.progress.totalBytes` over the backup's
`Completed` PodVolumeBackups, listed with `VeleroClient.list_pod_volume_backups`
(the same listing the component steps use). Velero's
Backup status has no byte size: `backupItemOperationsCompleted` is a count of
async plugin operations and must not be stored here (#136). The value is the
logical volume data before kopia deduplication and compression, and excludes
the resource manifests. It stays `NULL` when no PodVolumeBackup completed,
when the phase is not `Completed`, or when listing them fails; a listing
failure is logged and never fails the backup. Listing needs `get`/`list` on
`velero.io/podvolumebackups`, granted in both Helm charts. Sizes pass 2 GiB, so
the column is `BIGINT` and GraphQL exposes it as the `BigInt` scalar
(`api/scalars.py`); every `strawberry.Schema` built from the app's `Query` must
pass `StrawberryConfig(scalar_map=SCALAR_MAP)`.

`metadata_` is a plain `JSON` column carrying per-operation metadata:

| Key | Written by | Meaning |
|-----|-----------|---------|
| `timeout` | `create_backup` | Velero polling timeout in seconds (default 3600). |
| `ttl` | `execute_backup_workflow`, before the Velero object is built | The resolved retention applied to this backup, e.g. `"2160h"`. |
| `ttl_source` | same | Which scope supplied it — `deployment`, `environment`, `cluster`, or `default`. |
| `expires_at` | `execute_backup_workflow`, on a terminal Velero phase | Velero's own `status.expiration` ISO timestamp. Absent when Velero reported none. |

Because the column is plain `JSON` with no change tracking, writes MUST
**reassign** the dict (`backup.metadata_ = {**(backup.metadata_ or {}), **updates}`)
— in-place mutation is not flushed. `update_backup_status(metadata_updates=...)`
is the only supported writer and merges this way, so pre-existing keys survive.

### Restore

```python
class Restore(StyrminModel, table=True):
    name: str                     # Unique restore name
    status: RestoreStatus
    backup_id: UUID               # FK to Backup
    target_namespace: str         # K8s namespace to restore into
    target_instance_id: UUID | None  # Optional target instance
    environment_restore_id: UUID | None  # FK to EnvironmentRestore (constituent membership)
    component_statuses: dict      # JSON: component-level restore status
    metadata_: dict
```

### BackupSchedule

```python
class BackupSchedule(StyrminModel, table=True):
    name: str
    enabled: bool
    cron_expression: str          # Cron schedule
    deployment_id: UUID           # FK to Deployment
    retention_count: int = 10     # Max backups to retain
    last_backup_at: datetime | None
    next_backup_at: datetime | None
    prefect_deployment_id: UUID | None  # Prefect deployment for scheduled execution
```

## Service Functions

### Backup Operations (`services/backup/service.py`)

| Function | Description |
|----------|-------------|
| `resolve_backup_target(instance_id, uow)` | Walk instance → deployment (namespace) and instance → driver version → backup-enabled component configs, returning a `BackupTarget(deployment_id, target_namespace, component_configs)`. Best-effort: any failure degrades to `BackupTarget(None, "", None)` — a hookless backup — and logs a warning. Shared by the `createBackup` mutation and the environment fan-out so both build identical constituents (FR-014) |
| `create_backup(instance_id, uow, ...)` | Create on-demand backup with component configs. `environment_backup_id` links it as an environment-backup constituent. The row id is generated up front so the unique auto-generated name is final before the `INSERT` |
| `get_backup(backup_id, uow)` | Get backup by ID |
| `get_backups(uow, *, deployment_id=None, instance_id=None, status=None)` | List backups, newest first (`created_on` descending, then `id` descending, so `restore --last` picks the same backup on a tie). Exactly one of `deployment_id` or `instance_id` is required; both or neither raise `AmbiguousIdentifierError` (`VALIDATION_ERROR`) before the unit of work opens. `deployment_id` returns the deployment's backup history: the backups of every instance the deployment has had, found by joining `Backup.instance_id` to `ApplicationInstance.deployment_id` (`BackupRepository.get_by_deployment_id`, which also joins `Deployment` and lists nothing for an internal deployment, as `deployment(deploymentId:)` hides it; an unknown id lists nothing), so backups stay listed after an upgrade, a config edit, a refresh (`refresh_deployment`, which no code path calls today) or an environment config change gives the deployment a new active instance, and after the deployment is deleted. `instance_id` returns that one instance's backups (`get_by_instance_id`). See [issue #304](https://github.com/opsmill/styrmin/issues/304) and [ADR-062](../../adr/0062-backup-history-derived-through-instances.md). `applicationinstance.deployment_id`, which the history query filters on, has no index; adding one needs an Alembic revision and was deferred. <!-- Extracted from specs/011-deployment-backup-history on 2026-10-10 --> |
| `delete_backup(backup_id, uow)` | Delete backup (cascades to restores) |
| `update_backup_status(backup_id, status, uow, ...)` | Update overall backup status; `metadata_updates` merges keys into `Backup.metadata_` by reassignment |
| `update_backup_component_status(backup_id, component_name, ...)` | Update component status, derives overall status |

### Restore Operations (`services/backup/service.py`)

| Function | Description |
|----------|-------------|
| `create_restore(backup_id, target_namespace, uow, ...)` | Create restore from backup; resolves the target deployment, rejects internal deployments, tombstoned deployments (`DeletedDeploymentRestoreError`, `OPERATION_DENIED`, #304) and concurrent restores, flips `deployment.status` to `RESTORING`. Returns `(Restore, deployment_id)`. `environment_restore_id` links it as an environment-restore constituent; the row id is generated up front for the same unique-name reason as `create_backup`. |
| `get_restore(restore_id, uow)` | Get restore by ID |
| `get_restores(backup_id, uow, status)` | List restores for backup |
| `update_restore_status(restore_id, status, uow, ...)` | Update restore status |
| `update_restore_component_status(restore_id, component_name, ...)` | Update component restore status |

### Environment Operations (`services/backup/environment.py`)

Detail in [Environment-Level Backup & Restore](#environment-level-backup--restore).

| Function | Description |
|----------|-------------|
| `create_environment_backup(environment_id, uow, name, prefect_manager)` | Capture config + declared state and create every constituent backup in **one transaction**, then dispatch one `EXECUTE_BACKUP` per committed constituent |
| `restore_environment_backup(environment_backup_id, uow, prefect_manager)` | Revert captured config and create every constituent restore in **one transaction** (skips classified up front), then run the exclusion-aware config fan-out and dispatch `EXECUTE_RESTORE` per constituent |
| `get_environment_backup` / `get_environment_backups(environment_id, ...)` | Read one snapshot / an environment's snapshots (newest first) |
| `get_environment_restore` / `get_environment_restores(environment_backup_id, ...)` | Read one restore / a snapshot's restores (newest first) |
| `delete_environment_backup(environment_backup_id, uow)` | Cascade-delete constituents, their restores, the snapshot's environment restores, and the parent. No status guard |
| `delete_environment_backups_for_environment(environment_id, uow)` | Environment-deletion arm of the same cascade; called by `delete_environment` |
| `derive_environment_operation_status(children_statuses, error_count)` | Pure derivation of both parents' status; never stored |
| `is_eligible_for_environment_backup(deployment)` | Non-tombstoned, non-internal, has an active instance |

### Scheduler (`services/backup/scheduler.py`)

| Function | Description |
|----------|-------------|
| `create_backup_schedule(deployment_id, name, cron_expression, uow, ...)` | Create scheduled backup |
| `get_backup_schedule(schedule_id, uow)` | Get schedule by ID |
| `get_backup_schedules(deployment_id, uow)` | List schedules for deployment |
| `update_backup_schedule(schedule_id, uow, ...)` | Update schedule configuration |
| `delete_backup_schedule(schedule_id, uow)` | Delete schedule |

## Retention TTL (`services/backup/ttl.py`)

Every Velero Backup carries a `spec.ttl`. This module is the single home of the
retention rule — the default literal, its validation, and its scope resolution:

| Symbol | Purpose |
|--------|---------|
| `DEFAULT_BACKUP_TTL` | The built-in `"720h"`. The only place the literal is spelled out; pinned by `backend/tests/unit/services/test_backup_ttl_resolution.py`. |
| `BACKUP_TTL_PATTERN` | `^(\d+(\.\d+)?(h\|m\|s))+$` — strictly positive Go duration, `h`/`m`/`s` units only, case-sensitive. |
| `validate_backup_ttl(value)` | Returns the value unchanged or raises `ValueError`. Also rejects all-zero durations (`0h`, `0h0m0s`) that match the pattern but express no retention. |
| `resolve_backup_ttl(deployment_config, environment_config, cluster_config)` | Pure function returning `(ttl, source_scope)`. |
| `BackupTtlSource` | `Literal["deployment", "environment", "cluster", "default"]`. |

### Validation surface

`BaseConfigSection.backup_ttl: str | None` (`context/models/config.py`) carries a
field validator delegating to `validate_backup_ttl`, so all five config input
surfaces — cluster create, environment create/update, deploy, deployment update
— reject a malformed value through the existing `validate_*_config` →
`Invalid*ContextError` path before anything is written. The validator is imported
lazily inside the field validator so the config models keep no module-load-time
dependency on the services layer.

The frontend keeps a deliberate port of the same rule in
`frontend/src/lib/backup-ttl.ts` (`validateBackupTtl`, plus the `720h` default
and the hour ceiling) so the environment Configuration tab can reject a
malformed value without a round-trip. It is a UX affordance, not a second
boundary — this module stays authoritative — but a change to the rule here must
be mirrored there, and `frontend/src/lib/backup-ttl.test.ts` repeats the
accept/reject matrix to make a divergence visible.

### Resolution

Precedence is **deepest-wins**: deployment → environment → cluster → built-in
default. A scope contributes only when its persisted config dict carries a
non-null `backup_ttl`; a scope that omits the key is transparent and resolution
falls through.

`execute_backup_workflow` calls it **outside** the `try/except` that makes BSL
resolution best-effort — that block swallows every exception, and retention must
never be quietly reduced to the default by a failure it hid. On a failed config
read all three scopes are `None`, resolution yields the built-in default, and an
extra WARNING records that the configured policy was invisible to this backup.
The successful path logs at INFO:

```text
resolved backup TTL 2160h from environment scope for backup <uuid>
```

### Plumbing

1. `execute_backup_workflow` resolves the TTL, records `{"ttl", "ttl_source"}`
   via `update_backup_status(metadata_updates=...)` **before** the Velero object
   is built (so the audit trail survives a later failure), then passes `ttl=` to
   `build_velero_backup`.
2. `execute_velero_backup_flow` includes Velero's `status.expiration` in the
   Prefect Variable result payload alongside the phase.
3. Back in `execute_backup_workflow`, `status.expiration` is recorded as
   `expires_at` on **both** terminal branches — a `PartiallyFailed` backup is
   stored and does expire, and the workflow folds that phase into the FAILED
   branch. A `Failed` backup carries no expiration, so the key is simply absent.

## Two-Worker Architecture

Backup workflows use a two-worker model:

| Worker | Pool | Responsibilities |
|--------|------|------------------|
| INTERNAL | `styrmin-work-pool` | DB operations, CRD building, status updates, flow dispatch |
| USER | `user-work-pool` (K8s) | Velero CRD creation/polling, in-cluster K8s operations |

Results are passed between workers via **Prefect Variables** (a cross-worker communication channel).

### Workflow Flows (`workflows/templates/backup.py`)

**Backup:**

1. `execute_backup_workflow` (INTERNAL) — marks backup IN_PROGRESS, resolves the retention TTL and records it (see [Retention TTL](#retention-ttl-servicesbackupttlpy)), builds Velero CRD, creates an action token, dispatches to USER flow with the token and `STYRMIN_BACKUP_ID`, updates status, `size_bytes` and `expires_at` from result
2. `execute_velero_backup_flow` (USER) — creates Velero Backup CRD, polls completion, records one step per component, sums the PodVolumeBackup bytes on `Completed`, stores result (phase + `status.expiration` + `volume_bytes`) in Prefect Variable

**Restore:**

1. `execute_restore_workflow` (INTERNAL) — marks restore IN_PROGRESS, builds Velero CRD, creates an action token, dispatches to USER flow with the token and `STYRMIN_RESTORE_ID`, transitions `deployment.status` between `RESTORING` and `RUNNING` / `FAILED` based on the result.
2. `execute_velero_restore_flow` (USER) — deletes target namespace first, creates Velero Restore CRD, polls completion, then runs the post-velero recovery (see [Restore Lifecycle](#restore-lifecycle) below), records the three restore steps, stores result in Prefect Variable.

### Backup and restore steps

<!-- Extracted from specs/019-task-steps on 2026-10-06 -->

Backups and restores record steps, like tasks, so users can view each stage and why it failed on the deployment page (`Backup.steps`, `Restore.steps`). The work runs in the USER flows, which have no database access, so they record steps through the `recordStep` mutation with the flow step reporter (`agent/steps/reporter.py`). See [ADR-060](../../adr/0060-steps-and-derived-task-result.md) and [orchestration-flows.md](orchestration-flows.md#steps-recorded-by-the-flows).

**Action token.** `execute_backup_workflow` and `execute_restore_workflow` create one action token for the built-in `styrmin-actions` user per backup or restore (`_step_token`, which wraps `action_api_token()`, [ADR-059](../../adr/0059-driver-action-api-tokens.md)) and delete the session when the USER flow returns. They pass it with `action_job_variables(token, backup_id=...)` or `action_job_variables(token, restore_id=...)`, which put `STYRMIN_TOKEN` and `STYRMIN_BACKUP_ID` or `STYRMIN_RESTORE_ID` in the Job's `env`. When the token cannot be created, the INTERNAL flow logs a warning and the backup or restore runs without steps. A step write that fails never fails the backup or restore.

**Restore steps.** `execute_velero_restore_flow` records, in order:

| Key | Name | Recorded |
|---|---|---|
| `restore:namespace` | Delete the namespace | Around the namespace deletion and the wait for it to disappear; fails with "Namespace <name> was not deleted within 600s" or the Kubernetes error. |
| `restore:velero` | Run the Velero restore | Started before the Velero `Restore` is created. Succeeds on phase `Completed`. Fails when creating or polling raises, and on any other final phase with `failure_message("restore", status)`: "Velero restore failed validation: <validationErrors joined by "; ">", else Velero's `failureReason`, else "Velero restore phase: <phase> (<n> errors)". |
| `restore:recovery` | Run the recovery | Only after a `Completed` Velero restore, around `mark_restoring` and `reapply_and_finalize` (or `reapply_with_counterpart_identity`). Fails with "Restore reapply failed: <error>". |

A step is created when it starts, so a restore that fails while deleting the namespace has only `restore:namespace`.

**Backup steps.** Velero backs up the whole namespace and creates one `PodVolumeBackup` per backed-up pod volume. `execute_velero_backup_flow` receives the backup's components (the keys of `Backup.component_statuses`) and records one `backup:component:<name>` step ("Back up <name>", kind `BACKUP_COMPONENT`) per component (`agent/steps/backup_components.py`):

- On each poll of `poll_backup_status` (`on_poll` callback), it lists the backup's `PodVolumeBackup` objects (`VeleroClient.list_pod_volume_backups`, label `velero.io/backup-name`, with Velero's cut-and-hash rule for names longer than 63 characters) and maps each pod to its component through the pod's `styrmin/component` label.
- A component's step starts at the earliest `startTimestamp` of its items. It ends at the latest `completionTimestamp` once every item has ended (`Completed`, `Failed` or `Canceled`) and the Velero backup has left the `New` and `InProgress` phases. Velero creates `PodVolumeBackup` objects only while the backup is `InProgress`, so before that a component whose listed items have all ended can still get another item, and its step stays running. It fails when an item failed, with "Pod volume <pod>/<volume>: <message>" for each failed item, joined by "; ".
- When the Velero backup ends, `finish` ends every component that has not ended with the backup's result and its start and completion times. This covers components without pod volumes, and components whose items were last listed while the backup was `InProgress`. A backup that did not complete gives those components `failure_message("backup", status)`.
- Failures to list or record are logged and never fail the backup. A write made during polling that was not recorded is sent again on the next poll. `finish` sends a write that was not recorded again up to 3 attempts in total, 2 seconds apart (`FINISH_ATTEMPTS`, `FINISH_RETRY_DELAY_SECONDS`), then logs the components whose steps it could not end.

**Crashes.** When the USER flow fails or crashes, the INTERNAL flow fails every pending or running step of the backup or restore with the error (`fail_open_steps` in `services/steps/internal_flows.py`) before it marks the record `FAILED`.

**Velero's `FailedValidation` phase.** `poll_backup_status` and `poll_restore_status` return on every phase in `TERMINAL_PHASES`: `Completed`, `PartiallyFailed`, `Failed` and `FailedValidation`. Before spec 019, `FailedValidation` was not final, so a restore of a Velero backup that no longer exists was polled until the 7,200-second timeout. It now fails within one poll, and `restore:velero` fails with Velero's validation errors.

**Error message of the record.** When Velero does not complete a backup or restore, the USER flow passes Velero's `failureReason` through the Prefect Variable. When Velero gives none, as for `FailedValidation` and `PartiallyFailed`, it passes the text of the failed step instead (`failure_message`, for example "Velero restore failed validation: …"). The INTERNAL flow stores it as the `Backup` or `Restore` record's error message, and falls back to "Velero backup phase: <phase>" or "Velero restore phase: <phase>" when the Variable holds an empty reason.

**RBAC.** The agent's role grants `get` and `list` on `podvolumebackups` in `velero.io` (`helm/agent/templates/roles.yaml`), for the backup component steps.

## Restore Lifecycle

A restore is a multi-stage operation: velero recreates the namespace and its resources, but Kubernetes does not restore the `status` subresource and kopf does not fire `on.create` for a restored CRD (the `kopf.zalando.org/last-handled-configuration` annotation is restored too, fooling kopf into thinking it has already handled the resource). The styrmin restore workflow therefore drives the lifecycle explicitly so the deployment converges back to a healthy state without the operator's 300 s readiness timeout tripping.

### Stages

1. **Restore start (`services/backup/service.py:create_restore`).** The deployment's status is flipped to `DeploymentState.RESTORING` in the same transaction that creates the `Restore` record. Internal deployments are rejected, and so are tombstoned ones (`deleted_at` set): Velero would recreate the deleted deployment's resources and the flip would move it out of `DELETED` while `deleted_at` stays set. The tombstone keeps `active_application_instance_id`, so the CLI can resolve a target instance for it; the service guard is what refuses it. A second restore is rejected with `RestoreAlreadyInProgressError` when a **non-terminal `Restore` row** (`PENDING` or `IN_PROGRESS`) already targets that deployment, or when one already replays the same backup. `find_in_flight_restore` counts a row as targeting the deployment when it targets the requested or the deployment's own `styrmin-<id>` namespace, or when it restores one of the deployment's own backups into any namespace other than another deployment's `styrmin-<id>` (`createRestore` accepts any `target_namespace`; an environment clone restoring the backup into its counterpart is not a conflict) — the refusal always names the offending restore in `existing_restore_id`. The guard deliberately does **not** read `deployment.status`: an environment clone parks each counterpart in `RESTORING` so nothing reconciles it before its data lands (`specs/010-environment-clone/research.md` D5), and that state is the *precondition* of the first cross-target restore rather than a conflict with it. A deployment left `RESTORING` by a dead restore is therefore restorable again instead of permanently wedged. If the caller then cannot dispatch `execute_restore_workflow`, nothing would ever move the `PENDING` row, so `createRestore` and the environment-restore fan-out call `settle_undispatched_restore`, which marks the restore `FAILED` with the dispatch error and the deployment `FAILED` in one transaction; the clone flow does the same through `_settle_undispatched_restore`.
2. **Velero work (USER flow).** Namespace is deleted, then velero restores everything from the backup. The CRD is recreated with empty status.
3. **Operator quiesce.** While `phase == Restoring`, the operator's `kopf_styrmin_deployment_timer` early-returns — it does not advance phases and does not trip the 300 s readiness-timeout-to-Error branch.
4. **Post-velero recovery (`operator/restore_recovery.py`).** Called from the USER flow after velero polling reports `Completed`:
   - `mark_restoring` — patches the restored CRD to `phase=Restoring` / `displayState=Restoring` so the operator timer recognises the in-flight state.
   - `reapply_and_finalize` — strips kopf state-tracking annotations, re-applies prerequisites (`execute_phase_prerequisites`) and utility resources (`execute_phase_services`), then patches the CRD to `phase=Ready` / `displayState=Running`.
   - `mark_failed` — used on any failure with a message that distinguishes velero failure from post-restore reapply failure.
5. **Final DB transition (INTERNAL flow).** `deployment.status` is moved from `RESTORING` to `RUNNING` (or `FAILED`) inline so the UI reflects the transition immediately rather than waiting on the next agent status poll.

<!-- Extracted from specs/011-deployment-backup-history on 2026-10-10 -->

### Restoring a backup of an earlier instance

The backup history (`get_backups(deployment_id=...)`) lists backups of instances that are no longer active, for example a backup taken before an upgrade. An in-place restore of such a backup goes through the same stages:

- The restore puts the earlier instance's `StyrminDeployment` and `HelmRelease` back in the deployment's namespace, with that instance's application version and config.
- `create_restore` does not compare the backup's application version with the deployment's, and does not change `deployment.active_application_instance_id`. The deployment page and `styrminctl` keep showing the active instance's application version. `test_backup_and_restore_lifecycle` checks this after an upgrade from 0.1.0 to 0.2.0.
- The restored `StyrminDeployment` carries the earlier instance's spec. What the status reporter's stale-instance guard ([data-models.md](data-models.md)) does with its reports after such a restore is not known. No test covers it.

The clients, not the server, warn before such a restore:

- The Restore dialog on the Backups tab (`DeploymentDetailPage.tsx`) shows both application versions and a warning when the backup's instance is not the active instance or its application version differs.
- `styrminctl backups restore --last` picks the newest completed backup in the history whose expiry date has not passed, and prints how many expired backups it skipped. For a backup of an earlier instance or of another version it prints both versions and asks for confirmation; `--yes` skips the question, and without a terminal the command refuses unless `--yes` is passed. It refuses a deleted deployment before it asks.
- The Backups tab marks a backup whose expiry date has passed as expired and disables its restore, because Velero deletes a backup when it expires.

Design rationale: [ADR-063](../../adr/0063-restore-of-earlier-instance-backup.md).

### Display state mapping

The agent's status reporter maps CRD `displayState` to `deployment.status` (see `services/deployment_status.py:_DISPLAY_STATE_TO_STATUS`):

| `DisplayState` | `DeploymentState` |
|----------------|-------------------|
| `Deploying` | `DEPLOYING` |
| `Running` | `RUNNING` |
| `Restoring` | `RESTORING` |
| `Error` | `FAILED` |

A restore holds `deployment.status` at `RESTORING` while a non-terminal `Restore` row (`PENDING` or `IN_PROGRESS`) targets the deployment, as `find_in_flight_restore` defines it in stage 1 and `has_in_flight_restore` checks it: a report updates the `DeploymentStatus` snapshot but not `deployment.status`, and stage 5 sets the final state (or, when the workflow could not be dispatched, the caller fails both rows as described in stage 1). The CRD reads `Restoring` only after stage 4's `mark_restoring`, so reports sent before then carry the pre-restore `Running`, the teardown's `Deleting`, or the `Deploying` default of the status-less CRD that Velero recreates ([#389](https://github.com/opsmill/styrmin/issues/389)). Once the row is terminal, reports apply again.

## Environment-Level Backup & Restore

Everything above is per-instance. `services/backup/environment.py` adds a
coordinated environment scope on top of it, leaving everything downstream of row
creation untouched: no new Prefect flows, no changes to
`execute_backup_workflow` / `execute_restore_workflow`, no new backup
strategies, and no writer for the parent status. An environment backup is a
parent record plus a fan-out loop over the existing `create_backup` /
`create_restore` services.

The per-instance *service* layer did change, additively, in four places:

- `create_backup` / `create_restore` take the parent-FK kwarg
  (`environment_backup_id` / `environment_restore_id`), null for a standalone
  operation;
- both now generate their row id up front so the auto-generated name is final
  before the `INSERT` — a shared sentinel violates the `unique=True` name index
  as soon as two rows are created inside one transaction, which the environment
  capture does (see [The capture is atomic](#the-capture-is-atomic--and-terminal-status-still-is-not-convergence));
- `createBackup`'s target resolution moved into the shared
  `resolve_backup_target`, so the mutation and the fan-out build identical
  constituents (FR-014);
- `delete_environment` gained the snapshot cascade.

The design decisions are recorded in
[ADR-055](../../adr/0055-environment-backup-parent-records.md); this section
describes the resulting flow.

### Fan-out

```text
GraphQL Mutation (createEnvironmentBackup)
        |
        v
  create_environment_backup  (services/backup/environment.py)
        |
        |  ONE TRANSACTION ------------------------------------------------
        |   1. resolve environment, guard concurrency (derived, see below)
        |   2. filter eligible deployments
        |   3. capture environment_config + one DeploymentSnapshot each
        |   4. create the EnvironmentBackup row
        |   5. for each captured snapshot:   <-- per-item try/except (ADR-0012)
        |        +--> resolve_backup_target(instance_id)
        |        +--> create_backup(..., environment_backup_id=<parent>)
        |             (via _SharedTransaction — joins this transaction)
        |        |
        |        |   creation failure -> ConstituentError collected, continue
        |        +--> collect (backup_id, deployment_id) for dispatch
        |   6. persist constituent_errors
        |  --> COMMIT  (the capture is now complete and durable)
        |  ----------------------------------------------------------------
        v
  for each committed constituent:
        +--> prefect_manager.run_action(EXECUTE_BACKUP)
        |
        |   dispatch failure -> Backup row stays PENDING, loop continues
        v
  audit line emitted, parent re-read and returned
        (NOT_FOUND if it was deleted mid-dispatch — FR-010 has no status guard)
```

From there each constituent is an ordinary backup: the same INTERNAL/USER
two-worker flow, the same Velero objects, the same `update_backup_status`
writer, the same TTL resolution. The parent has **no writer at all** — which
is why nothing downstream had to change.

Structured audit lines mirror ADR-0012's `env_config_fanout_dispatched`:

```text
env_backup_fanout_dispatched environment_id=… environment_backup_id=… evaluated=… dispatched=… conflict=… dispatch_failed=…
env_restore_fanout_dispatched environment_id=… environment_backup_id=… environment_restore_id=… evaluated=… restored=… skipped=… config_redeployed=… dispatch_failed=…
```

### Data models

Neither parent table has a status column — see [Derived
status](#derived-status) below. Both ship in one Alembic revision
(`c1d2e3f4a5b6`), which also adds the two nullable FK columns on `Backup` and
`Restore`. No new DB enums.

```python
class EnvironmentBackup(StyrminModel, table=True):
    name: str                      # unique; defaults to styrmin-envbackup-<id>
    environment_id: UUID           # FK to Environment (non-nullable)
    environment_config: dict | None    # JSON: Environment.config at backup time
    deployment_snapshots: list | None  # JSON: list[DeploymentSnapshot]
    constituent_errors: list | None    # JSON: list[ConstituentError]
    backups: list[Backup]              # constituents, via Backup.environment_backup_id
    restores: list[EnvironmentRestore]


class EnvironmentRestore(StyrminModel, table=True):
    environment_backup_id: UUID        # FK to EnvironmentBackup (non-nullable)
    skipped_constituents: list | None  # JSON: list[SkippedConstituent]
    restores: list[Restore]            # constituents, via Restore.environment_restore_id
```

The three JSON shapes are Pydantic models in the service module, stored as
plain JSON (the `Backup.component_statuses` / `metadata_` precedent):

| Model | Fields | Purpose |
|-------|--------|---------|
| `DeploymentSnapshot` | `deployment_id`, `deployment_name`, `instance_id`, `driver_name`, `driver_version`, `driver_fingerprint`, `application_version`, `config`, `parameters` | Declared state of one eligible deployment. Records the ADR-0053 provenance fingerprint, not just the version string, so a future clone can tell whether the same driver content is still loaded. An unresolvable driver version degrades rather than failing the snapshot: `driver_name` / `driver_version` to empty strings, `driver_fingerprint` to `None`. |
| `ConstituentError` | `deployment_id`, `deployment_name`, `error` | A constituent that never got a `Backup` row — most often `BackupAlreadyInProgressError`, which `create_backup` raises *before* row creation. |
| `SkippedConstituent` | `deployment_id`, `deployment_name`, `reason` | A constituent that was not restored. `reason` is free text, not a closed enum on the wire. |

`deployment_snapshots` is the record of what *should* be in the snapshot;
linked `Backup` rows are what *is*. The difference is the gap left by an
individually deleted constituent, and it is surfaced rather than hidden — the
`constituents` GraphQL resolver joins snapshots ⋈ linked backups ⋈
`constituent_errors` and returns an entry per snapshot with `backup`, `error`,
or neither.

### Derived status

`derive_environment_operation_status(children_statuses, error_count)` is a pure
function, called on every read, shared by both parents:

```text
any child PENDING/IN_PROGRESS  -> IN_PROGRESS
                                  (narrowing to PENDING when every child is
                                   PENDING and error_count == 0)
all children terminal, over (terminal children + error_count):
    no failures                -> COMPLETED
    some completed, some not   -> PARTIAL
    nothing completed          -> FAILED
    no children, no errors     -> COMPLETED   (config-only snapshot)
```

Inputs per parent:

| Parent | `children_statuses` | `error_count` |
|--------|---------------------|---------------|
| `EnvironmentBackup` | linked `Backup.status` values | `len(constituent_errors)` |
| `EnvironmentRestore` | linked `Restore.status` values | `len(skipped_constituents)` |

Storing this was rejected outright: a stored parent status is a second source
of truth that can contradict its children after a crash or a race between
concurrent child completions, and the spec requires that contradiction be
*impossible*, not merely unlikely. Deriving it also means the existing flows
need no parent-update callback. The closest prior art is
`update_backup_component_status`, which derives a parent status from a child
map — but stores it, and collapses mixed outcomes to `FAILED`. This lifts the
derivation, adds `PARTIAL`, and drops the storage.

The `EnvironmentBackupStatus` / `EnvironmentRestoreStatus` GraphQL enums both
project the same service-layer `EnvironmentOperationStatus`.

#### The capture is atomic — and terminal status still is not convergence

**The derivation never sees a half-built capture.** The parent row, every
constituent `Backup` row and every recorded `ConstituentError` are written in
**one transaction, committed before any dispatch** (ADR-0012
commit-before-dispatch, made atomic). Committing the parent on its own first —
the original shape — left a window where a snapshot had zero children and zero
errors and therefore derived `COMPLETED`; a `CancelledError` (client
disconnect, request timeout) escapes the per-constituent `except Exception` and
made that state permanent, and the concurrency guard below (an `EXISTS` over
non-terminal *children*) did not hold the environment while the window was open,
so a second `createEnvironmentBackup` passed it (FR-009).
`restore_environment_backup` commits the same way.

**What a fresh snapshot reads now.** After the commit, either the snapshot does
not exist or its constituents and recorded errors exist with it, so the first
read is honest: `PENDING` (constituents created, none started), `IN_PROGRESS`
(some constituents created, at least one creation error recorded), `FAILED`
(every constituent blocked at creation, so zero children and `error_count > 0`),
or `COMPLETED` — which on a brand-new snapshot means only one thing: nothing was
eligible, so it is the config-only snapshot of FR-011.
`derive_environment_operation_status([], 0) == COMPLETED` is therefore still
correct and still load-bearing; it is no longer reachable from a half-built
capture.

Reusing `create_backup` / `create_restore` inside that transaction needs
`_SharedTransaction`, a `UnitOfWork` view that forwards every repository to the
real unit of work and makes `commit`/`rollback` no-ops. Without it those
services would commit a half-built capture at the end of their own `async with
uow` block, and `UnitOfWork.__aexit__` would *roll back the parent snapshot*
whenever one constituent raised (e.g. `BackupAlreadyInProgressError`) — turning
per-constituent isolation into "no snapshot at all".

**Terminal status is still not evidence that a snapshot covers the
environment.** A snapshot whose constituents were individually deleted
afterwards legitimately reads `COMPLETED` with fewer children than
`deployment_snapshots` (that gap is the point — see FR-014). Coverage is a count,
not a status: the capture commits

```text
len(backups) + len(constituent_errors) == len(deployment_snapshots)
```

and a later shortfall against that identity is precisely the set of
individually deleted constituents. Comparing linked backups alone against
`deployment_snapshots` is *not* the check — a constituent that failed at
creation never got a row, so it is a legitimate permanent shortfall. The
`constituents` resolver already does this join: an entry with neither `backup`
nor `error` is a deleted constituent, which is why the E2E asserts
per-constituent outcomes rather than status alone.

**A terminal restore does not mean the environment has converged.** The
constituent data restores are done, but the reverted config is still
propagating to the deployments that did *not* receive a constituent restore.
That propagation is tracked by those deployments' own `Task` rows, not by the
`EnvironmentRestore`.

### Eligibility

`is_eligible_for_environment_backup(deployment)` — non-tombstoned, not
`internal`, and carrying an active application instance. Deployment *state* is
irrelevant: a `FAILED` deployment with an active instance still contributes a
constituent. The list comes from `uow.deployments.find_all_by_environment`
(which already excludes tombstones); the predicate repeats the check so it is
correct on any deployment list.

Note that every real environment carries at least one `internal` deployment
(its ingress controller), so "one constituent per deployment" is always "one
constituent per *eligible* deployment" in practice.

### Concurrency guard

`_guard_no_environment_operation_in_progress` raises
`EnvironmentOperationInProgressError` (`ALREADY_IN_PROGRESS`, metadata carrying
the in-flight operation's id and kind) when the environment already has an
environment-level backup or restore in flight. "In flight" is itself derived —
repository `EXISTS` queries (`has_in_progress_environment_backup` /
`has_in_progress_environment_restore`) over linked children in
`PENDING`/`IN_PROGRESS` — so there is no lock row to leak if a process dies.

Two consequences worth knowing:

- **A stuck constituent pins the environment.** Dispatch is fire-and-forget; a
  constituent whose flow never ran stays `PENDING`, so its parent stays
  non-terminal and the guard keeps rejecting new operations. Deletion is the
  escape hatch, which is why `delete_environment_backup` has no status guard.
  A constituent backup whose dispatch fails stays `PENDING` this way. A
  constituent restore whose dispatch fails does not: the fan-out marks it
  `FAILED` and its deployment `FAILED` (`settle_undispatched_restore`).
- **Two racing create calls can both pass the check.** Accepted: the
  per-instance `has_in_progress_backup` guard then turns the loser's
  constituents into recorded `ConstituentError`s (a `PARTIAL` outcome) rather
  than corrupting anything. A DB advisory lock was rejected as disproportionate
  machinery for the window.

### Restore ordering

`restore_environment_backup` runs five steps in one service function, in this
order:

1. **Guard.** Snapshot exists; its *derived* status is `COMPLETED` or `PARTIAL`
   (else `EnvironmentBackupNotRestorableError`, `OPERATION_DENIED`); no
   environment-level operation in flight.
2. **Classify** every captured constituent as usable or skipped, and persist
   the skips on the new `EnvironmentRestore` row at creation time.
3. **Revert `Environment.config`** to the captured value, recompute
   capabilities, create one constituent restore per usable constituent
   (`create_restore(..., environment_restore_id=…)`), and **commit all of it
   once, before any dispatch**.
4. **Exclusion-aware config fan-out**: `redeploy_for_environment_update` for
   every eligible deployment *not* receiving a constituent restore.
5. **Dispatch** one `EXECUTE_RESTORE` per created constituent restore. A
   dispatch failure marks that restore and its deployment `FAILED` and the
   loop continues.

Why the exclusion in step 4 is load-bearing: a deployment receiving a Velero
data restore is being returned to its backup-time state, and its restored
in-cluster resources already correspond to the captured config (both came from
the same near-consistent snapshot). Redeploying it via the config fan-out
*while* Velero restores the same namespace races apply-state against the
restore with an undefined outcome. Excluding restored deployments removes the
race by construction while still converging everything: restored deployments
via Velero, the rest via the standard fan-out.

Two implementation details that are easy to get wrong:

- **The config revert assigns `Environment.config` directly** — it does *not*
  delegate to `update_environment`, which treats `config is None` as an
  idempotent no-op and would silently make a captured `None` config
  unrestorable.
- **A `RestoreAlreadyInProgressError` while creating a constituent restore
  downgrades to a skip**, never an abort. Late skips are appended to
  `skipped_constituents` inside the step-3 transaction, so they are durable
  before anything is dispatched.

### Skip classification

`_classify_constituents` returns `(usable, skipped)`. The reasons come from the
`SkipReason` enum, stored as its `str` values:

| `SkipReason` | Value | Condition |
|--------------|-------|-----------|
| `BACKUP_FAILED_AT_CREATION` | `backup failed at creation` | The snapshot recorded a `ConstituentError` for this deployment. |
| `BACKUP_NOT_COMPLETED` | `backup not completed` | Linked `Backup` exists but its status is not `COMPLETED`. |
| `BACKUP_DELETED` | `backup deleted` | No linked `Backup` row and no recorded error — deleted individually. |
| `BACKUP_EXPIRED` | `backup expired` | `expires_at < now`, derived from `Backup.metadata_`. |
| `DEPLOYMENT_GONE` | `deployment no longer exists` | Deployment row missing or tombstoned. |
| `DEPLOYMENT_BUSY` | `deployment busy with another restore` | Deployment already `RESTORING` from a separately started restore. |

Plus one escape hatch outside the enum: `restore could not be created: <exc>`,
appended as a late skip when `create_restore` fails for any other reason.

`BACKUP_EXPIRED` is the subtle one. Velero garbage-collects expired backup data
cluster-side but never updates the DB row, so **an expired constituent still
reads `COMPLETED`**. Classification therefore computes expiry from the
recorded TTL metadata (`_backup_expires_at`, the same derivation the
`Backup.expiresAt` resolver uses) rather than trusting `status`. Without this,
a restore would dispatch a Velero restore for data that no longer exists and
fail at the Velero step instead of reporting an honest skip.

### Cascade delete

`delete_environment_backup` runs the cascade in FK-dependency order: every
constituent via the existing `delete_backup` (which already deletes each
backup's `Restore` rows, taking the environment restores' constituents with
them), then the snapshot's now-childless `EnvironmentRestore` rows, then the
parent. A constituent that vanished in the meantime is a no-op, not an error.

**There is deliberately no status guard** — deleting a snapshot whose
constituents are still in flight is the documented escape hatch for an
environment pinned by a stuck constituent (see [Concurrency
guard](#concurrency-guard)).

`delete_environment_backups_for_environment` is the environment-deletion arm:
`services/environments.py::delete_environment` calls it *before* deleting the
environment row, because `environmentbackup.environment_id` is a non-nullable
FK and would otherwise turn environment deletion into a constraint violation
surfacing as an opaque `INTERNAL_ERROR`.

### Typed errors

| Error | Code | Raised when |
|-------|------|-------------|
| `EnvironmentBackupNotFoundError` | `NOT_FOUND` | Snapshot id does not resolve — including the snapshot being deleted underneath a fan-out that was still dispatching (FR-010 has no status guard). |
| `EnvironmentRestoreNotFoundError` | `NOT_FOUND` | Restore id does not resolve, or the restore was taken by its snapshot's cascade while its fan-out was still dispatching. |
| `EnvironmentOperationInProgressError` | `ALREADY_IN_PROGRESS` | An environment-level operation is already in flight for the environment. |
| `EnvironmentBackupNotRestorableError` | `OPERATION_DENIED` | Derived status is not `COMPLETED` or `PARTIAL`. |

### Authorization asymmetry

`createEnvironmentBackup` and `deleteEnvironmentBackup` require `READ_WRITE`,
matching per-instance `createBackup` / `deleteBackup`.
`restoreEnvironmentBackup` requires **`ADMIN`**: it rewrites
`Environment.config`, which is exactly what `updateEnvironment` does, and that
mutation is `ADMIN`. Granting config-mutation-by-restore to `READ_WRITE` would
be a privilege bypass. No new roles or permission concepts (ADR-0017).

## Environment Clone

`services/backup/clone.py` + `workflows/templates/clone.py` compose one more scope on
top of the environment capture: an **environment clone** copies a live environment into
a **new** environment on the same cluster, built entirely from a fresh environment
backup of the source. The design decisions are recorded in
[ADR-056](../../adr/0056-environment-clone-record-and-cross-target-restore.md); this
section describes the resulting mechanics.

The operation splits in two, and the split is the whole architecture:

- **Everything decidable synchronously** happens in the mutation — validation, the clone
  record, the capture, the constituent dispatch. A caller therefore receives
  `ALREADY_EXISTS` / `NOT_FOUND` / `VALIDATION_ERROR` / `ALREADY_IN_PROGRESS` at request
  time, with zero side effects.
- **Everything that has to *wait*** happens in `EXECUTE_ENVIRONMENT_CLONE`, the
  platform's first orchestration that polls instead of firing and forgetting: nothing
  materialises until the capture reaches a restorable terminal status.

`EnvironmentClone` has **no status column** (same argument as the two ADR-055 parents,
with four inputs instead of two) and its `name` is **not unique** (uniqueness of an
environment name lives on `Environment(name, cluster_id)`; a discarded clone must not
burn the name).

### Service functions (`services/backup/clone.py`)

| Function | Purpose |
|----------|---------|
| `clone_environment(...)` | The mutation half. Three phases: (1) upfront validation with zero side effects — source resolution (ADR-031), config-override canonicalisation, cleared-field names, target name free, every selected id belongs to the source, source concurrency guard; (2) one transaction writing the clone record, its upfront attribution and the whole capture; (3) post-commit dispatch of one `EXECUTE_BACKUP` per constituent plus the single `EXECUTE_ENVIRONMENT_CLONE` run. The target name is checked but **not reserved** — reserving it needs a placeholder environment, which FR-002 forbids. |
| `merge_environment_config(captured, override, cleared)` | Top-level-field replacement merge over the canonicalised capture, cleared fields popped **before** the override is applied. Validates the result; a field both cleared and overridden takes the override. |
| `derive_clone_capture_status(environment_backup)` | The backing capture's own derived status, or `None` when the capture is unreachable (never registered, or since deleted). The absence is never re-interpreted — the deletion path records what happened in `clone_errors` instead. |
| `derive_environment_clone_status(...)` / `..._from_record(clone, restores)` | The derivation (below). The `_from_record` adapter is what the resolvers, the guards and the deletion cascades all read the record through. |
| `find_clone_occupying_environment(...)` | Backs the environment-level guard: a non-terminal clone occupies its *created* environment for its whole lifetime, and its *source* only while the capture is in flight. |
| `guard_no_clone_capturing_environment_backup(...)` | The `IN_USE` guard on `delete_environment_backup`, scoped to the capture window (see below). |
| `detach_clones_from_environment_backup(...)` | Post-capture backup deletion: nulls the FK and appends `environment_backup_deleted` — fatal on a non-terminal clone, non-fatal on a terminal one. |
| `detach_clones_from_created_environment(...)` | The discard path: nulls `created_environment_id` and appends a fatal `created_environment_deleted`. |
| `resolve_clones_of_deleted_source_environment(...)` | Source deletion: terminal clones survive as provenance with `source_environment_id` nulled; non-terminal ones are deleted outright. |
| `get_environment_clone` / `get_environment_clones` | Reads. `get_environment_clones` is scoped by **source** environment, newest first. |

### Flow

```text
GraphQL Mutation (cloneEnvironment)            [ADMIN]
        |
        v
  clone_environment  (services/backup/clone.py)
        |
        |  UPFRONT — zero side effects on any failure
        |   resolve source, validate override + cleared fields,
        |   target name free?, selection ids belong to source?,
        |   environment-level guard on the source
        |
        |  ONE TRANSACTION ------------------------------------------------
        |   1. EnvironmentClone row (no status column)
        |   2. deployment_results: one entry per source deployment
        |      considered — upfront skips already attributed
        |   3. the whole capture, via create_environment_backup with a
        |      deployment filter (parent + constituent Backup rows +
        |      constituent errors)
        |  --> COMMIT
        |  ----------------------------------------------------------------
        v
  dispatch: one EXECUTE_BACKUP per constituent, then ONE
            EXECUTE_ENVIRONMENT_CLONE run
        |
        v
  EXECUTE_ENVIRONMENT_CLONE  (INTERNAL; workflows/templates/clone.py)
        |
        |  1. poll the capture's DERIVED status until terminal
        |  2. gate: FAILED capture -> fatal capture_failed, nothing
        |     materialises.  COMPLETED / PARTIAL -> proceed with the
        |     usable constituents
        |  3. create the environment from the captured config with the
        |     clone's cleared fields dropped and its override merged over
        |     the rest; capabilities recomputed (ADR-0027).  Committed
        |     before any counterpart exists — it is the discard handle
        |  4. per usable constituent: deploy_application(driver_version_id
        |     pinned from the snapshot fingerprint, skip_initial_reconcile,
        |     release_reference = the SOURCE's release name), created in
        |     RESTORING
        |  5. per counterpart: create_restore(target_deployment_id=<counterpart>)
        |     -> cross-target restore; record the attribution
        v
  env_clone_materialised … (structured audit line)
```

The flow **never writes the clone's status** — it writes the *inputs* to the derivation:
`created_environment_id`, `deployment_results`, `clone_errors`. It also tolerates its own
record vanishing mid-flight (deleting the source removes non-terminal clones), ending
quietly on `EnvironmentCloneNotFoundError` exactly as `execute_restore_workflow` handles
`RestoreNotFoundError`.

### Derived status

`derive_environment_clone_status` takes four inputs — the capture's derived status, the
created environment's existence, the attribution entries, the recorded events — plus the
referenced `Restore` rows. First match wins:

```text
1. any FATAL clone_errors entry                -> FAILED
   (per-deployment failures are never fatal entries)
2. capture PENDING and nothing else recorded   -> PENDING
3. anything still moving                       -> IN_PROGRESS
     capture non-terminal, or no created environment (and no
     created_environment_deleted marker), or a `pending` entry, or a
     resolvable non-terminal Restore row
4. no *included* entry failed                  -> COMPLETED
5. some included failed, some succeeded        -> PARTIAL
6. every included entry failed                 -> FAILED
```

Four points worth internalising, all pinned by the unit matrix:

- **`PENDING` is not guaranteed to be the first status.** An upfront skip is recorded with
  the clone row, and recorded progress is progress — so a freshly created clone commonly
  reads `IN_PROGRESS`. Nothing may assume a `PENDING`-first progression.
- **"Included" means "not skipped".** A skipped deployment neither fails the clone nor
  rescues it: `skipped` + `failed` with nothing cloned is `FAILED`, while **all-skipped is
  `COMPLETED`** — as is a clone of an empty selection (`deploymentIds: []`), which is the
  legal "configuration only, no applications" shape.
- **A missing `Restore` row does not retract a recorded outcome.** A restore that cascaded
  away leaves its `cloned` entry standing; only a `FAILED` restore turns it into a
  failure (`RestoreStatus` has no `PARTIAL` member).
- **`NULL` FKs are disambiguated by markers, not by absence.** `created_environment_id IS
  NULL` means "not created yet" *unless* a `created_environment_deleted` entry says
  otherwise, which is why every cascade appends one.

| Marker step | Written when | Fatal? |
|-------------|--------------|--------|
| `capture_failed` | The capture reached `FAILED`; nothing materialises. | yes |
| `target_name_taken` | The target name was free at validation and taken at creation (TOCTOU). | yes |
| `environment_creation_failed` | The merged config was invalid, or environment creation raised. | yes |
| `environment_backup_deleted` | The backing capture was deleted post-capture. | yes on a non-terminal clone, no on a terminal one |
| `created_environment_deleted` | The created environment was deleted — the discard path. | yes |

### Attribution and skip reasons

Every source deployment a caller could have selected gets one `deployment_results` entry:
`PENDING` → `CLONED` / `SKIPPED` / `FAILED`, with a free-text `reason` on the latter two,
plus `counterpart_deployment_id` and `restore_id` once they exist. Three distinct
behaviours, deliberately not collapsed:

| Situation | Outcome |
|-----------|---------|
| Selected id unknown, or belonging to another environment | Rejected **upfront** with `NOT_FOUND` — no clone record, no capture, no side effects. |
| Selected id known but ineligible | Attributed `SKIPPED` with a reason. Never an error. |
| Eligible | Included, and the selection also filters the capture. |

`internal` deployments are **omitted from attribution entirely** unless explicitly named:
the cloned environment gets its own fresh ingress controller as part of ordinary setup, so
reporting the source's as a skip would be noise. The reason constants are
`CLONE_REASON_*` in `services/backup/clone.py` (`not_selected`, `not_eligible`,
`internal`, `tombstoned`, `capture_failed`, `backup_not_completed`, `backup_deleted`,
`backup_expired`, `driver_version_gone`, `capture_unusable`); like ADR-055's skip
classification the wire value is free text, not a closed code set.

### Config override and clearing

The wire input is `UpdateEnvironmentInput` (**camelCase**, `envVars` as a list of
`{name, value}`), and it is **stored and returned as canonical snake_case JSON** — the
asymmetry is deliberate and documented on the public surface. `clearConfigFields` takes
**snake_case** `EnvironmentConfig` field names.

- Clearing removes the field: it is *absent* from the created environment's config, not
  null and not defaulted, and resolves to `None` in an instance context.
- Clearing a field the capture never set is a legal no-op; only an unknown *field name* is
  a `VALIDATION_ERROR`.
- The merge runs **before** `create_environment`, so the counterparts' very first instance
  contexts already observe the merged config — there is no window under source config.
- Known caveat: the generated input model does not forbid extra keys, so a **misspelled**
  override field is silently dropped and the captured value stays in place.

### Cross-target restore

The shipped restore contract was in-place by construction, not by Velero limitation.
Velero's native `namespaceMapping` was already wired in `build_velero_restore`; what
changed is our own coupling:

| Coupling point | Change |
|----------------|--------|
| `create_restore` resolved the deployment *from the backup* and flipped **that** deployment to `RESTORING` | Gains an explicit optional target deployment: all guards and the `RESTORING` flip apply to the target, and the long-persisted `Restore.target_instance_id` is finally honoured for attribution. |
| `execute_restore_workflow` derived the source namespace from, and wrote terminal status to, the same deployment id | Signature splits source identity (namespace derivation) from the status-write target. Identical values for an in-place restore. |
| Post-restore recovery assumed `crd_name == target_namespace` | Under `namespaceMapping` Velero preserves the CR *name*, so the restored CR name is passed explicitly. |
| Recovery replayed the **restored (source) CR spec** into the target namespace | For a cross-target restore, `operator/restore_recovery.py::reapply_with_counterpart_identity` replaces it with the **counterpart's own CR body**. |
| Restore CR labels carried the source instance id | The clone path labels with the counterpart's instance id. |

**Counterpart identity is split on purpose.** A counterpart keeps its own
`StyrminDeployment` CR identity (CR name = namespace = `styrmin-<counterpart_id>`) but
pins its **Helm release name to the source's** (`styrmin-<source_deployment_id>`). Velero
restores the source's Helm release-storage secret into the counterpart namespace, and
restored chart objects carry the source's `meta.helm.sh/release-name`. Matching the name
makes the recovery upsert a Helm *upgrade* — which rewrites those ownership annotations
consistently; a counterpart-named release would be a fresh *install* over objects Helm
already owns and would fail its ownership check.

**The restored release storage must be retargeted before that upgrade.** It still names
the source namespace — in its `namespace` field and on every object a chart pins with an
explicit `metadata.namespace` (all Bitnami subcharts, e.g. simple-app's postgres). An
upgrade straight from the restored record renders the release under the source namespace;
Flux then logs `release target configuration changed (release namespace): running
uninstall` and the uninstall deletes those pinned objects **from the source namespace**.
Two changes prevent it: a cross-target Restore CR sets
`excludedResources: [helmreleases.helm.toolkit.fluxcd.io]`
(`resources/builders/backup.py::CROSS_TARGET_EXCLUDED_RESOURCES`), so Flux has nothing to
upgrade until recovery re-renders the HelmRelease; and
`restore_recovery.py::retarget_helm_release` rewrites the source namespace to the
counterpart's in every restored `helm.sh/release.v1` Secret before it does. The pin is kept honest by
`services/context.py::_resolve_release_reference`, whose order is: explicit override → the
value the active instance already carries → `styrmin-<deployment id>`. A later config
fan-out therefore cannot silently rename a live release.

Operator-visible consequence: **`helm list -n styrmin-<counterpart>` shows a release named
after the *source* deployment.** Correct, not drift (assuming Helm's default secret
storage driver).

`reapply_with_counterpart_identity` then, in order: applies the counterpart's CR body
carrying kopf's state annotations over from the restored CR (a CR without
`last-handled-configuration` would make kopf fire `on.create` and race the finalize);
deletes the restored source-named CR **after clearing and verifying its finalizers**
(deleting it with kopf's finalizer intact fires the delete handler, which would tear down
the counterpart's HelmRelease and, through Flux, the volumes just restored); retargets the
restored release storage; and re-runs
prerequisites → HelmRelease → services against the counterpart's spec before marking it
Ready. Data survives; only identity objects are re-rendered.

Two related notes:

- Counterparts are created with the **initial reconcile deferred** and in the `RESTORING`
  state — reconciling first would only create resources the restore flow immediately
  deletes, and `RESTORING` is what makes the existing restoring-deployment guards protect
  a counterpart until its data lands. The restore concurrency guard was moved onto an
  actual non-terminal `Restore` row for exactly this reason (see
  [Restore Lifecycle](#restore-lifecycle)).
- The data-layer hooks (`pg_restore`, neo4j, mariadb, mongodb) already exec inside the
  restored pods with target-namespace selectors and read credentials from the restored
  Secrets, so they are target-agnostic. The open risk class is a chart that **generates**
  credentials at install/upgrade time: the counterpart's Helm values are re-rendered while
  its data is restored, so such a chart can mint credentials the restored data does not
  recognise. Statically configured credentials are safe (config and parameters are copied
  verbatim). The E2E performs an authenticated write against the counterpart to keep this
  honest.

### Concurrency and the discard cascades

- **The source is occupied only during the capture.** A non-terminal clone extends the
  existing environment-level guard for as long as its capture is non-terminal; afterwards
  clones proceed independently. A second clone of the same source during that window is
  refused with `EnvironmentOperationInProgressError`.
- **The created environment is occupied for the clone's whole lifetime.** Environment-level
  backups/restores/clones of it are refused, and `update_environment` refuses too (its
  redeploy fan-out would race the restore flow's namespace delete-and-wait).
  `redeploy_for_environment_update` also learned to skip `RESTORING` deployments.
  `delete_environment` stays allowed — it is the discard path.
- **`delete_environment_backup` refuses with `IN_USE` only while a referencing clone's
  capture is in flight**, and only while that clone is itself non-terminal. Terminality is
  **snapshotted at the guard, not re-derived after the cascade**, because the cascade
  deletes `Backup` and `Restore` rows that are themselves derivation inputs. Post-capture
  deletion is the escape hatch for a clone whose flow died.
- **`delete_environment` settles clone records first**, in both roles: as a *source*
  (terminal clones survive with the FK nulled and a non-fatal `environment_backup_deleted`
  entry, since the source's captures cascade; non-terminal ones are removed) and as a
  *created* environment (`created_environment_deleted`, fatal). It then cascades the
  environment's snapshots, then **its deployments** — asking each to tear its cluster
  resources down and deleting its rows in FK order, detaching rather than deleting
  cross-target restores so a clone's `restore_id` stays resolvable — and only then the
  environment row. That deployment cascade did not exist before this feature: every prior
  caller swallowed the resulting NOT NULL violation in cleanup handling.

## GraphQL API

### Queries

`Backup.steps` and `Restore.steps` (`[Step!]!`, by start time, pending steps last) return the steps described in [Backup and restore steps](#backup-and-restore-steps); they are empty for backups and restores that ran before steps were recorded. A response reads the steps of all its backups, and of all its restores, with one query each, wherever they appear, and reads none when `steps` is not requested (data loaders in `api/loaders.py`). `Backup.instance` reads the instances of all the response's backups with one query through the `application_instances` loader, so the backup history, which lists the backups of every instance, does not run one query per backup.

```graphql
backup(backupId: UUID!): Backup
backups(deploymentId: UUID, instanceId: UUID, status: BackupStatus): [Backup!]!   # exactly one id, else VALIDATION_ERROR; deploymentId = backup history
restore(restoreId: UUID!): Restore
restores(backupId: UUID!, status: RestoreStatus): [Restore!]!
backupSchedule(scheduleId: UUID!): BackupSchedule
backupSchedules(deploymentId: UUID!): [BackupSchedule!]!
environmentBackup(environmentBackupId: UUID!): EnvironmentBackup
environmentBackups(environmentId: UUID!): [EnvironmentBackup!]!
environmentRestore(environmentRestoreId: UUID!): EnvironmentRestore
environmentRestores(environmentBackupId: UUID!): [EnvironmentRestore!]!
environmentClone(environmentCloneId: UUID!): EnvironmentClone!    # non-null; NOT_FOUND if unknown
environmentClones(environmentId: UUID!): [EnvironmentClone!]!     # by SOURCE environment, newest first
```

### Mutations

```graphql
createBackup(instanceId: UUID!, name: String): Backup!
deleteBackup(backupId: UUID!): String!
createRestore(backupId: UUID!, targetNamespace: String!, targetInstanceId: UUID): Restore!
createBackupSchedule(deploymentId: UUID!, name: String!, cronExpression: String!, retentionCount: Int, enabled: Boolean): BackupSchedule!
updateBackupSchedule(scheduleId: UUID!, name: String, cronExpression: String, retentionCount: Int, enabled: Boolean): BackupSchedule!
deleteBackupSchedule(scheduleId: UUID!): String!
createEnvironmentBackup(environmentId: UUID!, name: String): EnvironmentBackup!   # READ_WRITE
restoreEnvironmentBackup(environmentBackupId: UUID!): EnvironmentRestore!         # ADMIN
deleteEnvironmentBackup(environmentBackupId: UUID!): Boolean!                     # READ_WRITE
cloneEnvironment(name: String!, environmentId: UUID, environmentName: String, clusterId: UUID, clusterName: String, deploymentIds: [UUID!], configOverride: UpdateEnvironmentInput, clearConfigFields: [String!]): EnvironmentClone!   # ADMIN
```

`Environment.clonedFrom: EnvironmentClone` is the provenance back-reference — `environmentClones` is scoped by *source*, so this is how a clone-born environment points at where it came from. All three clone reads are **ungated**, matching `environmentBackup(s)`; see [ADR-056](../../adr/0056-environment-clone-record-and-cross-target-restore.md) decision 6 for why that parity is a decision rather than an inheritance.

### Retention fields on `Backup`

```graphql
type Backup {
  ttl: String        # the applied retention, e.g. "2160h"
  expiresAt: DateTime
}
```

Both are `@strawberry.field` resolvers over `metadata_` in
`api/definitions/backup/backup.py`, and both are nullable — a pre-existing row
(or one whose `metadata_` is `None`) reports `null`, as does a `Failed` backup
for which Velero reported no expiration. `expiresAt` parses the stored ISO string
with `datetime.fromisoformat`, returning `null` when the key is absent or
unparseable.

The setter side is `backupTtl: String` on `UpdateEnvironmentInput` and on
`DeploymentConfigInput` (which `UpdateDeploymentInput` inherits, covering both
`deploy` and `updateDeployment`). Cluster and environment **create** take it
through their existing `config: JSON` argument.

The only UI setter is the environment scope: the Configuration tab's **Backup
Retention** section (`frontend/src/components/environment/BackupRetentionForm.tsx`)
drives `updateEnvironment` through `buildFullReplacementInput`, which carries
every other persisted field along. A blank input submits `backupTtl: null`, which
clears the environment policy and hands resolution back to the cluster scope.

## Component Status Tracking

Backups and restores track status at the component level. The overall status is derived from component statuses:

- Any component FAILED -> overall FAILED
- All components COMPLETED -> overall COMPLETED
- Otherwise -> IN_PROGRESS

## Velero Integration

### Builders (`agent/service/kubernetes/resources/builders/backup.py`)

- `build_velero_backup()` — Creates Velero Backup CRD spec with labels, hooks, and TTL. `ttl` is a **required** parameter (as it is on the `VeleroBackup` dataclass in `agent/service/kubernetes/velero/resources.py`): neither layer carries a fallback literal, so `services/backup/ttl.py` stays the single home of the default
- `build_velero_restore()` — Creates Velero Restore CRD spec with namespace mapping and hooks

### Install constraints (`helm/styrmin/values.yaml`)

Two Velero-side details the Python layer depends on, neither visible from the
code that uses them:

- **The Velero Deployment is named exactly `velero`.** Velero's
  repository-maintenance controller resolves its own Deployment by that
  hardcoded name to build the kopia maintenance Job, so the `velero` subchart
  ships `fullnameOverride: velero`. Any other fullname leaves kopia unable to
  prune: backups and restores still succeed, but the data behind expired
  backups is never reclaimed from the bucket. See
  [helm.md](../../guidelines/helm.md) ("Velero subchart naming").
- **`VELERO_RESTORE_PVC_PATCH_CONFIGMAP`** (`builders/backup.py`) names the
  ConfigMap holding the `resourceModifier` rules that strip `spec.volumeName`
  from restored PVCs. The chart renders `configMaps` entries as
  `<fullname>-<key>`, so the pinned fullname is what makes
  `velero-restore-pvc-patch` a stable name rather than a release-name
  derivative. Every Restore references it; a mismatch fails all of them.

Both are asserted by `backend/tests/unit/test_helm_velero_naming.py`, and the
maintenance path is exercised end to end by
`test_backup_and_restore_lifecycle`'s
`assert_backup_repository_maintenance_succeeds`, which backdates
`status.lastMaintenanceTime` on the `BackupRepository` the backup created (and
shortens `spec.maintenanceFrequency`, the spec change being what wakes the
controller) so a cycle runs inside the test instead of an hour later, then waits
for the stamp to move and fails fast on a `Failed` entry in
`status.recentMaintenance`.

### Volume Annotations (`agent/service/kubernetes/resources/builders/backup_annotations.py`)

- `build_backup_volume_annotation_patches()` — Generates Kustomize patches that inject `backup.velero.io/backup-volumes` annotations on pod templates

## Default Timeouts

| Operation | Default |
|-----------|---------|
| Backup | 3600s (1 hour) |
| Restore | 7200s (2 hours) |

## Key Files

| File | Purpose |
|------|---------|
| [services/backup/service.py](backend/styrmin_backend/services/backup/service.py) | Backup and restore service functions |
| [services/backup/environment.py](backend/styrmin_backend/services/backup/environment.py) | Environment-level fan-out, snapshot capture, derived status, classification, cascades |
| [services/backup/clone.py](backend/styrmin_backend/services/backup/clone.py) | Environment clone: registration, config merge/clear, derived clone status, guards and the discard cascades |
| [services/backup/ttl.py](backend/styrmin_backend/services/backup/ttl.py) | Retention default, validation, and deepest-wins scope resolution |
| [services/backup/scheduler.py](backend/styrmin_backend/services/backup/scheduler.py) | Backup schedule management |
| [services/backup/strategies/](backend/styrmin_backend/services/backup/strategies/) | Backup strategy implementations |
| [workflows/templates/backup.py](backend/styrmin_backend/workflows/templates/backup.py) | Prefect workflow templates for backup/restore |
| [workflows/templates/clone.py](backend/styrmin_backend/workflows/templates/clone.py) | `EXECUTE_ENVIRONMENT_CLONE` — polls the capture, creates the environment and counterparts, dispatches the cross-target restores |
| [operator/restore_recovery.py](backend/styrmin_backend/operator/restore_recovery.py) | Post-restore CR recovery, incl. `reapply_with_counterpart_identity` for cross-target restores |
| [agent/service/kubernetes/resources/builders/backup.py](backend/styrmin_backend/agent/service/kubernetes/resources/builders/backup.py) | Velero CRD builders |
| [agent/service/kubernetes/velero/client.py](backend/styrmin_backend/agent/service/kubernetes/velero/client.py) | `VeleroClient` polls (`TERMINAL_PHASES`, `on_poll`), `list_pod_volume_backups`, `failure_message` |
| [agent/steps/backup_components.py](backend/styrmin_backend/agent/steps/backup_components.py) | One `backup:component:<name>` step per component from `PodVolumeBackup` objects |
| [agent/service/kubernetes/resources/builders/backup_annotations.py](backend/styrmin_backend/agent/service/kubernetes/resources/builders/backup_annotations.py) | Volume annotation patches |
| [api/definitions/backup/environment_backup.py](backend/styrmin_backend/api/definitions/backup/environment_backup.py) | `EnvironmentBackup` strawberry types incl. the derived-status and constituents resolvers |
| [api/definitions/backup/environment_restore.py](backend/styrmin_backend/api/definitions/backup/environment_restore.py) | `EnvironmentRestore` strawberry types incl. skipped constituents |
| [repository/backup.py](backend/styrmin_backend/repository/backup.py) | Backup data access |
| [repository/restore.py](backend/styrmin_backend/repository/restore.py) | Restore data access |
| [repository/environment_backup.py](backend/styrmin_backend/repository/environment_backup.py) | Environment backup/restore data access and the in-progress `EXISTS` guards |
| [repository/environment_clone.py](backend/styrmin_backend/repository/environment_clone.py) | Environment clone data access, eager-loaded capture, referenced-restore lookup |
| [repository/backup_schedule.py](backend/styrmin_backend/repository/backup_schedule.py) | Schedule data access |
