# Data Model: Environment-Level Backup and Restore

**Feature Branch**: `001-env-backup-restore`
**Date**: 2026-04-04

## Entity Overview

```
Environment (existing)
├── 1:N EnvironmentBackup (NEW)
│   ├── 1:N Backup (existing, + nullable FK)
│   │   └── 1:N Restore (existing)
│   └── 1:N EnvironmentRestore (NEW)
│       └── 1:N Restore (existing, + nullable FK)
└── BackupStorageLocation (existing, required for env backup)
```

## New Entities

### EnvironmentBackup

Parent record representing a coordinated backup of all active application instances in an environment.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | `UUID` | PK, default `uuid4()` | Inherited from StyrminModel |
| `created_on` | `datetime` | NOT NULL, server default `now()` | Inherited from StyrminModel |
| `updated_on` | `datetime` | server default `now()`, onupdate | Inherited from StyrminModel |
| `name` | `str` | UNIQUE, NOT NULL | Auto-generated or user-provided label (max 128 chars) |
| `status` | `EnvironmentBackupStatus` | NOT NULL, enum | Aggregate status: PENDING, IN_PROGRESS, COMPLETED, PARTIALLY_FAILED, FAILED |
| `started_at` | `datetime \| None` | nullable | Timestamp when first constituent backup starts |
| `completed_at` | `datetime \| None` | nullable | Timestamp when all constituent backups finish |
| `error_message` | `str \| None` | nullable | Error details (timeout, all-failed, etc.) |
| `metadata_` | `dict \| None` | JSON column ("metadata") | Skipped instances, initiator info, concurrency config |
| `max_concurrency` | `int` | NOT NULL, default 5 | Max concurrent constituent backups |
| `timeout` | `int` | NOT NULL, default 3600 | Overall timeout in seconds |
| `environment_id` | `UUID` | FK → `environment.id`, NOT NULL | Source environment |

**Relationships:**
- `environment: Environment` — many-to-one
- `backups: list[Backup]` — one-to-many (via `Backup.environment_backup_id`)
- `restores: list[EnvironmentRestore]` — one-to-many

**Status enum** (`EnvironmentBackupStatus`):
```python
class EnvironmentBackupStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIALLY_FAILED = "partially_failed"
    FAILED = "failed"
```

### EnvironmentRestore

Parent record representing a coordinated restore operation from an EnvironmentBackup.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | `UUID` | PK, default `uuid4()` | Inherited from StyrminModel |
| `created_on` | `datetime` | NOT NULL, server default `now()` | Inherited from StyrminModel |
| `updated_on` | `datetime` | server default `now()`, onupdate | Inherited from StyrminModel |
| `name` | `str` | UNIQUE, NOT NULL | Auto-generated label |
| `status` | `EnvironmentRestoreStatus` | NOT NULL, enum | Aggregate status (same values as backup) |
| `started_at` | `datetime \| None` | nullable | Timestamp when first constituent restore starts |
| `completed_at` | `datetime \| None` | nullable | Timestamp when all constituent restores finish |
| `error_message` | `str \| None` | nullable | Error details |
| `metadata_` | `dict \| None` | JSON column ("metadata") | Restore operation metadata |
| `environment_backup_id` | `UUID` | FK → `environmentbackup.id`, NOT NULL | Source environment backup |

**Relationships:**
- `environment_backup: EnvironmentBackup` — many-to-one
- `restores: list[Restore]` — one-to-many (via `Restore.environment_restore_id`)

**Status enum** (`EnvironmentRestoreStatus`):
```python
class EnvironmentRestoreStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIALLY_FAILED = "partially_failed"
    FAILED = "failed"
```

## Modified Entities

### Backup (existing — add nullable FK)

| Field | Change | Type | Description |
|-------|--------|------|-------------|
| `environment_backup_id` | **ADD** | `UUID \| None` | FK → `environmentbackup.id`, nullable. NULL for standalone backups. |

**New relationship:**
- `environment_backup: EnvironmentBackup | None` — many-to-one (nullable)

**Cascade:** EnvironmentBackup deletion cascades to delete all constituent Backups. Existing Backup → Restore cascade remains unchanged.

### Restore (existing — add nullable FK)

| Field | Change | Type | Description |
|-------|--------|------|-------------|
| `environment_restore_id` | **ADD** | `UUID \| None` | FK → `environmentrestore.id`, nullable. NULL for standalone restores. |

**New relationship:**
- `environment_restore: EnvironmentRestore | None` — many-to-one (nullable)

**Cascade:** EnvironmentRestore deletion cascades to delete all constituent Restores.

## Validation Rules

1. **EnvironmentBackup creation**:
   - Environment MUST have a non-null `backup_storage_location_id` (FR-012)
   - Environment MUST have at least one active application instance across its deployments (FR-013)
   - `name` max length: 128 characters (if user-provided)
   - `max_concurrency` must be ≥ 1
   - `timeout` must be > 0

2. **EnvironmentRestore creation**:
   - Source EnvironmentBackup MUST have status COMPLETED or PARTIALLY_FAILED (not FAILED/PENDING/IN_PROGRESS)
   - No other EnvironmentRestore from the same EnvironmentBackup may be IN_PROGRESS
   - Only constituent Backups with status COMPLETED are eligible for restore

3. **EnvironmentBackup deletion** (FR-010):
   - No constituent Backup may have status PENDING or IN_PROGRESS
   - No constituent Restore may have status PENDING or IN_PROGRESS

## State Transitions

### EnvironmentBackup Status

```
PENDING ──→ IN_PROGRESS ──→ COMPLETED
                         ──→ PARTIALLY_FAILED
                         ──→ FAILED
```

- **PENDING → IN_PROGRESS**: When the orchestration flow starts processing constituent backups
- **IN_PROGRESS → COMPLETED**: All constituent backups reached COMPLETED
- **IN_PROGRESS → PARTIALLY_FAILED**: Some constituent backups COMPLETED, some FAILED
- **IN_PROGRESS → FAILED**: All constituent backups FAILED, or overall timeout exceeded

### EnvironmentRestore Status

Same transitions as EnvironmentBackup, applied to constituent restores.

## Metadata Schema

### EnvironmentBackup.metadata_

```json
{
  "skipped_instances": [
    {
      "instance_id": "uuid",
      "deployment_name": "string",
      "reason": "backup_in_progress | no_backup_config"
    }
  ],
  "initiated_by": "user_or_system",
  "constituent_count": 3,
  "completed_count": 2,
  "failed_count": 1
}
```

### EnvironmentRestore.metadata_

```json
{
  "skipped_backups": [
    {
      "backup_id": "uuid",
      "reason": "backup_not_completed"
    }
  ],
  "constituent_count": 2,
  "completed_count": 2,
  "failed_count": 0
}
```
