# ADR-003: Adopt Alembic for Database Migration Management

**Status**: Accepted
**Date**: 2026-04-04
**Source**: specs/archive/001-alembic-migrations/research.md (R1, R5, R6, R7)

## Context

Styrmin's database schema was managed via `SQLModel.metadata.create_all()`, which works for development but provides no versioned history of schema changes, no rollback capability, and no safe path for evolving a production database. As the project moves toward production deployments, incremental and reversible schema changes became a prerequisite.

## Decision

Adopt Alembic as the database migration framework, configured for async operation to match the project's exclusive use of `AsyncEngine`. Key design choices:

- **Async env.py**: Uses `asyncio.run()` and `connection.run_sync()` to bridge Alembic's synchronous migration API with the project's async engines.
- **SQLModel.metadata as target**: Alembic autogenerate reads `SQLModel.metadata` directly, keeping model definitions as the single source of truth.
- **Application config for database URL**: `env.py` initializes the app config and calls `get_database_url()` rather than hardcoding URLs in `alembic.ini`.
- **render_as_batch=True**: Enabled unconditionally to support SQLite's limited `ALTER TABLE` operations during development while remaining harmless on PostgreSQL.
- **CLI integration via Cyclopts**: Migration commands (`migrate`, `downgrade`, `status`, `stamp`) are exposed through `styrmin db` subcommands using Alembic's programmatic API, maintaining CLI consistency.
- **Migrations colocated with db layer**: Stored at `backend/styrmin_backend/db/migrations/` alongside models and utils.

## Consequences

- Schema changes are now versioned, reviewable, and deployable through standard release processes.
- Developers must generate migration files when modifying models (`alembic revision --autogenerate`).
- Existing databases created with `create_all()` can transition via `styrmin db stamp`.
- Test fixtures continue using in-memory SQLite with `create_all()`/`drop_all()` for speed — tests do not run through migrations.

## Alternatives Considered

- **Continue with create_all()**: Rejected — no incremental changes, no rollback, no version history.
- **Separate sync engine for migrations**: Rejected — adds complexity of maintaining two engine configurations.
- **Raw SQL migration scripts**: Rejected — error-prone, no autogeneration, no framework support.
- **Exposing raw `alembic` CLI**: Rejected — inconsistent UX with existing `styrmin` CLI commands.
