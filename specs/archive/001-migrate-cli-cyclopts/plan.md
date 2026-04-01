# Implementation Plan: Migrate styrminctl CLI from Typer to Cyclopts

**Branch**: `001-migrate-cli-cyclopts` | **Date**: 2026-03-25 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-migrate-cli-cyclopts/spec.md`

## Summary

Migrate the `styrminctl` CLI (35 commands across 7 command groups) from Typer to Cyclopts to improve startup performance, eliminate the custom `AsyncTyper` wrapper, and unify CLI frameworks with the backend `styrmin` CLI. The migration replaces Typer's `App`/`command`/`Option`/`Argument` patterns with Cyclopts' `App`/`@app.command` patterns, adopts `sys.exit(1)` for error handling (replacing `typer.Exit()`), and adds shell completion support via Cyclopts built-in capabilities.

## Technical Context

**Language/Version**: Python 3.12+
**Primary Dependencies**: Cyclopts >=3.0.0 (already in project), Rich >=13.0.0, Pydantic-settings >=2.12.0, styrmin-sdk (local)
**Storage**: N/A (CLI is a thin client over GraphQL API)
**Testing**: pytest (following backend CLI test patterns with `capsys` + `SystemExit` assertions)
**Target Platform**: Linux/macOS (CLI tool)
**Project Type**: Single package (`cli/`)
**Performance Goals**: CLI startup time (`--help`) reduced by >=50% vs Typer baseline (SC-001)
**Constraints**: 100% command compatibility (same names, arguments, behavior); boolean `--no-<flag>` negation dropped as documented breaking change
**Scale/Scope**: 35 commands, 7 command groups, ~1,300 LOC in command files, 0 existing tests

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | N/A | CLI is a client; no reconciliation logic changes |
| II. Driver-Based Deployment | N/A | No driver changes |
| III. Layered Architecture | PASS | CLI remains a thin client calling styrmin-sdk; no layer violations |
| IV. Type Safety and Typed Errors | PASS | All functions retain type hints; mypy enforcement continues |
| V. Test-First Development | PASS | Tests written alongside migration per command group (SC-002) |
| VI. Format and Lint Before Commit | PASS | `uv run invoke format lint` applies to CLI code |

**Governance Gates**:

| Gate | Triggered? | Action |
|------|-----------|--------|
| New dependencies | YES | Cyclopts already in project deps (`>=3.0.0`); Typer is **removed**. Net: dependency swap, not addition. |
| GraphQL schema modifications | NO | No schema changes |
| Database schema changes | NO | No database changes |
| CI/CD workflow changes | NO | No CI changes expected |
| Auth changes | NO | No auth changes |

**Result**: All gates PASS. No violations requiring justification.

## Project Structure

### Documentation (this feature)

```text
specs/001-migrate-cli-cyclopts/
├── plan.md              # This file
├── research.md          # Phase 0: Cyclopts patterns, migration strategy
├── data-model.md        # Phase 1: Command surface area mapping
├── quickstart.md        # Phase 1: Migration quickstart guide
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
cli/
├── pyproject.toml                    # UPDATE: Replace typer dep with cyclopts
├── README.md
└── src/styrminctl/
    ├── __init__.py
    ├── cli.py                        # UPDATE: Entry point (Cyclopts App)
    ├── cli_commands.py               # UPDATE: Command group registration
    ├── async_typer.py                # DELETE: No longer needed
    ├── config.py                     # NO CHANGE: Pydantic-settings config
    ├── output.py                     # NO CHANGE: Rich output utilities
    └── commands/
        ├── __init__.py
        ├── clusters.py               # UPDATE: Migrate to Cyclopts
        ├── environments.py           # UPDATE: Migrate to Cyclopts
        ├── drivers.py                # UPDATE: Migrate to Cyclopts
        ├── deployments.py            # UPDATE: Migrate to Cyclopts
        ├── backups.py                # UPDATE: Migrate to Cyclopts
        ├── backup_storage_locations.py  # UPDATE: Migrate to Cyclopts
        └── tasks.py                  # UPDATE: Migrate to Cyclopts

cli/tests/                            # NEW: Test directory
├── conftest.py                       # NEW: Shared fixtures
├── test_app.py                       # NEW: Root app tests (help, version)
├── test_clusters.py                  # NEW: Cluster command tests
├── test_environments.py              # NEW: Environment command tests
├── test_drivers.py                   # NEW: Driver command tests
├── test_deployments.py               # NEW: Deployment command tests
├── test_backups.py                   # NEW: Backup command tests
├── test_backup_storage_locations.py  # NEW: Backup location command tests
└── test_tasks.py                     # NEW: Task command tests
```

**Structure Decision**: Existing `cli/` package structure is preserved. Migration is an in-place framework swap with no structural changes beyond deleting `async_typer.py` and adding a `tests/` directory.
