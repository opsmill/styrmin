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
    metadata_: dict               # JSON: operation metadata (timeout, etc.)
    restores: list[Restore]       # One-to-many relationship
```

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
| `update_backup_status(backup_id, status, uow, ...)` | Update overall backup status |
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

## Two-Worker Architecture

Backup workflows use a two-worker model:

| Worker | Pool | Responsibilities |
|--------|------|------------------|
| INTERNAL | `styrmin-work-pool` | DB operations, CRD building, status updates, flow dispatch |
| USER | `user-work-pool` (K8s) | Velero CRD creation/polling, in-cluster K8s operations |

Results are passed between workers via **Prefect Variables** (a cross-worker communication channel).

### Workflow Flows (`workflows/templates/backup.py`)

**Backup:**

1. `execute_backup_workflow` (INTERNAL) — marks backup IN_PROGRESS, builds Velero CRD, dispatches to USER flow, updates status from result
2. `execute_velero_backup_flow` (USER) — creates Velero Backup CRD, polls completion, stores result in Prefect Variable

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

## Component Status Tracking

Backups and restores track status at the component level. The overall status is derived from component statuses:

- Any component FAILED -> overall FAILED
- All components COMPLETED -> overall COMPLETED
- Otherwise -> IN_PROGRESS

## Velero Integration

### Builders (`agent/service/kubernetes/resources/builders/backup.py`)

- `build_velero_backup()` — Creates Velero Backup CRD spec with labels, hooks, and TTL
- `build_velero_restore()` — Creates Velero Restore CRD spec with namespace mapping and hooks

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
| [services/backup/scheduler.py](backend/styrmin_backend/services/backup/scheduler.py) | Backup schedule management |
| [services/backup/strategies/](backend/styrmin_backend/services/backup/strategies/) | Backup strategy implementations |
| [workflows/templates/backup.py](backend/styrmin_backend/workflows/templates/backup.py) | Prefect workflow templates for backup/restore |
| [agent/service/kubernetes/resources/builders/backup.py](backend/styrmin_backend/agent/service/kubernetes/resources/builders/backup.py) | Velero CRD builders |
| [agent/service/kubernetes/resources/builders/backup_annotations.py](backend/styrmin_backend/agent/service/kubernetes/resources/builders/backup_annotations.py) | Volume annotation patches |
| [repository/backup.py](backend/styrmin_backend/repository/backup.py) | Backup data access |
| [repository/restore.py](backend/styrmin_backend/repository/restore.py) | Restore data access |
| [repository/backup_schedule.py](backend/styrmin_backend/repository/backup_schedule.py) | Schedule data access |
