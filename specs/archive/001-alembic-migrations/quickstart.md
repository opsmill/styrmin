# Quickstart: Alembic Migration Management

**Feature**: 001-alembic-migrations | **Date**: 2026-04-04

## Prerequisites

- Python 3.12+
- `uv sync --all-groups` (installs Alembic and all dependencies)

## Common Operations

### Apply All Pending Migrations

```bash
styrmin db migrate
```

### Rollback the Most Recent Migration

```bash
styrmin db downgrade
```

### Check Current Migration Status

```bash
styrmin db status
```

### Initialize a New Database

```bash
styrmin db init
```

This now applies all migrations instead of using `create_all()`.

### Stamp an Existing Database (Transition from create_all)

For databases created before Alembic was introduced:

```bash
styrmin db stamp
```

This marks the database as being at the latest migration version without running any migrations.

## Developer Workflow: Creating a New Migration

When you modify models in `backend/styrmin_backend/db/models.py`:

1. **Make your model changes** (add columns, modify types, add indexes, etc.)

2. **Generate a migration**:
   ```bash
   cd backend
   alembic revision --autogenerate -m "describe your change"
   ```

3. **Review the generated migration** in `backend/styrmin_backend/db/migrations/versions/`

4. **Apply it locally**:
   ```bash
   styrmin db migrate
   ```

5. **Commit the migration file** along with your model changes

## Configuration

Migrations use the same database configuration as the application:

- `STYRMIN_DB_TYPE` — `sqlite` or `postgres`
- `STYRMIN_DB_NAME` — database name or file path
- `STYRMIN_DB_HOST`, `STYRMIN_DB_PORT` — PostgreSQL connection
- `STYRMIN_DB_USERNAME`, `STYRMIN_DB_PASSWORD` — PostgreSQL credentials
- `STYRMIN_DB_URL` — full URL override (takes precedence)

## Testing

Existing tests continue to use in-memory SQLite with `create_all()`/`drop_all()` for isolation. Migration tests are not required for unit tests.
