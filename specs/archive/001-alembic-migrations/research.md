# Research: Alembic Migration Integration

**Feature**: 001-alembic-migrations | **Date**: 2026-04-04

## 1. Async Engine Integration

**Decision**: Use Alembic's async pattern with `asyncio.run()` in `run_migrations_online()` and `connection.run_sync()` to bridge async/sync.

**Rationale**: This is Alembic's official async cookbook pattern (available since Alembic 1.7+). The project uses `AsyncEngine` exclusively via `create_async_engine` with `aiosqlite` and `asyncpg` drivers. The async env.py template creates an async engine, gets a connection, and uses `run_sync()` to execute migrations synchronously within the async context.

**Alternatives considered**:
- Creating a separate sync engine for migrations only → Rejected: adds complexity of maintaining two engine configurations
- Using `alembic.operations.ops.MigrationScript` with async ops → Rejected: not supported by Alembic

## 2. SQLModel Metadata for Autogenerate

**Decision**: Use `SQLModel.metadata` as `target_metadata` in env.py, with a side-effect import of `styrmin_backend.db.models`.

**Rationale**: All 15+ models are defined in a single `models.py` file and inherit from `StyrminModel(SQLModel)`. Importing this module populates `SQLModel.metadata` with all table definitions. No `declarative_base()` needed — `SQLModel.metadata` is the single source of truth, already used by `init_db()`.

**Alternatives considered**:
- Using a separate `Base` class → Rejected: would duplicate metadata and diverge from existing pattern
- Importing individual models → Rejected: unnecessary since all models are in one file

## 3. Database URL Configuration

**Decision**: Override `sqlalchemy.url` programmatically in env.py using the existing `get_database_url()` function. The `alembic.ini` file contains a placeholder URL.

**Rationale**: The project already has a `get_database_url()` function that constructs the URL from `STYRMIN_DB_*` environment variables via `DatabaseSettings`. Reusing this ensures migrations always connect to the same database as the application.

**Alternatives considered**:
- Hardcoding URL in `alembic.ini` → Rejected: duplicates configuration, diverges from app config
- Using Alembic's `%(VARIABLE)s` interpolation → Rejected: ties Alembic to specific env var naming

## 4. SQLite Compatibility

**Decision**: Enable `render_as_batch=True` unconditionally in `context.configure()`.

**Rationale**: SQLite does not support `ALTER TABLE DROP COLUMN` or most `ALTER TABLE` operations. Alembic's batch mode recreates the table to work around this. It's harmless on PostgreSQL (adds negligible overhead). Since the project uses SQLite for development and PostgreSQL for production, unconditional batch mode ensures migrations work on both.

**Alternatives considered**:
- Conditional batch mode based on dialect → Rejected: adds complexity for no benefit
- SQLite-only development workarounds → Rejected: migrations should be portable

## 5. Migration Directory Location

**Decision**: Place migrations at `backend/styrmin_backend/db/migrations/` with `alembic.ini` at `backend/`.

**Rationale**: Colocating migrations with the db layer keeps related code together. The `alembic.ini` at `backend/` is the standard location since Alembic commands are run from the package root. This matches the project's existing structure where db models, utils, and constants all live under `styrmin_backend/db/`.

**Alternatives considered**:
- Top-level `migrations/` directory at repo root → Rejected: would be outside the Python package
- Separate `alembic/` directory → Rejected: unnecessary indirection

## 6. CLI Integration Approach

**Decision**: Add `migrate`, `downgrade`, and `status` commands to the existing `db_app` Cyclopts app by calling Alembic's programmatic API (`alembic.command.upgrade`, `alembic.command.downgrade`, `alembic.command.current`).

**Rationale**: The project uses Cyclopts for CLI commands. Wrapping Alembic's programmatic API maintains consistency with existing CLI patterns (Rich output, config initialization, error handling). Users interact with `styrmin db migrate` rather than raw `alembic` commands.

**Alternatives considered**:
- Exposing raw `alembic` CLI directly → Rejected: inconsistent UX, requires users to know Alembic
- Adding a separate `migration` subcommand group → Rejected: `db` already exists and is the natural home

## 7. Baseline Migration Strategy

**Decision**: Generate an initial migration that creates all existing tables, representing the current schema as revision 1. Provide a `styrmin db stamp` command for existing databases.

**Rationale**: Existing databases created with `create_all()` already have the correct schema but no Alembic version table. The `stamp` command marks them as being at the baseline version without re-running the migration. New databases get the schema through the migration itself.

**Alternatives considered**:
- Empty baseline + incremental migrations → Rejected: no way to bootstrap a new database
- Dual path (create_all for new, migrations for existing) → Rejected: divergent schema paths
