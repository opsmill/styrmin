# Quickstart: Environment-Level Backup and Restore

**Feature Branch**: `001-env-backup-restore`

## Prerequisites

- Styrmin backend running with Prefect worker
- PostgreSQL database (schema will auto-create new tables via `metadata.create_all()`)
- At least one environment with:
  - A BackupStorageLocation assigned
  - One or more deployments with active application instances

## Implementation Order

### Step 1: Database Models

Add to `backend/styrmin_backend/db/models.py`:

1. `EnvironmentBackupStatus` enum (5 values: PENDING, IN_PROGRESS, COMPLETED, PARTIALLY_FAILED, FAILED)
2. `EnvironmentRestoreStatus` enum (same 5 values)
3. `EnvironmentBackup` model (extends StyrminModel)
4. `EnvironmentRestore` model (extends StyrminModel)
5. Add nullable `environment_backup_id` FK to existing `Backup` model
6. Add nullable `environment_restore_id` FK to existing `Restore` model

### Step 2: Repositories

Create:
- `backend/styrmin_backend/repository/environment_backup.py` — `EnvironmentBackupRepository` + `SQLModelEnvironmentBackupRepository`
- `backend/styrmin_backend/repository/environment_restore.py` — `EnvironmentRestoreRepository` + `SQLModelEnvironmentRestoreRepository`

Register in `UnitOfWork` (`backend/styrmin_backend/services/unit_of_work.py`):
- `environment_backups: EnvironmentBackupRepository`
- `environment_restores: EnvironmentRestoreRepository`

### Step 3: Service Layer

Create `backend/styrmin_backend/services/backup/environment.py`:

```python
# Key functions:
async def create_environment_backup(environment_id, uow, name=None, max_concurrency=5, timeout=3600) -> EnvironmentBackup
async def create_environment_restore(environment_backup_id, uow) -> EnvironmentRestore
async def get_environment_backup(environment_backup_id, uow) -> EnvironmentBackup
async def get_environment_backups(environment_id, uow, status=None) -> list[EnvironmentBackup]
async def get_environment_restore(environment_restore_id, uow) -> EnvironmentRestore
async def get_environment_restores(environment_backup_id, uow, status=None) -> list[EnvironmentRestore]
async def delete_environment_backup(environment_backup_id, uow) -> None
async def update_environment_backup_status(environment_backup_id, status, uow, ...) -> EnvironmentBackup
async def update_environment_restore_status(environment_restore_id, status, uow, ...) -> EnvironmentRestore
```

### Step 4: Prefect Workflows

Add to `PrefectAction` enum:
- `EXECUTE_ENV_BACKUP = "execute_env_backup"`
- `EXECUTE_ENV_RESTORE = "execute_env_restore"`

Create `backend/styrmin_backend/workflows/templates/environment_backup.py`:

```python
@flow(name="execute_env_backup")
async def execute_environment_backup_workflow(environment_backup_id: str):
    # 1. Load EnvironmentBackup + constituent Backups
    # 2. Mark parent as IN_PROGRESS
    # 3. For each constituent, dispatch PrefectAction.EXECUTE_BACKUP via asyncio.gather + Semaphore
    # 4. Track completions, update parent status
    # 5. Handle timeout

@flow(name="execute_env_restore")
async def execute_environment_restore_workflow(environment_restore_id: str):
    # Similar pattern for restores
```

Register in `catalogue.py`.

### Step 5: GraphQL Types + Schema

Create GraphQL types:
- `backend/styrmin_backend/api/definitions/backup/environment_backup.py`
- `backend/styrmin_backend/api/definitions/backup/environment_restore.py`

Add to `mutation.py`:
- `create_environment_backup(environment_id, name, max_concurrency, timeout)`
- `create_environment_restore(environment_backup_id)`
- `delete_environment_backup(environment_backup_id)`

Add to `query.py`:
- `environment_backup(environment_backup_id)`
- `environment_backups(environment_id, status)`
- `environment_restore(environment_restore_id)`
- `environment_restores(environment_backup_id, status)`

### Step 6: Regenerate Schema + SDK

```bash
uv run styrmin export graphql-schema schema.graphql
uv run invoke generate
```

### Step 7: Frontend

Add GraphQL operation files to `frontend/src/graphql/`.
Add backup/restore section to Environment detail page.

### Step 8: CLI

Add `styrmin env backup create|list|get|delete` and `styrmin env restore create|list|get` commands.

### Step 9: Tests

- Unit tests for service functions
- Integration tests for GraphQL queries/mutations
- E2E tests for full backup/restore lifecycle

## Verification

```bash
# Backend
uv run invoke format lint
uv run invoke test

# Schema
uv run styrmin export graphql-schema schema.graphql
uv run invoke generate
uv run invoke validate-graphql

# Frontend
cd frontend && pnpm test
```
