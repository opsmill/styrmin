# Data Model: Environment-Level Backup and Restore

**Feature**: `specs/001-env-backup-restore` | **Date**: 2026-08-06

All tables extend `StyrminModel` (UUID `id`, tz-aware `created_on`/`updated_on`). Schema change ships as one Alembic revision on head `b9c0d1e2f3a4` (see research.md D10). Status is **never stored** for the two parent entities — it is derived (research.md D2).

## New table: `EnvironmentBackup`

| Column | Type | Constraints | Purpose |
|---|---|---|---|
| `name` | `str` | unique, not null | Human-readable snapshot name; defaults to `styrmin-envbackup-<id>` when not supplied |
| `environment_id` | `UUID` | FK → `environment.id`, not null | Owning environment |
| `environment_config` | `dict \| None` | JSON | Verbatim copy of `Environment.config` at backup time (FR-002) |
| `deployment_snapshots` | `list \| None` | JSON | One `DeploymentSnapshot` entry per eligible deployment (FR-003) |
| `constituent_errors` | `list \| None` | JSON | `ConstituentError` entries for constituents that failed at creation (FR-005) |

Relationships: `environment` (many-to-one); `backups` (one-to-many via new nullable FK on `Backup`); `restores` (one-to-many `EnvironmentRestore`).

### `DeploymentSnapshot` (service-layer Pydantic model, stored as JSON)

| Field | Type | Notes |
|---|---|---|
| `deployment_id` | UUID | |
| `deployment_name` | str | Stable even if the deployment is later tombstoned |
| `instance_id` | UUID | The active application instance backed up |
| `driver_name` | str | |
| `driver_version` | str | |
| `driver_fingerprint` | str \| None | Content hash or commit SHA per source type (ADR-0053); clone readiness |
| `application_version` | str | |
| `config` | dict \| None | Deployment config at backup time |
| `parameters` | dict \| None | Deployment parameters at backup time |

### `ConstituentError` (service-layer Pydantic model, stored as JSON)

| Field | Type | Notes |
|---|---|---|
| `deployment_id` | UUID | |
| `deployment_name` | str | |
| `error` | str | Attributable message, e.g. "backup already in progress (existing: <id>)" |

## New table: `EnvironmentRestore`

| Column | Type | Constraints | Purpose |
|---|---|---|---|
| `environment_backup_id` | `UUID` | FK → `environmentbackup.id`, not null | Source snapshot |
| `skipped_constituents` | `list \| None` | JSON | `SkippedConstituent` entries (FR-007) |

Relationships: `environment_backup` (many-to-one); `restores` (one-to-many via new nullable FK on `Restore`). The environment is reached via `environment_backup.environment_id`.

### `SkippedConstituent` (service-layer Pydantic model, stored as JSON)

| Field | Type | Notes |
|---|---|---|
| `deployment_id` | UUID | |
| `deployment_name` | str | |
| `reason` | str | One of the uniform skip reasons: `backup failed at creation`, `backup not completed`, `backup deleted`, `backup expired`, `deployment no longer exists`, `deployment busy with another restore` |

**Expiry classification input (critique E4)**: Velero garbage-collects expired backup data cluster-side but never updates the DB row — an expired constituent still reads `COMPLETED`. Classification computes expiry from the backup's recorded TTL metadata (`expiresAt < now`), the same derivation the existing `Backup.expiresAt` resolver uses. Unit tests must cover an expired-but-`COMPLETED` constituent.

## Modified table: `Backup`

| Column | Change |
|---|---|
| `environment_backup_id` | **New**, `UUID \| None`, FK → `environmentbackup.id`, nullable — mirrors the existing `schedule_id` precedent. Null for standalone per-instance backups. |

## Modified table: `Restore`

| Column | Change |
|---|---|
| `environment_restore_id` | **New**, `UUID \| None`, FK → `environmentrestore.id`, nullable. Null for standalone restores. |

## Derived status (not a column)

Pure function in the service layer, used by both parents:

```
derive(children_statuses: list[terminal|non-terminal], error_count: int) -> Status
  any child PENDING or IN_PROGRESS        -> IN_PROGRESS (all PENDING -> PENDING)
  all terminal:
    completed > 0 and failed+errors == 0  -> COMPLETED
    completed > 0 and failed+errors  > 0  -> PARTIAL
    completed == 0 and failed+errors > 0  -> FAILED
    no children, no errors                -> COMPLETED   (config-only backup, FR-011)
```

For `EnvironmentBackup`: children = linked `Backup` rows; errors = `constituent_errors`. A deleted child simply vanishes from the derivation (parent shows the gap via `deployment_snapshots` minus linked backups — US3).
For `EnvironmentRestore`: children = linked `Restore` rows; errors = `skipped_constituents`.

## State transitions

- `EnvironmentBackup` rows are immutable after creation (snapshot columns written once). Observable status changes only through constituent state changes.
- `EnvironmentRestore` rows are immutable after creation (`skipped_constituents` classified at creation time).
- Constituent `Backup`/`Restore` rows keep their existing lifecycles unchanged (`PENDING → IN_PROGRESS → COMPLETED|FAILED`, driven by the existing Prefect flows).
- Deployment status effects are unchanged: each constituent restore flips its deployment to `RESTORING` via the existing `create_restore` service.

## Validation rules (service layer)

- Create backup: environment must exist (`EnvironmentNotFoundError`); no environment-level operation in progress for the environment (`EnvironmentOperationInProgressError`, `ALREADY_IN_PROGRESS`) — research.md D6.
- Restore: environment backup must exist (`EnvironmentBackupNotFoundError`, `NOT_FOUND`); derived status must be `COMPLETED` or `PARTIAL` (`EnvironmentBackupNotRestorableError`, `OPERATION_DENIED`); same concurrency guard.
- Delete: parent must exist; cascade = per-constituent `delete_backup` + delete `EnvironmentRestore` rows + delete parent (research.md D5). **No status guard** — deletion is legal for an in-progress environment backup (escape hatch, FR-010).
- Environment deletion: `delete_environment` cascades through the environment's environment backups (same per-parent cascade) before deleting the environment row (FR-015) — otherwise the new FK turns environment deletion into a constraint violation.

## Eligibility query (FR-001)

Reuses `uow.deployments.find_all_by_environment(environment_id)` (excludes tombstones by default) with the caller-side filter `not deployment.internal and deployment.active_application_instance_id is not None` — the same shape as the ADR-0012 fan-out loop.
