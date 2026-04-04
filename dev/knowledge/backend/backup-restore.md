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
- **Postgres/Neo4j:** Pre-backup hooks run dump commands, post-restore hooks run restore commands. Default backup volume is `"backup"`
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
| `create_restore(backup_id, target_namespace, uow, ...)` | Create restore from backup |
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

1. `execute_restore_workflow` (INTERNAL) — marks restore IN_PROGRESS, builds Velero CRD, dispatches to USER flow, updates status from result
2. `execute_velero_restore_flow` (USER) — deletes target namespace first, creates Velero Restore CRD, polls completion, stores result in Prefect Variable

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
createBackup(instanceId: UUID!, name: String, timeout: Int): Backup!
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

## Environment-Level Backup & Restore

<!-- Extracted from specs/001-env-backup-restore on 2026-04-05 -->

Environment-level operations coordinate backups and restores across all active application instances in an environment as a single logical unit. They compose on top of the existing per-instance infrastructure — no new Velero logic is introduced.

### Architecture

```text
GraphQL Mutation (createEnvironmentBackup / createEnvironmentRestore)
        |
        v
  Service Layer (services/backup/environment.py)
        |  Creates parent record (EnvironmentBackup/EnvironmentRestore)
        |  Creates constituent Backup/Restore records (one per active instance)
        v
  Prefect Action (EXECUTE_ENV_BACKUP / EXECUTE_ENV_RESTORE)
        |
        v
  INTERNAL Flow (execute_environment_backup_workflow / execute_environment_restore_workflow)
        |   - Marks parent IN_PROGRESS
        |   - Dispatches constituent EXECUTE_BACKUP/EXECUTE_RESTORE via asyncio.gather + Semaphore
        |   - Polls until all constituents reach terminal status
        |   - Recomputes and persists parent status
        v
  Existing per-instance flows handle Velero operations (unchanged)
```

### Parent-Child Status Aggregation

Parent status is derived from constituent statuses:

| Constituent States | Parent Status |
|-------------------|---------------|
| All COMPLETED | COMPLETED |
| All FAILED | FAILED |
| Mix of COMPLETED + FAILED | PARTIALLY_FAILED |
| Any PENDING/IN_PROGRESS | IN_PROGRESS |

The `PARTIALLY_FAILED` status is unique to environment-level operations.

### Data Models

```python
class EnvironmentBackup(StyrminModel, table=True):
    name: str                       # Unique label (auto-generated or user-provided)
    status: EnvironmentBackupStatus # PENDING, IN_PROGRESS, COMPLETED, PARTIALLY_FAILED, FAILED
    environment_id: UUID            # FK to Environment
    max_concurrency: int = 5        # Concurrent constituent limit
    timeout: int = 3600             # Overall timeout (seconds)
    started_at / completed_at / error_message / metadata_
    backups: list[Backup]           # Constituent backups (cascade delete)
    restores: list[EnvironmentRestore]  # Cascade delete

class EnvironmentRestore(StyrminModel, table=True):
    name: str
    status: EnvironmentRestoreStatus
    environment_backup_id: UUID     # FK to EnvironmentBackup
    timeout: int = 7200
    restores: list[Restore]         # Constituent restores (cascade delete)
```

Existing `Backup` and `Restore` models gain nullable FK columns (`environment_backup_id`, `environment_restore_id`) — NULL for standalone operations.

### Service Functions (`services/backup/environment.py`)

| Function | Description |
|----------|-------------|
| `create_environment_backup(environment_id, uow, ...)` | Validate BSL + active instances, create parent + constituents |
| `create_environment_restore(environment_backup_id, uow)` | Validate source status, create parent + constituents for COMPLETED backups only |
| `update_environment_backup_status(id, uow, ...)` | Recompute parent status from constituents |
| `update_environment_restore_status(id, uow, ...)` | Recompute parent status from constituents |
| `get_environment_backup` / `get_environment_backups` | Get by ID / list with optional status filter |
| `get_environment_restore` / `get_environment_restores` | Get by ID / list with optional status filter |
| `delete_environment_backup(id, uow)` | Reject if in-progress ops, cascade delete via SQLAlchemy |

### Validation Rules

- Environment MUST have a BackupStorageLocation assigned
- Environment MUST have ≥1 active instance
- Restore only from COMPLETED or PARTIALLY_FAILED backups
- No concurrent restore from the same EnvironmentBackup
- Cannot delete while any constituent is PENDING or IN_PROGRESS

### Concurrency Limiting

The orchestration flow uses `asyncio.Semaphore(max_concurrency)` to bound concurrent constituent dispatches. See [ADR-004](../../adr/adr-004-composite-parent-child-orchestration.md).

### Key Files

| File | Purpose |
|------|---------|
| [services/backup/environment.py](backend/styrmin_backend/services/backup/environment.py) | Environment backup/restore service functions |
| [workflows/templates/environment_backup.py](backend/styrmin_backend/workflows/templates/environment_backup.py) | Prefect orchestration flows |
| [repository/environment_backup.py](backend/styrmin_backend/repository/environment_backup.py) | EnvironmentBackup data access |
| [repository/environment_restore.py](backend/styrmin_backend/repository/environment_restore.py) | EnvironmentRestore data access |
| [api/definitions/backup/environment_backup.py](backend/styrmin_backend/api/definitions/backup/environment_backup.py) | GraphQL types |

## Default Timeouts

| Operation | Default |
|-----------|---------|
| Backup (per-instance) | 3600s (1 hour) |
| Restore (per-instance) | 7200s (2 hours) |
| Environment Backup | 3600s (1 hour) |
| Environment Restore | 7200s (2 hours) |

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
