# Implementation Plan: Environment-Level Backup and Restore

**Branch**: `fac/env-backup-restore-6jtfn` | **Date**: 2026-08-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-env-backup-restore/spec.md`

## Summary

Add coordinated environment-level backup and restore (issue #7): a new `EnvironmentBackup` parent record captures the environment's config and per-deployment declared state, then fans out one constituent backup per eligible deployment through the **unchanged** per-instance backup machinery; a symmetric `EnvironmentRestore` reverts the captured config and fans out constituent restores, skipping-and-reporting anything unusable. Parent status is **derived at read time** from constituents (never stored), making status contradiction structurally impossible. The fan-out follows the ADR-0012 service-layer pattern (per-item isolation, commit-before-dispatch); no new Prefect flows are introduced. Ships on all four surfaces (GraphQL, SDK, CLI `env-backups` group, environment-detail Backups tab) with a dual-entrypoint E2E in the existing `shard_backup` scenario.

## Technical Context

**Language/Version**: Python 3.14+ (backend, SDK, CLI); TypeScript 5.9.3 / Node 22 (frontend)

**Primary Dependencies**: Strawberry GraphQL, SQLModel + SQLAlchemy (async), Pydantic v2, Prefect (existing flows only), Cyclopts + Rich (CLI), httpx + ariadne-codegen (SDK), React 19 + TanStack Query v5 + Radix UI (frontend). **No new dependencies.**

**Storage**: PostgreSQL via SQLModel. Two new tables (`environmentbackup`, `environmentrestore`) + two nullable FK columns (`backup.environment_backup_id`, `restore.environment_restore_id`); one Alembic revision on head `b9c0d1e2f3a4` (ADR-0001). No new DB enums — parent status is derived, not stored.

**Testing**: pytest — unit (`backend/tests/unit/services/backup/`), repository, GraphQL propagation (`backend/tests/functional/graphql/`), E2E (`backend/tests/e2e/test_backup_restore.py`, `shard_backup`, dual-entrypoint); Vitest (frontend); mock-based CLI tests (`cli/tests/`).

**Target Platform**: Linux server (backend), modern browsers (frontend), CLI on developer/operator workstations

**Project Type**: Web service (GraphQL) + SPA + CLI + SDK — existing multi-surface monorepo layout

**Performance Goals**: SC-006 — all constituent backups for a 20-deployment environment enqueued within 60s of request acceptance (sequential fire-and-forget dispatch, ~100ms/`arun_deployment`, leaves >50s headroom)

**Constraints**: Full reuse of per-instance backup/restore machinery — zero changes to `execute_backup_workflow`/`execute_restore_workflow`; derived parent status (FR-004/SC-003); zero silent skips (FR-007); restore never creates/deletes deployments (FR-008)

**Scale/Scope**: Environments with tens of deployments; snapshot JSON of that order (KBs) per backup

## Constitution Check

*GATE: evaluated pre-research and re-checked post-design — PASS (no violations; one documented deviation from a prior ADR's guidance, justified below and recorded in a new ADR).*

| Principle | Verdict | How the design complies |
|---|---|---|
| I. Declarative reconciliation | PASS | Restore reuses the existing lifecycle (`create_restore` flips deployments to `RESTORING`); config revert flows through the existing fan-out with per-deployment no-op detection; re-submitting a restore converges laggards (ADR-0012 recovery property preserved by commit-before-dispatch). |
| II. Driver-based deployment | PASS | No ad-hoc deployment logic: constituent backups reuse driver `component_configs` backup strategies untouched. |
| III. Layered architecture | PASS | New service functions in `services/backup/environment.py`; new repositories registered on `UnitOfWork`; mutations stay thin; flows unchanged. Fan-out lives in the service layer per ADR-0012 (research.md D1). |
| IV. Type safety & typed errors | PASS | New `ServiceError` subclasses (`EnvironmentBackupNotFoundError`, `EnvironmentOperationInProgressError`, `EnvironmentBackupNotRestorableError`) with existing error codes; Pydantic models for snapshot JSON shapes; full type hints. |
| V. Test-first / E2E DoD / propagation tests | PASS (planned) | Propagation tests for every new field/mutation; unit property tests for the derivation rule; dual-entrypoint E2E extending the existing `shard_backup` scenario (reuse before boot — adds one light deployment to an already-booted stack); local PASS evidence recorded per §V. |
| VI. Format & lint | PASS | Standard `uv run invoke format lint` gates; codegen drift checked by `generate-validate`. |
| VII. Documentation accuracy | PASS (planned) | docs site (backups-and-restores, alpha-status — which names issue #7 as "coming before beta" and MUST be edited, styrminctl reference, glossary), `dev/knowledge/backend/backup-restore.md`, new ADR, `CONTEXT.md` (already landed). |

**Governance gates crossed** (all explicitly discussed in the spec/brief): database schema change (Alembic revision, this plan); GraphQL schema modification (contract + propagation tests, this plan); CI/CD change — **one line**: remove the `{entrypoint: ui, shard: backup}` matrix exclusion in `.github/workflows/ci.yml` (~line 240), which that exclusion's own comment instructs when a dual-entrypoint backup test is added. No new dependencies; no auth changes (roles reuse ADR-0017: create/delete `READ_WRITE`, restore `ADMIN` for parity with `updateEnvironment` — research.md D7).

**Documented deviation**: ADR-0012 rejected an "umbrella record" for the config fan-out; this feature introduces exactly such a parent record. Justification: traceability of grouped constituents is the feature's core requirement (issue #7), not incidental bookkeeping. A new ADR records the parent-record + derived-status design and its relationship to ADR-0012 (research.md D11).

## Project Structure

### Documentation (this feature)

```text
specs/001-env-backup-restore/
├── plan.md              # This file
├── research.md          # D1–D11 design decisions
├── data-model.md        # Tables, JSON shapes, derivation rule
├── quickstart.md        # Validation scenarios
├── contracts/
│   └── graphql.md       # GraphQL types/mutations/queries + SDK/CLI surface
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── db/
│   ├── models.py                          # + EnvironmentBackup, EnvironmentRestore; FK cols on Backup/Restore
│   └── migrations/versions/
│       └── <newid>_add_environment_backup_tables.py   # down_revision = b9c0d1e2f3a4
├── repository/
│   └── environment_backup.py              # NEW: EnvironmentBackup + EnvironmentRestore repos (ABC + SQLModel pair)
├── services/
│   ├── unit_of_work.py                    # register environment_backups / environment_restores repos
│   ├── exceptions.py                      # + 3 typed errors
│   ├── environments.py                    # delete_environment: cascade env backups before row delete (FR-015)
│   └── backup/
│       └── environment.py                 # NEW: create/restore/delete env backup, snapshot builder, status derivation, guards
└── api/
    ├── definitions/backup/
    │   ├── environment_backup.py          # NEW: strawberry types incl. derived status resolver
    │   └── environment_restore.py         # NEW
    └── schema/
        ├── mutation.py                    # + createEnvironmentBackup / restoreEnvironmentBackup / deleteEnvironmentBackup
        └── query.py                       # + environmentBackup(s) / environmentRestore(s)

schema.graphql                             # re-exported

python_sdk/src/styrmin_sdk/
├── graphql/*.graphql                      # 7 new operation files (contracts/graphql.md)
├── resources/environment_backups.py       # NEW: EnvironmentBackupResource facade
├── client.py                              # attach client.environment_backups
└── models/__init__.py                     # public-name aliases

cli/src/styrminctl/
├── commands/environment_backups.py        # NEW: env-backups Cyclopts sub-app
├── cli_commands.py                        # register group
└── types.py                               # + EnvironmentBackupId / EnvironmentRestoreId aliases

frontend/src/
├── graphql/*.graphql                      # 5 new operation files
├── components/environment/
│   ├── EnvironmentBackupsTab.tsx          # NEW (replaces the "SOON" stub)
│   └── EnvironmentBackupRow.tsx           # NEW (mirrors BackupRow/RestoreRow split)
└── pages/environments/EnvironmentDetailPage.tsx  # wire tab, drop badge

backend/tests/
├── unit/services/backup/test_environment_backup.py     # NEW: derivation property tests, guards, snapshot capture
├── unit/repository/backup/test_environment_backup_repository.py  # NEW
├── functional/graphql/test_environment_backup.py       # NEW propagation tests + operations/*.graphql
└── e2e/
    ├── test_backup_restore.py             # + test_environment_backup_and_restore_lifecycle (ci + shard_backup)
    ├── drivers/{protocol,refs,api_driver,ui_driver,test_conformance}.py  # + env-backup methods/refs
    └── pages/environments.py              # + env backups tab page object

cli/tests/test_environment_backups.py      # NEW
frontend/src/__tests__/environments/EnvironmentBackups*.test.tsx  # NEW

.github/workflows/ci.yml                   # remove ui/backup matrix exclusion (one line)

docs/docs/concepts-and-architecture/backups-and-restores.md   # env-level section
docs/docs/alpha-status.md                  # remove "coming before beta" bullet for #7
docs/docs/reference/styrminctl.md          # env-backups group
docs/docs/concepts-and-architecture/glossary.md               # 2 entries
dev/knowledge/backend/backup-restore.md    # architecture update
dev/adr/00XX-environment-backup-parent-records.md             # NEW ADR (deviation from ADR-0012 §umbrella)
```

**Structure Decision**: Existing monorepo layout; every addition slots into an established directory with a named sibling as its pattern (`repository/backup.py`, `services/backup/service.py`, `api/definitions/backup/backup.py`, `commands/backups.py`, `resources/backups.py`, `components/environment/*`). No new top-level structure.

## Complexity Tracking

No constitution violations to justify. The single deviation from prior guidance (ADR-0012's rejection of umbrella records) is documented in the Constitution Check above and will be recorded in a new ADR (research.md D11).
