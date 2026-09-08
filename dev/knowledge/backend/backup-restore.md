# Backup & Restore

## Overview

The backup/restore system provides component-level backup and restore operations for deployed application instances, built on top of Velero for Kubernetes-native volume snapshots. It supports multiple backup strategies per component and uses a two-worker architecture to separate orchestration from Kubernetes operations.

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
    started_at: datetime | None
    completed_at: datetime | None
    size_bytes: int | None
    error_message: str | None
    component_statuses: dict      # JSON: {component_name: {status, size_bytes, error}}
    metadata_: dict               # JSON: operation metadata (see below)
    restores: list[Restore]       # One-to-many relationship
```

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
| `create_backup(instance_id, uow, ...)` | Create on-demand backup with component configs |
| `get_backup(backup_id, uow)` | Get backup by ID |
| `get_backups(instance_id, uow, status)` | List backups for instance |
| `delete_backup(backup_id, uow)` | Delete backup (cascades to restores) |
| `update_backup_status(backup_id, status, uow, ...)` | Update overall backup status; `metadata_updates` merges keys into `Backup.metadata_` by reassignment |
| `update_backup_component_status(backup_id, component_name, ...)` | Update component status, derives overall status |

### Restore Operations (`services/backup/service.py`)

| Function | Description |
|----------|-------------|
| `create_restore(backup_id, target_namespace, uow, ...)` | Create restore from backup; resolves the target deployment, rejects internal deployments and concurrent restores, flips `deployment.status` to `RESTORING`. Returns `(Restore, deployment_id)`. |
| `get_restore(restore_id, uow)` | Get restore by ID |
| `get_restores(backup_id, uow, status)` | List restores for backup |
| `update_restore_status(restore_id, status, uow, ...)` | Update restore status |
| `update_restore_component_status(restore_id, component_name, ...)` | Update component restore status |

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

1. `execute_backup_workflow` (INTERNAL) — marks backup IN_PROGRESS, resolves the retention TTL and records it (see [Retention TTL](#retention-ttl-servicesbackupttlpy)), builds Velero CRD, dispatches to USER flow, updates status and `expires_at` from result
2. `execute_velero_backup_flow` (USER) — creates Velero Backup CRD, polls completion, stores result (phase + `status.expiration`) in Prefect Variable

**Restore:**

1. `execute_restore_workflow` (INTERNAL) — marks restore IN_PROGRESS, builds Velero CRD, dispatches to USER flow, transitions `deployment.status` between `RESTORING` and `RUNNING` / `FAILED` based on the result.
2. `execute_velero_restore_flow` (USER) — deletes target namespace first, creates Velero Restore CRD, polls completion, then runs the post-velero recovery (see [Restore Lifecycle](#restore-lifecycle) below), stores result in Prefect Variable.

## Restore Lifecycle

A restore is a multi-stage operation: velero recreates the namespace and its resources, but Kubernetes does not restore the `status` subresource and kopf does not fire `on.create` for a restored CRD (the `kopf.zalando.org/last-handled-configuration` annotation is restored too, fooling kopf into thinking it has already handled the resource). The styrmin restore workflow therefore drives the lifecycle explicitly so the deployment converges back to a healthy state without the operator's 300 s readiness timeout tripping.

### Stages

1. **Restore start (`services/backup/service.py:create_restore`).** The deployment's status is flipped to `DeploymentState.RESTORING` in the same transaction that creates the `Restore` record. Internal deployments are rejected. A second restore on a deployment already `RESTORING` is rejected with `RestoreAlreadyInProgressError`.
2. **Velero work (USER flow).** Namespace is deleted, then velero restores everything from the backup. The CRD is recreated with empty status.
3. **Operator quiesce.** While `phase == Restoring`, the operator's `kopf_styrmin_deployment_timer` early-returns — it does not advance phases and does not trip the 300 s readiness-timeout-to-Error branch.
4. **Post-velero recovery (`operator/restore_recovery.py`).** Called from the USER flow after velero polling reports `Completed`:
   - `mark_restoring` — patches the restored CRD to `phase=Restoring` / `displayState=Restoring` so the operator timer recognises the in-flight state.
   - `reapply_and_finalize` — strips kopf state-tracking annotations, re-applies prerequisites (`execute_phase_prerequisites`) and utility resources (`execute_phase_services`), then patches the CRD to `phase=Ready` / `displayState=Running`.
   - `mark_failed` — used on any failure with a message that distinguishes velero failure from post-restore reapply failure.
5. **Final DB transition (INTERNAL flow).** `deployment.status` is moved from `RESTORING` to `RUNNING` (or `FAILED`) inline so the UI reflects the transition immediately rather than waiting on the next agent status poll.

### Display state mapping

The agent's status reporter maps CRD `displayState` to `deployment.status` (see `services/deployment_status.py:_DISPLAY_STATE_TO_STATUS`):

| `DisplayState` | `DeploymentState` |
|----------------|-------------------|
| `Deploying` | `DEPLOYING` |
| `Running` | `RUNNING` |
| `Restoring` | `RESTORING` |
| `Error` | `FAILED` |

## GraphQL API

### Queries

```graphql
backup(backupId: UUID!): Backup
backups(instanceId: UUID!, status: BackupStatus): [Backup!]!
restore(restoreId: UUID!): Restore
restores(backupId: UUID!, status: RestoreStatus): [Restore!]!
backupSchedule(scheduleId: UUID!): BackupSchedule
backupSchedules(deploymentId: UUID!): [BackupSchedule!]!
```

### Mutations

```graphql
createBackup(instanceId: UUID!, name: String): Backup!
deleteBackup(backupId: UUID!): String!
createRestore(backupId: UUID!, targetNamespace: String!, targetInstanceId: UUID): Restore!
createBackupSchedule(deploymentId: UUID!, name: String!, cronExpression: String!, retentionCount: Int, enabled: Boolean): BackupSchedule!
updateBackupSchedule(scheduleId: UUID!, name: String, cronExpression: String, retentionCount: Int, enabled: Boolean): BackupSchedule!
deleteBackupSchedule(scheduleId: UUID!): String!
```

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
controller) so a cycle runs inside the test instead of an hour later.

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
| [services/backup/ttl.py](backend/styrmin_backend/services/backup/ttl.py) | Retention default, validation, and deepest-wins scope resolution |
| [services/backup/scheduler.py](backend/styrmin_backend/services/backup/scheduler.py) | Backup schedule management |
| [services/backup/strategies/](backend/styrmin_backend/services/backup/strategies/) | Backup strategy implementations |
| [workflows/templates/backup.py](backend/styrmin_backend/workflows/templates/backup.py) | Prefect workflow templates for backup/restore |
| [agent/service/kubernetes/resources/builders/backup.py](backend/styrmin_backend/agent/service/kubernetes/resources/builders/backup.py) | Velero CRD builders |
| [agent/service/kubernetes/resources/builders/backup_annotations.py](backend/styrmin_backend/agent/service/kubernetes/resources/builders/backup_annotations.py) | Volume annotation patches |
| [repository/backup.py](backend/styrmin_backend/repository/backup.py) | Backup data access |
| [repository/restore.py](backend/styrmin_backend/repository/restore.py) | Restore data access |
| [repository/backup_schedule.py](backend/styrmin_backend/repository/backup_schedule.py) | Schedule data access |
