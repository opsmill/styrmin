# Implementation Plan: Environment-Level Backup and Restore

**Branch**: `001-env-backup-restore` | **Date**: 2026-04-04 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-env-backup-restore/spec.md`

## Summary

Add coordinated environment-level backup and restore operations that compose on top of the existing per-instance Velero backup/restore infrastructure. Two new DB models (`EnvironmentBackup`, `EnvironmentRestore`) act as parent aggregators, linking to existing `Backup`/`Restore` records. A new Prefect INTERNAL workflow orchestrates concurrent constituent backups (with configurable concurrency limit) and updates parent status via callbacks. Exposed via GraphQL mutations/queries, CLI commands (`styrmin env backup`/`styrmin env restore`), and frontend UI on the environment detail page.

## Technical Context

**Language/Version**: Python 3.12+ (backend), TypeScript 5.9.3 (frontend)
**Primary Dependencies**: Strawberry GraphQL, SQLModel, SQLAlchemy (async), Pydantic, Prefect (backend); React 19, urql, Radix UI, TanStack Router (frontend)
**Storage**: PostgreSQL via SQLModel — two new tables (`environmentbackup`, `environmentrestore`) with FKs to existing `environment`, `backup`, `restore` tables
**Testing**: pytest (unit + integration + E2E with real Kind cluster), Vitest + React Testing Library (frontend)
**Target Platform**: Linux server (backend), Browser SPA (frontend)
**Project Type**: Web application (backend + frontend)
**Performance Goals**: Environment backup creation <2s API response (async orchestration); constituent backups run concurrently (default max 5)
**Constraints**: Must reuse existing per-instance backup/restore service and Velero workflow — no new backup strategies. Must not modify existing Backup/Restore behavior (SC-004).
**Scale/Scope**: Environments typically have 3–10 deployments; environment backups may accumulate 10–50 per environment before cleanup

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | N/A | Backup/restore is an operational action, not state reconciliation |
| II. Driver-Based Deployment | PASS | No changes to drivers; backup strategies already exist per driver component |
| III. Layered Architecture | PASS | Design follows GraphQL API → Service Layer → Repository Layer → Database. Async workflows via Prefect with callback-driven status updates |
| IV. Type Safety and Typed Errors | PASS | New GraphQL types will use union types for errors. Python type hints mandatory. Separate domain/DB/context models |
| V. Test-First Development | PASS | Unit tests for service/repository, integration tests for GraphQL, E2E tests for full lifecycle |
| VI. Format and Lint Before Commit | PASS | Standard `uv run invoke format lint` workflow applies |

**Governance Gates:**

| Gate | Status | Action |
|------|--------|--------|
| Database schema changes | REQUIRED | Two new tables — `environmentbackup` and `environmentrestore`. No Alembic; schema via `metadata.create_all()` |
| GraphQL schema modifications | REQUIRED | New types, queries, and mutations for environment backup/restore |
| New dependencies | PASS | No new dependencies — uses existing Strawberry, SQLModel, Prefect stack |
| CI/CD workflow changes | PASS | No CI/CD changes |
| Auth/authz changes | PASS | No auth changes — uses existing context |

**Result: PASS** — All constitution principles satisfied. Governance gates for DB schema and GraphQL changes are acknowledged and justified by the feature requirements.

## Project Structure

### Documentation (this feature)

```text
specs/001-env-backup-restore/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (GraphQL schema)
└── tasks.md             # Phase 2 output (not created by /speckit.plan)
```

### Source Code (repository root)

```text
backend/
├── styrmin_backend/
│   ├── db/models.py                          # + EnvironmentBackup, EnvironmentRestore models
│   ├── repository/
│   │   ├── environment_backup.py             # New repository
│   │   └── environment_restore.py            # New repository
│   ├── services/
│   │   └── backup/
│   │       ├── service.py                    # + env backup/restore service functions
│   │       └── environment.py                # New: environment-level orchestration service
│   ├── api/
│   │   ├── definitions/backup/
│   │   │   ├── environment_backup.py         # New GraphQL type
│   │   │   └── environment_restore.py        # New GraphQL type
│   │   └── schema/
│   │       ├── mutation.py                   # + env backup/restore mutations
│   │       └── query.py                      # + env backup/restore queries
│   ├── workflows/
│   │   ├── models.py                         # + EXECUTE_ENV_BACKUP, EXECUTE_ENV_RESTORE actions
│   │   ├── catalogue.py                      # + register new workflows
│   │   └── templates/
│   │       └── environment_backup.py         # New: Prefect flow for env backup orchestration
│   └── services/unit_of_work.py              # + environment_backups, environment_restores repos
└── tests/
    ├── unit/
    │   └── services/backup/
    │       └── test_environment_backup.py    # New unit tests
    ├── integration/                          # New integration tests
    └── e2e/
        └── test_env_backup_restore.py # New E2E tests

frontend/
├── src/
│   ├── graphql/
│   │   ├── create_environment_backup.graphql     # New
│   │   ├── create_environment_restore.graphql    # New
│   │   ├── list_environment_backups.graphql      # New
│   │   ├── get_environment_backup.graphql        # New
│   │   └── delete_environment_backup.graphql     # New
│   └── pages/environments/
│       └── EnvironmentDetailPage.tsx             # + backup/restore UI section
└── tests/                                        # Frontend component tests
```

**Structure Decision**: Web application layout matching existing `backend/` + `frontend/` split. New files follow established patterns — repositories in `repository/`, services in `services/backup/`, GraphQL types in `api/definitions/backup/`, workflows in `workflows/templates/`.

## Complexity Tracking

No constitution violations to justify — design stays within existing patterns.
