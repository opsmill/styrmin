# Feature Specification: Add Alembic for Database Migration Management

**Feature Branch**: `001-alembic-migrations`  
**Created**: 2026-04-04  
**Status**: Draft  
**Input**: User description: "https://github.com/opsmill/styrmin/issues/43"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Apply Pending Migrations (Priority: P1)

A developer or operator deploying a new version of Styrmin needs to apply pending database schema changes to bring their database up to date. They run a single CLI command and all unapplied migrations execute in order, leaving the database at the latest schema version.

**Why this priority**: This is the core value proposition — without the ability to apply migrations, no other migration workflow is useful. It replaces the current `create_all()` approach with a versioned, incremental system.

**Independent Test**: Can be fully tested by creating a database, running migrations, and verifying the resulting schema matches the expected state.

**Acceptance Scenarios**:

1. **Given** a database with no migrations applied, **When** the operator runs `styrmin db migrate`, **Then** all migrations execute sequentially and the database schema matches the current model definitions.

2. **Given** a database at migration version N, **When** a new release adds migration N+1, **Then** running `styrmin db migrate` applies only the new migration.

3. **Given** all migrations are already applied, **When** the operator runs `styrmin db migrate`, **Then** the command completes successfully with a message indicating no pending migrations.

---

### User Story 2 - Generate Migration from Model Changes (Priority: P1)

A developer modifies a SQLModel model (adds a column, changes a type, adds an index) and needs to create a migration script that captures those changes. They run a command that auto-generates a migration file by comparing the current models against the database state.

**Why this priority**: Without autogeneration, developers would need to hand-write SQL migration scripts, which is error-prone and slow. This is essential for the developer workflow.

**Independent Test**: Can be tested by modifying a model, running autogenerate, and verifying the generated migration file contains the expected operations.

**Acceptance Scenarios**:

1. **Given** a model with a new column added, **When** the developer runs `alembic revision --autogenerate`, **Then** a migration file is created that adds the new column.

2. **Given** no model changes since the last migration, **When** the developer runs autogenerate, **Then** the generated migration is empty or a warning indicates no changes detected.

---

### User Story 3 - Rollback a Migration (Priority: P2)

An operator discovers that a recently applied migration caused issues in production. They need to revert the database to the previous schema version to restore stability while the issue is investigated.

**Why this priority**: Rollback capability is a safety net for production. While less frequently used than forward migration, it is critical for incident response.

**Independent Test**: Can be tested by applying a migration, then running downgrade and verifying the schema reverts to the previous state.

**Acceptance Scenarios**:

1. **Given** a database at migration version N, **When** the operator runs `styrmin db downgrade`, **Then** migration N is reversed and the database is at version N-1.

2. **Given** a database at the initial migration, **When** the operator runs `styrmin db downgrade`, **Then** the command warns that no further downgrade is possible.

---

### User Story 4 - Initialize a New Database with Migrations (Priority: P2)

A developer setting up Styrmin for the first time runs the database initialization command. Instead of using `create_all()`, the system applies all migrations from the beginning, ensuring the database is set up through the same path as production upgrades.

**Why this priority**: Ensures consistency between fresh installations and upgraded databases, eliminating a class of "works on my machine" bugs.

**Independent Test**: Can be tested by running `styrmin db init` against an empty database and verifying the schema matches what `styrmin db migrate` would produce.

**Acceptance Scenarios**:

1. **Given** an empty database, **When** the developer runs `styrmin db init`, **Then** all migrations are applied and the database is ready for use.

2. **Given** a database that was previously initialized with `create_all()`, **When** the developer wants to transition to migration-managed, **Then** they can stamp the database at the baseline migration version without re-running migrations.

---

### User Story 5 - Check Migration Status (Priority: P3)

An operator needs to verify what migration version a database is at and whether there are pending migrations before deploying a new release.

**Why this priority**: Useful for operational visibility but not required for the core migration workflow.

**Independent Test**: Can be tested by applying some migrations and verifying the status command reports the correct current version and pending count.

**Acceptance Scenarios**:

1. **Given** a database at migration version N with M pending migrations, **When** the operator runs a status command, **Then** the current version and number of pending migrations are displayed.

---

### Edge Cases

- What happens when a migration fails partway through? The system should roll back the failed migration and report the error clearly.
- How does the system handle concurrent migration attempts? Only one migration process should run at a time.
- What happens when the migration history diverges (e.g., two developers create migrations from the same base)? Alembic's branch detection should flag this.
- What happens when a database was created with `create_all()` and has no migration history? A stamping mechanism allows adopting Alembic on existing databases.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a CLI command (`styrmin db migrate`) to apply all pending database migrations in order.
- **FR-002**: System MUST provide a CLI command (`styrmin db downgrade`) to revert the most recent migration.
- **FR-003**: System MUST support autogeneration of migration scripts from SQLModel/SQLAlchemy model changes.
- **FR-004**: System MUST generate a baseline migration representing the current full schema as the starting point.
- **FR-005**: System MUST support both SQLite (development) and PostgreSQL (production) database backends.
- **FR-006**: System MUST integrate with the project's async database engine configuration.
- **FR-007**: System MUST update the existing `styrmin db init` command to use migrations instead of `create_all()`.
- **FR-008**: System MUST provide a way to stamp an existing database at a specific migration version without running migrations (for transitioning existing databases).
- **FR-009**: System MUST maintain a versioned history of all schema changes as migration files in the repository.
- **FR-010**: Existing tests MUST continue to pass (test fixtures using in-memory SQLite with `create_all`/`drop_all` may remain unchanged for test isolation).
- **FR-011**: Developer documentation MUST be provided covering the migration workflow (creating, applying, and rolling back migrations).

### Key Entities

- **Migration Version**: Represents a specific schema state, identified by a unique revision ID. Each version has an upgrade path (forward) and a downgrade path (backward).
- **Migration Script**: A Python file containing `upgrade()` and `downgrade()` functions that define the schema changes for a specific version.
- **Alembic Configuration**: Settings that connect Alembic to the project's database configuration and model metadata.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Schema changes to models can be deployed to production databases via versioned, reviewable migration files without manual SQL.
- **SC-002**: Developers can generate migration scripts automatically from model diffs in under 30 seconds.
- **SC-003**: Rollbacks can be performed without manual SQL intervention.
- **SC-004**: A fresh database initialized via `styrmin db init` produces an identical schema to a database that has had all migrations applied sequentially.
- **SC-005**: All existing tests continue to pass without modification to test fixtures.

## Assumptions

- Alembic will be configured for async operation using `run_async()` in `env.py` since the project uses async database engines exclusively.
- The in-memory SQLite pattern used in tests will remain unchanged — tests do not need to run through migrations for isolation speed.
- The initial baseline migration will capture the full current schema, allowing existing `create_all()`-based databases to be stamped at this version.
- Migration files will be stored in a `migrations/` directory within the backend package.
