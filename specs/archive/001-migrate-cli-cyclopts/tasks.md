# Tasks: Migrate styrminctl CLI from Typer to Cyclopts

**Input**: Design documents from `/specs/001-migrate-cli-cyclopts/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md

**Tests**: Included — SC-002 requires 100% command coverage, spec clarification confirms tests written alongside migration per command group.

**Organization**: Tasks are grouped by user story. US1 (migrate commands) is the bulk of work, organized by command group in order of complexity (simplest first, per R8).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Update dependencies and create test infrastructure

- [x] T001 Update dependencies in `cli/pyproject.toml`: replace `typer>=0.16.0,<0.22.0` with `cyclopts>=3.0.0`, keep `rich>=13.0.0`, `pydantic-settings>=2.12.0`, `styrmin-sdk`
- [x] T002 Create test directory and shared fixtures in `cli/tests/conftest.py` (pytest fixtures for mocked `StyrminClient`, `capsys` helpers)
- [x] T003 [P] Create `cli/tests/__init__.py` (empty init for test package)
- [x] T004 Run `uv sync --all-packages` to install updated dependencies

**Checkpoint**: Dependencies updated, test infrastructure ready

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Migrate root app entry point and command registration — MUST complete before any command group migration

**⚠️ CRITICAL**: No command group migration can begin until this phase is complete

- [x] T005 Migrate root app in `cli/src/styrminctl/cli.py`: replace Typer `App` with `cyclopts.App(name="styrminctl", help="Styrmin client CLI.", version=version("cli"))`
- [x] T006 Migrate command group registration in `cli/src/styrminctl/cli_commands.py`: replace `app.add_typer()` calls with `app.command(sub_app)` for all 7 command groups
- [x] T007 Create root app tests in `cli/tests/test_app.py`: test `--help` output, `--version` output, invalid subcommand error handling

**Checkpoint**: Foundation ready — `styrminctl --help` works with Cyclopts, command group migration can begin

---

## Phase 3: User Story 1 — Run Existing CLI Commands with Faster Startup (Priority: P1) 🎯 MVP

**Goal**: Migrate all 35 commands across 7 command groups from Typer to Cyclopts, preserving identical behavior, with tests for each group

**Independent Test**: Run `styrminctl --help` and any existing command — confirm all commands produce identical output and behavior. Time `styrminctl --help` to verify startup improvement.

### 3a: tasks group (2 commands — simplest, validates pattern)

- [x] T008 [US1] Migrate `cli/src/styrminctl/commands/tasks.py`: replace Typer imports with `cyclopts.App`, convert `app` to `tasks_app = App(name="tasks", help="View tasks.")`, convert `@app.command()` to `@tasks_app.command`, move parameter help to docstring `Args:` sections, replace `typer.Exit(code=1)` with `raise SystemExit(1)`
- [x] T009 [US1] Write tests for tasks group in `cli/tests/test_tasks.py`: test `tasks --help`, `tasks list` (with and without `--status`), `tasks get <id>`, error cases returning exit code 1

### 3b: clusters group (4 commands — simple CRUD, establishes standard pattern)

- [x] T010 [P] [US1] Migrate `cli/src/styrminctl/commands/clusters.py`: replace Typer patterns with Cyclopts (App, command decorator, docstring args, SystemExit)
- [x] T011 [US1] Write tests for clusters group in `cli/tests/test_clusters.py`: test `clusters --help`, `create`, `list`, `get`, `delete` commands with mocked `_get_client()`, error cases

### 3c: environments group (4 commands — similar to clusters)

- [x] T012 [P] [US1] Migrate `cli/src/styrminctl/commands/environments.py`: replace Typer patterns with Cyclopts
- [x] T013 [US1] Write tests for environments group in `cli/tests/test_environments.py`: test `environments --help`, `create`, `list`, `get`, `delete` with mocked client

### 3d: drivers group (3 commands — file operations variant)

- [x] T014 [P] [US1] Migrate `cli/src/styrminctl/commands/drivers.py`: replace Typer patterns with Cyclopts
- [x] T015 [US1] Write tests for drivers group in `cli/tests/test_drivers.py`: test `drivers --help`, `create`, `load-version`, `load-local-version` with mocked client

### 3e: backup-locations group (6 commands)

- [x] T016 [P] [US1] Migrate `cli/src/styrminctl/commands/backup_storage_locations.py`: replace Typer patterns with Cyclopts
- [x] T017 [US1] Write tests for backup-locations group in `cli/tests/test_backup_storage_locations.py`: test `backup-locations --help`, `create`, `list`, `get`, `delete`, `assign`, `unassign` with mocked client

### 3f: backups group (9 commands — largest non-deployment group)

- [x] T018 [P] [US1] Migrate `cli/src/styrminctl/commands/backups.py`: replace Typer patterns with Cyclopts
- [x] T019 [US1] Write tests for backups group in `cli/tests/test_backups.py`: test `backups --help`, `create`, `get`, `list`, `delete`, `restore`, `restore-get`, `restore-list` with mocked client, error cases

### 3g: deployments group (10 commands — largest and most complex)

- [x] T020 [P] [US1] Migrate `cli/src/styrminctl/commands/deployments.py`: replace Typer patterns with Cyclopts, handle list parameters for `start-components`/`stop-components`, optional config JSON for `create`/`update`/`run-job`
- [x] T021 [US1] Write tests for deployments group in `cli/tests/test_deployments.py`: test `deployments --help`, all 10 commands (`create`, `get`, `update`, `update-version`, `start-components`, `stop-components`, `run-job`, `context`) with mocked client, error cases

**Checkpoint**: All 35 commands migrated and tested. US1 acceptance scenarios can be validated — all commands produce same output and exit codes.

---

## Phase 4: User Story 2 — Use Async Commands Natively (Priority: P2)

**Goal**: Remove the `AsyncTyper` wrapper entirely; verify all async commands work natively through Cyclopts

**Independent Test**: Verify no `AsyncTyper` wrapper exists in codebase. Run any async command and confirm correct execution.

- [x] T022 [US2] Delete `cli/src/styrminctl/async_typer.py`
- [x] T023 [US2] Remove all remaining `typer` imports across `cli/src/styrminctl/` — grep for any residual `import typer` or `from typer` references
- [x] T024 [US2] Remove `typer` from `cli/pyproject.toml` dependencies (if not already done in T001)
- [x] T025 [US2] Verify all async commands execute correctly by running test suite: `cd cli && uv run pytest tests/ -v`

**Checkpoint**: Zero Typer references remain in codebase. All async commands work natively.

---

## Phase 5: User Story 3 — Consistent CLI Experience Across Project Tools (Priority: P3)

**Goal**: Ensure `styrminctl` and `styrmin` (backend CLI) have consistent command patterns, help formatting, and argument conventions. Add shell completion support.

**Independent Test**: Compare `styrminctl --help` and `styrmin --help` output formatting. Verify shell completions generate for bash, zsh, fish.

- [x] T026 [US3] Add shell completion support via Cyclopts built-in capabilities in `cli/src/styrminctl/cli.py` (FR-008: bash, zsh, fish)
- [x] T027 [US3] Verify help formatting consistency: compare `styrminctl --help` vs `styrmin --help` output style (flag style, description layout, grouping) and adjust App configuration if needed
- [x] T028 [US3] Write shell completion test in `cli/tests/test_app.py`: verify completion generation does not error for supported shells

**Checkpoint**: Both CLIs follow same formatting conventions. Shell completions available.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, documentation, and performance verification

- [x] T029 [P] Run formatter and linter: `uv run invoke format lint`
- [x] T030 [P] Document breaking changes (boolean `--no-<flag>` negation removed, help text layout changes) in appropriate location
- [x] T031 Measure CLI startup performance: time `styrminctl --help` before and after migration, verify >=50% reduction (SC-001)
- [x] T032 Run full test suite and verify 100% command coverage: `cd cli && uv run pytest tests/ -v`
- [x] T033 Run quickstart.md validation checklist against migrated CLI

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all command group migration
- **US1 (Phase 3)**: Depends on Foundational — command groups can be migrated sequentially (recommended) or in parallel
- **US2 (Phase 4)**: Depends on US1 completion (all command files must be migrated before deleting AsyncTyper)
- **US3 (Phase 5)**: Depends on Foundational (Phase 2) — can run in parallel with US1 for shell completions, but help consistency check needs US1 complete
- **Polish (Phase 6)**: Depends on all user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Depends on Foundational (Phase 2). No dependencies on other stories. This IS the migration.
- **User Story 2 (P2)**: Depends on US1 completion — cannot delete AsyncTyper until all command files stop importing it.
- **User Story 3 (P3)**: Depends on Foundational (Phase 2) for shell completions; depends on US1 for help consistency verification.

### Within US1 (Command Group Migration Order)

Per R8 research decision, migrate in order of complexity (simplest first):

1. **tasks** (2 commands) — validates the migration pattern
2. **clusters** (4 commands) — establishes standard CRUD pattern
3. **environments** (4 commands) — similar to clusters
4. **drivers** (3 commands) — file operation variant
5. **backup_storage_locations** (6 commands) — medium complexity
6. **backups** (9 commands) — large group
7. **deployments** (10 commands) — largest and most complex

### Parallel Opportunities

- T001 and T002/T003 can run in parallel (different files)
- Within US1: migration tasks (T010, T012, T014, T016, T018, T020) are marked [P] — they modify different files and can theoretically run in parallel, but **sequential order is recommended** to validate the pattern on simpler groups first
- T029 and T030 can run in parallel (different concerns)

---

## Parallel Example: US1 Command Group Migration

```bash
# Sequential (recommended — validate pattern on simple groups first):
Task T008: Migrate tasks.py → Task T009: Test tasks
Task T010: Migrate clusters.py → Task T011: Test clusters
Task T012: Migrate environments.py → Task T013: Test environments
# ... continue through all groups

# Parallel (if pattern is validated and team has capacity):
Task T010: Migrate clusters.py      | Task T012: Migrate environments.py | Task T014: Migrate drivers.py
Task T011: Test clusters             | Task T013: Test environments       | Task T015: Test drivers
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1 (all 7 command groups migrated + tested)
4. **STOP and VALIDATE**: All 35 commands work identically to Typer version
5. This alone delivers the primary value: faster startup + working CLI

### Incremental Delivery

1. Setup + Foundational → Framework swap in place
2. US1 (command migration) → All commands work → **MVP complete**
3. US2 (AsyncTyper cleanup) → Codebase simplified
4. US3 (shell completions + consistency) → Polish complete
5. Each story adds value without breaking previous stories

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Migration tasks are [P] across groups but sequential execution is recommended per R8
- Each test file should mock `_get_client()` to avoid real API calls (per R7)
- Test pattern: `app(["group", "command", "args"])` + `capsys` + `pytest.raises(SystemExit)` (per R7)
- Commit after each command group migration + tests pass
- Stop at any checkpoint to validate independently
