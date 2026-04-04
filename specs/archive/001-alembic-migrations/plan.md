# Implementation Plan: Add Alembic for Database Migration Management

**Branch**: `001-alembic-migrations` | **Date**: 2026-04-04 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-alembic-migrations/spec.md`

## Summary

Integrate Alembic as the versioned database migration framework, replacing `SQLModel.metadata.create_all()` for schema management. The implementation configures Alembic for async operation with SQLModel metadata, generates a baseline migration capturing the full current schema, and adds CLI commands (`styrmin db migrate`, `styrmin db downgrade`, `styrmin db status`) to the existing Cyclopts-based CLI.

## Technical Context

**Language/Version**: Python 3.12+
**Primary Dependencies**: Alembic >=1.14.0, SQLModel >=0.0.31, SQLAlchemy (async), aiosqlite, asyncpg
**Storage**: PostgreSQL (production), SQLite (development) — both via async engines
**Testing**: pytest with in-memory SQLite fixtures (existing pattern preserved)
**Target Platform**: Linux server / macOS development
**Project Type**: Web application (backend only for this feature)
**Performance Goals**: N/A — migrations are offline operations
**Constraints**: Must work with both SQLite and PostgreSQL; async engine integration required
**Scale/Scope**: 15+ models, single migration chain

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | N/A | Migrations are infrastructure, not deployment state |
| II. Driver-Based Deployment | N/A | No driver changes |
| III. Layered Architecture | PASS | Migrations live in db layer; CLI commands go through service functions |
| IV. Type Safety and Typed Errors | PASS | All new code will have type hints; CLI uses Rich for output |
| V. Test-First Development | PASS | Tests for CLI commands; existing test fixtures unchanged |
| VI. Format and Lint Before Commit | PASS | Will run `uv run invoke format lint` |

**Governance Gates:**
- Database schema or migration changes → **This IS the migration system itself. Approved via issue #43.**
- New dependencies → **Alembic is the only new dependency. Well-established, standard choice.**

## Project Structure

### Documentation (this feature)

```text
specs/001-alembic-migrations/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output
```

### Source Code (repository root)

```text
backend/
├── alembic.ini                              # Alembic configuration file
├── styrmin_backend/
│   ├── cli/
│   │   ├── app.py                           # Main CLI (already registers db_app)
│   │   └── db.py                            # Updated: migrate, downgrade, status commands
│   └── db/
│       ├── models.py                        # Existing models (unchanged)
│       ├── utils.py                         # Updated: add get_sync_database_url()
│       ├── constants.py                     # Existing (unchanged)
│       └── migrations/                      # NEW: Alembic migrations directory
│           ├── env.py                       # Async Alembic environment
│           ├── script.py.mako               # Migration template
│           └── versions/                    # Migration scripts
│               └── 0001_initial_schema.py   # Baseline migration
└── tests/
    └── unit/
        ├── cli/
        │   └── test_db.py                   # Updated: tests for new commands
        └── repository/
            └── conftest.py                  # Unchanged (in-memory SQLite)
```

**Structure Decision**: Migrations are colocated with the db layer (`styrmin_backend/db/migrations/`) since they are tightly coupled to the models. `alembic.ini` sits at the `backend/` root where `alembic` commands are run.

## Complexity Tracking

No constitution violations to justify.
