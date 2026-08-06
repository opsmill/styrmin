# Implementation Plan: Environment Clone

**Branch**: `fac/clone-restore-k93ia` | **Date**: 2026-08-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-env-clone/spec.md`

## Summary

Add environment cloning (issue #6): one ADMIN operation produces a data-bearing copy of a live environment on the same cluster. A new `EnvironmentClone` record tracks the saga — capture a selection-scoped `EnvironmentBackup` (nothing materialises unless it succeeds), create the new environment from captured config plus an operator override, create counterpart deployments through the ordinary `deploy_application` path with fingerprint-pinned driver versions, then run the genuinely new mechanism: **data-only cross-target constituent restore** (scratch-namespace Velero restore with the already-implemented-but-dormant `namespaceMapping`, excluding platform-identity resources, then in-cluster data transfer into the counterpart). Status is derived on read, never stored (ADR-0055 pattern extended with a `finished_at` event for progressive sagas). Ships on all four surfaces with a dual-entrypoint E2E in the existing `shard_backup` scenario.

## Technical Context

**Language/Version**: Python 3.14+ (backend, SDK, CLI); TypeScript 5.9.3 / Node 22 (frontend)

**Primary Dependencies**: Strawberry GraphQL, SQLModel + SQLAlchemy (async), Pydantic v2, Prefect (two new INTERNAL flows — `EXECUTE_ENVIRONMENT_CLONE`, `EXECUTE_CLONE_RESTORE`), Velero (existing install; `namespaceMapping` + `excludedResources` on Restore), Cyclopts + Rich (CLI), httpx + ariadne-codegen (SDK), React 19 + TanStack Query v5 + Radix UI (frontend). **No new dependencies.**

**Storage**: PostgreSQL via SQLModel. One new table (`environmentclone`) + one nullable FK column (`restore.environment_clone_id`); one Alembic revision on head `c1d2e3f4a5b6` (ADR-0001). No new DB enums — clone status is derived, not stored.

**Testing**: pytest — unit (`backend/tests/unit/services/backup/`, flow-level units for the transfer pipeline), GraphQL propagation (`backend/tests/functional/graphql/test_environment_clone.py`), driver conformance (`backend/tests/unit/test_e2e_driver_conformance.py`), E2E (`backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle`, `shard_backup`, dual-entrypoint); Vitest (frontend); mock-based CLI tests (`cli/tests/test_environment_clones.py`).

**Target Platform**: Linux server (backend), modern browsers (frontend), CLI on operator workstations

**Project Type**: Web service (GraphQL) + SPA + CLI + SDK — existing multi-surface monorepo layout

**Performance Goals**: None time-bound by the spec (clone duration is data-dominated). SC-001 is an effort bound: one operation per surface, zero manual per-deployment steps.

**Constraints**: Nothing materialises unless the backup succeeds (FR-002); clone built entirely from the capture — live source never re-read after capture (FR-007); zero silent omissions in attribution (FR-010/SC-003); source never mutated (SC-002); per-instance backup/restore execution machinery reused with **narrow, behaviour-preserving extensions** (selection filter on `create_environment_backup`; target-aware `create_restore` that defaults to today's in-place semantics when no target is given). Post-critique: every saga wait is bounded, with timeout → attributed failure + continue (critique E2); scratch namespaces get a deny-all NetworkPolicy before any restore lands in them (critique E1).

**Scale/Scope**: Environments with tens of deployments; one scratch namespace per constituent restore, deleted unconditionally after transfer.

## Constitution Check

*GATE: evaluated pre-research and re-checked post-design — PASS (no violations; two documented deviations justified below and recorded in the new ADR).*

| Principle | Verdict | How the design complies |
|---|---|---|
| I. Declarative reconciliation | PASS | Counterpart deployments are ordinary deployments created via `deploy_application` and reconciled by the ordinary loop; the clone never applies cluster state outside it. Data restore flips counterparts through the existing `RESTORING → RUNNING` lifecycle. |
| II. Driver-based deployment | PASS | Counterparts bind to captured driver versions (fingerprint-first re-resolution, ADR-0053); data-restore commands are factored from the drivers' declared strategy configs (`component_statuses`), no ad-hoc deployment logic. |
| III. Layered architecture | PASS | Mutation stays thin; validation/creation/derivation live in `services/backup/clone.py`; the two new Prefect flows only sequence service calls — Constitution §III names Prefect as the async-orchestration layer, which is exactly what a multi-wait saga needs (research.md D1). |
| IV. Type safety & typed errors | PASS | New `ServiceError` subclasses reuse existing error codes (`NOT_FOUND`, `ALREADY_EXISTS`, `VALIDATION_ERROR`, `ALREADY_IN_PROGRESS`, `OPERATION_DENIED`); Pydantic models for `DeploymentCloneResult`; full type hints. |
| V. Test-first / E2E DoD / propagation tests | PASS (planned) | Propagation tests for every new field/argument/mutation; derivation property tests; conformance-tuple update for the four new driver methods; dual-entrypoint E2E extending the already-booted `shard_backup` stack (reuse before boot); local PASS evidence recorded per §V for both entrypoints. |
| VI. Format & lint | PASS | Standard `uv run invoke format lint` gates; codegen drift checked by `generate-validate`. |
| VII. Documentation accuracy | PASS (planned) | docs site (backups-and-restores clone section incl. `action`-strategy and `service_name_overrides` limitations, styrminctl reference, glossary, alpha-status check), `dev/knowledge/backend/backup-restore.md`, new ADR (clone record + data-only cross-target restore), `CONTEXT.md` amendments for the D4 concurrency ruling and D5 record deletability. |

**Governance gates crossed** (all named in the spec): database schema change (one Alembic revision, this plan); GraphQL schema modification (contract + propagation tests, this plan); auth surface (new ADMIN mutation following the `restoreEnvironmentBackup` precedent — no new roles, no model change); no new dependencies; no CI/CD changes (the E2E lands in the already-enabled `shard_backup` matrix cells).

**Documented deviations**:

1. **A new Prefect flow, where 001 deliberately used none** — clone has ordered waits (backup terminal, deployment `RUNNING`) that a synchronous service cannot perform; the service-layer-fan-out precedent (ADR-0012/ADR-0055) covers fire-and-forget fan-outs, not sagas (research.md D1).
2. **Spec edge ruling 4 amended**: concurrent clones of one source fail fast with `ALREADY_IN_PROGRESS` instead of running concurrently — the shipped one-environment-operation guard (ADR-0055 D6) is load-bearing and will not be weakened for this feature (research.md D4). Recorded in the alignment check as deliberate drift from the grilled brief.

## Project Structure

### Documentation (this feature)

```text
specs/002-env-clone/
├── plan.md              # This file
├── research.md          # D1–D12 design decisions
├── data-model.md        # Table, JSON shapes, derivation rule
├── quickstart.md        # Validation scenarios
├── contracts/
│   └── graphql.md       # GraphQL types/mutations/queries + SDK/CLI surface
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── db/
│   ├── models.py                          # + EnvironmentClone; nullable FK on Restore
│   └── migrations/versions/
│       └── <newid>_add_environment_clone.py            # down_revision = c1d2e3f4a5b6
├── repository/
│   └── environment_clone.py               # NEW: ABC + SQLModel pair; in-flight-clone EXISTS guard query
├── services/
│   ├── unit_of_work.py                    # register environment_clones repo
│   ├── exceptions.py                      # + EnvironmentCloneNotFoundError / SelectionError / EnvironmentBackupInUseError
│   └── backup/
│       ├── environment.py                 # create_environment_backup: + optional deployment_ids selection;
│       │                                  # delete_environment_backup: + FR-008 in-flight-clone guard
│       ├── service.py                     # create_restore: target-aware (reads target_instance_id; guards/flip on target)
│       └── clone.py                       # NEW: validate/create clone record, derivation, attribution, delete
├── workflows/
│   ├── models.py / catalogue.py           # + EXECUTE_ENVIRONMENT_CLONE, EXECUTE_CLONE_RESTORE
│   └── templates/
│       └── clone.py                       # NEW: INTERNAL saga + INTERNAL per-constituent flow;
│                                          #      K8s-side scratch restore/transfer as a USER flow
│                                          #      (deny-all prelude, Velero restore, transfer, teardown)
├── agent/service/kubernetes/
│   ├── resources/builders/backup.py       # build_velero_restore call sites pass excludedResources (builder param addition)
│   └── velero/hooks.py                    # factor strategy restore-command builders for reuse by the transfer step
└── api/
    ├── definitions/backup/
    │   └── environment_clone.py           # NEW: strawberry types incl. derived status resolver
    └── schema/
        ├── mutation.py                    # + cloneEnvironment (ADMIN) / deleteEnvironmentClone (READ_WRITE)
        └── query.py                       # + environmentClone / environmentClones

schema.graphql                             # re-exported

python_sdk/src/styrmin_sdk/
├── graphql/*.graphql                      # 4 new operation files (contracts/graphql.md)
├── resources/environment_clones.py        # NEW: EnvironmentCloneResource facade + wait_for_clone
├── client.py                              # attach client.environment_clones
└── models/__init__.py                     # public-name aliases

cli/src/styrminctl/
├── commands/environment_clones.py         # NEW: env-clones Cyclopts sub-app
└── cli_commands.py                        # register group

frontend/src/
├── graphql/*.graphql                      # 3 new operation files
├── components/environment/
│   ├── CloneEnvironmentDialog.tsx         # NEW (mirrors CreateEnvironmentDialog; ADMIN-gated)
│   ├── EnvironmentClonesTab.tsx           # NEW (mirrors EnvironmentBackupsTab)
│   └── EnvironmentCloneRow.tsx            # NEW (results expansion, link to created environment)
└── pages/environments/
    ├── EnvironmentListPage.tsx            # + Clone action per row
    └── EnvironmentDetailPage.tsx          # + Clones tab

backend/tests/
├── unit/services/backup/test_environment_clone.py      # NEW: derivation properties, guards, selection, merge
├── unit/repository/backup/test_environment_clone_repository.py  # NEW
├── functional/graphql/test_environment_clone.py        # NEW propagation tests + operations/*.graphql
├── unit/test_e2e_driver_conformance.py                  # + 4 clone methods in the explicit tuple
└── e2e/
    ├── test_backup_restore.py             # + test_environment_clone_lifecycle (ci + shard_backup, dual-entrypoint)
    ├── drivers/{protocol,refs,api_driver,ui_driver}.py  # + clone methods/refs
    └── pages/environments.py              # + clone dialog + Clones tab page objects

cli/tests/test_environment_clones.py       # NEW
frontend/src/__tests__/environments/EnvironmentClone*.test.tsx    # NEW

helm/styrmin/                              # agent RBAC check: pod exec + helper pods in styrmin-* namespaces (if missing)

docs/docs/concepts-and-architecture/backups-and-restores.md   # "Cloning an environment" section
docs/docs/reference/styrminctl.md          # env-clones group
docs/docs/concepts-and-architecture/glossary.md               # entry
docs/docs/alpha-status.md                  # check for an issue-#6 mention
dev/knowledge/backend/backup-restore.md    # clone pipeline + scratch-namespace mechanics
dev/adr/00XX-environment-clone-data-only-cross-target-restore.md  # NEW ADR
CONTEXT.md                                 # amend Environment clone entry (D4 ruling, record deletability)
```

**Structure Decision**: Existing monorepo layout; every addition slots into an established directory with a named sibling as its pattern (`services/backup/environment.py`, `workflows/templates/backup.py`, `api/definitions/backup/environment_backup.py`, `commands/environment_backups.py`, `resources/environment_backups.py`, `components/environment/*`). No new top-level structure.

## Complexity Tracking

Two deliberate deviations, both argued in the Constitution Check and recorded in the new ADR: (1) new Prefect flows for the clone saga (first INTERNAL flows this feature family adds — justified by ordered waits); (2) the concurrency edge ruling amended to fail-fast (guard reuse over guard weakening). No other complexity beyond the established patterns.
