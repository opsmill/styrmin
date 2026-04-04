# Tasks: Add Alembic for Database Migration Management

**Input**: Design documents from `/specs/001-alembic-migrations/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, quickstart.md

**Tests**: Tests are included per the spec requirement (FR-010: existing tests must pass; new CLI commands need tests).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup

**Purpose**: Add Alembic dependency and create migration directory structure

- [ ] T001 Add `alembic` dependency to `backend/pyproject.toml` and run `uv sync --all-groups`
- [ ] T002 Create `backend/alembic.ini` with async template configuration pointing to `styrmin_backend/db/migrations`
- [ ] T003 Create `backend/styrmin_backend/db/migrations/` directory with `__init__.py` and `versions/` subdirectory
- [ ] T004 Create `backend/styrmin_backend/db/migrations/env.py` with async engine support, SQLModel metadata, and app config integration
- [ ] T005 Create `backend/styrmin_backend/db/migrations/script.py.mako` migration template

---

## Phase 2: Foundational (Baseline Migration)

**Purpose**: Generate the initial migration capturing the full current schema

**⚠️ CRITICAL**: No CLI commands can work without a baseline migration

- [ ] T006 Add `get_sync_database_url()` helper to `backend/styrmin_backend/db/utils.py` for Alembic offline mode
- [ ] T007 Generate baseline migration `backend/styrmin_backend/db/migrations/versions/0001_initial_schema.py` that creates all 15+ existing tables with all columns, constraints, indexes, and relationships

**Checkpoint**: Migration infrastructure ready — CLI commands can now be implemented

---

## Phase 3: User Story 1 - Apply Pending Migrations (Priority: P1) 🎯 MVP

**Goal**: Operators can run `styrmin db migrate` to apply all pending migrations

**Independent Test**: Run `styrmin db migrate` against an empty database and verify schema matches model definitions

### Implementation for User Story 1

- [ ] T008 [US1] Add `migrate` command to `backend/styrmin_backend/cli/db.py` using `alembic.command.upgrade(config, "head")`
- [ ] T009 [US1] Add test for `migrate` command in `backend/tests/unit/cli/test_db.py`

**Checkpoint**: `styrmin db migrate` works end-to-end

---

## Phase 4: User Story 2 - Generate Migration from Model Changes (Priority: P1)

**Goal**: Developers can autogenerate migration scripts from model diffs

**Independent Test**: Verify `alembic revision --autogenerate` produces correct migration files

### Implementation for User Story 2

- [ ] T010 [US2] Verify autogenerate works by running `alembic revision --autogenerate -m "test"` in `backend/` and inspecting output (manual validation, no code change needed — env.py from T004 enables this)

**Checkpoint**: Autogeneration workflow validated

---

## Phase 5: User Story 3 - Rollback a Migration (Priority: P2)

**Goal**: Operators can run `styrmin db downgrade` to revert the most recent migration

**Independent Test**: Apply a migration, run downgrade, verify schema reverts

### Implementation for User Story 3

- [ ] T011 [US3] Add `downgrade` command to `backend/styrmin_backend/cli/db.py` using `alembic.command.downgrade(config, "-1")`
- [ ] T012 [US3] Add test for `downgrade` command in `backend/tests/unit/cli/test_db.py`

**Checkpoint**: `styrmin db downgrade` works end-to-end

---

## Phase 6: User Story 4 - Initialize New Database with Migrations (Priority: P2)

**Goal**: `styrmin db init` uses migrations instead of `create_all()`, with `stamp` for existing databases

**Independent Test**: Run `styrmin db init` against empty database, verify schema matches migration result

### Implementation for User Story 4

- [ ] T013 [US4] Update `init` command in `backend/styrmin_backend/cli/db.py` to use `alembic.command.upgrade(config, "head")` instead of `init_db()`
- [ ] T014 [US4] Add `stamp` command to `backend/styrmin_backend/cli/db.py` using `alembic.command.stamp(config, "head")`
- [ ] T015 [US4] Update existing `test_db_init_*` tests in `backend/tests/unit/cli/test_db.py` to reflect new migration-based init
- [ ] T016 [US4] Add test for `stamp` command in `backend/tests/unit/cli/test_db.py`

**Checkpoint**: `styrmin db init` and `styrmin db stamp` work end-to-end

---

## Phase 7: User Story 5 - Check Migration Status (Priority: P3)

**Goal**: Operators can check current migration version and pending migrations

**Independent Test**: Apply some migrations, verify status command shows correct version

### Implementation for User Story 5

- [ ] T017 [US5] Add `status` command to `backend/styrmin_backend/cli/db.py` using `alembic.command.current(config)`
- [ ] T018 [US5] Add test for `status` command in `backend/tests/unit/cli/test_db.py`

**Checkpoint**: `styrmin db status` works end-to-end

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, linting, and final validation

- [ ] T019 Create migration workflow guide in `dev/guides/database-migrations.md`
- [ ] T020 Run `uv run invoke format lint` and fix any issues
- [ ] T021 Run `uv run invoke test` to verify all existing tests still pass
- [ ] T022 Validate quickstart.md scenarios manually

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — T001→T002→T003→T004→T005 (sequential)
- **Foundational (Phase 2)**: Depends on Phase 1 — T006 [P], T007 (T007 depends on T006)
- **US1 (Phase 3)**: Depends on Phase 2 — T008→T009
- **US2 (Phase 4)**: Depends on Phase 2 — T010
- **US3 (Phase 5)**: Depends on Phase 2 — T011→T012
- **US4 (Phase 6)**: Depends on Phase 2 — T013→T014→T015→T016
- **US5 (Phase 7)**: Depends on Phase 2 — T017→T018
- **Polish (Phase 8)**: Depends on all user stories — T019, T020, T021, T022

### User Story Dependencies

- **US1 (P1)**: Independent after Phase 2
- **US2 (P1)**: Independent after Phase 2
- **US3 (P2)**: Independent after Phase 2
- **US4 (P2)**: Independent after Phase 2 (but logically follows US1)
- **US5 (P3)**: Independent after Phase 2

### Parallel Opportunities

- US1 (Phase 3), US3 (Phase 5), US5 (Phase 7) can run in parallel after Phase 2
- T006 can run in parallel with other Phase 2 setup

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (Alembic config + env.py)
2. Complete Phase 2: Foundational (baseline migration)
3. Complete Phase 3: User Story 1 (`styrmin db migrate`)
4. **STOP and VALIDATE**: Test migration against empty database
5. Continue with remaining stories

### Incremental Delivery

1. Setup + Foundational → Migration infrastructure ready
2. Add US1 → `styrmin db migrate` works (MVP!)
3. Add US3 → `styrmin db downgrade` works
4. Add US4 → `styrmin db init` updated + `styrmin db stamp`
5. Add US5 → `styrmin db status` for visibility
6. Polish → Documentation + validation

---

## Notes

- All CLI commands share the same pattern: initialize config, create Alembic Config object, call alembic.command.*
- The Alembic Config object should be created via a shared helper function to avoid duplication
- Existing test fixtures (in-memory SQLite with create_all/drop_all) remain unchanged
- The baseline migration (T007) is the most complex task — it must accurately represent the full current schema
