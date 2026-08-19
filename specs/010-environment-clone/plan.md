# Implementation Plan: Environment Clone

**Branch**: `010-environment-clone` | **Date**: 2026-08-19 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/010-environment-clone/spec.md`

## Summary

One `ADMIN`-gated operation clones a live environment into a new environment on the
same cluster: capture a fresh environment backup of the selected deployments, then —
only after the capture succeeds — create the new environment (captured config with a
top-level-field override merge), create counterpart deployments pinned to the
captured driver versions, and restore each usable constituent backup into its
counterpart via Velero `namespaceMapping` (cross-target restore). A new
`EnvironmentClone` record tracks the whole operation with status **derived on every
read** (ADR-055 pattern) and 100% per-deployment attribution
(cloned/skipped/failed + reason). Sequencing runs in a new INTERNAL Prefect flow —
the platform's first orchestration that must *wait* on an async capture. Design
decisions: [research.md](research.md) D1–D12.

## Technical Context

**Language/Version**: Python 3.14+ (backend, SDK, CLI); TypeScript 5.9.3 / Node 22 (frontend)

**Primary Dependencies**: Strawberry GraphQL, SQLModel/SQLAlchemy (async), Pydantic v2,
Prefect (one new INTERNAL flow), kubernetes_asyncio (Velero CRDs — `namespaceMapping`
already wired), Cyclopts (CLI), httpx/ariadne-codegen (SDK), React 19 + TanStack
Query v5 (frontend). **No new external dependency** (research D1).

**Storage**: PostgreSQL via SQLModel — one new table `environmentclone`
([data-model.md](data-model.md)) shipped with one Alembic revision (ADR-001). No
stored status column.

**Testing**: pytest — unit (derived status matrix, merge, guards), functional GraphQL
propagation tests (Constitution §V), one dual-entrypoint E2E in `shard_backup`
extending `test_backup_restore.py`; Vitest for frontend components.

**Target Platform**: Linux server (backend) + Kubernetes clusters (vCluster in E2E);
single-cluster scope per ADR-039.

**Project Type**: web service (backend + frontend + SDK + CLI — four-surface parity, FR-012)

**Performance Goals**: clone mutation returns immediately (async); status reads are a
**superset** of the environment-backup envelope (clone row + capture children +
restore rows reachable via JSON ids) — the repository provides a batched restore-row
fetch (one `IN` query across all listed clones) to avoid N+1 on `environmentClones`.
Velero processes restores sequentially cluster-wide, so clone duration is
O(N × restore-time) plus queueing — accepted at the "tens of deployments" scale and
documented so it is not filed as a bug.

**Constraints**: source never mutated (SC-002); nothing materialises unless capture
succeeds (FR-002); clone built only from the capture (FR-007); capture window
serialises with other environment-level operations on the source (research D8).

**Scale/Scope**: environments with ~tens of deployments; clone record JSON attribution
scales linearly with source deployments.

## Constitution Check

*GATE: evaluated pre-Phase-0 and re-checked post-design — PASS with two argued
deviations (see Complexity Tracking).*

- **§I Declarative reconciliation**: counterpart deployments are ordinary deployments;
  after the cross-target restore, recovery re-applies the counterpart's own CR built
  from its instance context, and normal reconciliation owns it from there. Clone adds
  no side-channel state. ✅
- **§II Driver-based deployment**: counterparts created via `deploy_application` with
  `driver_version_id` pinned from the captured fingerprint (ADR-053); no ad-hoc
  deploy logic. ✅
- **§III Layered architecture**: mutation → service (`services/backup/clone.py`) →
  repositories via UnitOfWork; async work in Prefect
  (`EXECUTE_ENVIRONMENT_CLONE`); flows write status via the existing direct-DB
  helpers, matching the backup/restore flows. ✅
- **§IV Typed errors**: new `ServiceError` subclasses
  (`EnvironmentBackupInUseByCloneError` = `IN_USE`, reuse of
  `EnvironmentAlreadyExistsError`, `EnvironmentOperationInProgressError`); no unions. ✅
- **§V Tests**: propagation tests for every new GraphQL element; derived-status unit
  matrix; one heavy dual-entrypoint E2E in `shard_backup` **extending the existing
  backup/restore stack** (reuse-before-you-boot — same session fixtures, active
  consumers exist); local PASS evidence recorded. ✅
- **§VI Format/lint before commit**: `uv run invoke format lint` gates every commit. ✅
- **§VII Documentation**: `docs/docs/concepts-and-architecture/backups-and-restores.md`
  gains a clone section (or sibling page); `docs/docs/reference/styrminctl.md` gains
  `env-clones`; new ADR for the clone record + cross-target restore decisions;
  `dev/knowledge/backend/backup-restore.md` extended; `CONTEXT.md` gains
  **Environment clone**; changelog entry. All in-change. ✅
- **Governance gates** (require explicit discussion — flagged for the reviewer, as
  pre-agreed in the idea brief's "Governance Gates Crossed"): database schema change
  (new table + revision), GraphQL schema modification (mutation + queries + types),
  auth change (new ADMIN mutation). No new dependency; no CI/CD change
  (`shard_backup` exists). ✅

## Project Structure

### Documentation (this feature)

```text
specs/010-environment-clone/
├── plan.md              # This file
├── research.md          # D1–D12 decisions (Phase 0)
├── data-model.md        # EnvironmentClone + derivation (Phase 1)
├── quickstart.md        # Validation guide (Phase 1)
├── contracts/
│   └── graphql.md       # cloneEnvironment + queries + types (Phase 1)
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── db/
│   ├── models.py                          # + EnvironmentClone
│   └── migrations/versions/<new>.py       # + environmentclone revision
├── repository/
│   └── environment_clone.py               # NEW: CRUD, by-source/by-created lookups, batched
│                                          #      restore-row fetch (terminality derives in Python
│                                          #      — not EXISTS-able; see data-model.md)
├── services/
│   ├── unit_of_work.py                    # + environment_clones repo wiring
│   ├── exceptions.py                      # + EnvironmentBackupInUseByCloneError, clone errors
│   ├── deployment.py                      # deploy_application: + skip_initial_reconcile /
│   │                                      #   RESTORING initial state for counterparts;
│   │                                      #   redeploy_for_environment_update skips RESTORING
│   ├── environments.py                    # delete_environment: clone-aware cascades (created-env
│   │                                      #   error write; source-side record handling);
│   │                                      #   update_environment: refuse on under-construction clone
│   └── backup/
│       ├── clone.py                       # NEW: clone_environment service, derivation,
│       │                                  #      selection validation, config merge helper
│       ├── environment.py                 # + deployment_ids filter on create_environment_backup,
│       │                                  #   + clone-aware D8 guard, + D9 delete guard hook
│       └── service.py                     # create_restore: + target_deployment_id (research D2.1)
├── workflows/
│   ├── models.py                          # + EXECUTE_ENVIRONMENT_CLONE action
│   ├── catalogue.py                       # + INTERNAL flow registration
│   └── templates/
│       ├── clone.py                       # NEW: execute_environment_clone_workflow (research D4)
│       └── backup.py                      # execute_restore_workflow: source/status split (D2.2);
│                                          # USER flow: restored CR name (D2.3)
├── operator/
│   └── restore_recovery.py                # counterpart-identity reapply path (D2.4)
├── agent/service/kubernetes/resources/builders/
│   └── backup.py                          # restore labels → counterpart instance (D2.6)
└── api/
    ├── schema/{mutation.py,query.py}      # + cloneEnvironment (ADMIN), environmentClone(s)
    └── definitions/backup/
        └── environment_clone.py           # NEW: types with derived status()

backend/tests/
├── unit/                                  # derivation matrix, merge, guards, cross-target flip
├── functional/graphql/
│   ├── test_environment_clone.py          # NEW: propagation suite
│   └── operations/*.graphql               # named operations
└── e2e/
    ├── test_backup_restore.py             # + test_environment_clone_lifecycle (@ci, shard_backup)
    ├── drivers/{protocol,api_driver,ui_driver,refs}.py   # + clone methods (ADR-038)
    └── pages/environments.py              # + clone dialog/list page objects

python_sdk/src/styrmin_sdk/
├── graphql/{clone_environment,get_environment_clone,list_environment_clones}.graphql
├── resources/environment_clones.py        # NEW: create/get/list/wait_for_clone
└── client.py                              # + environment_clones registration

cli/src/styrminctl/
├── commands/environment_clones.py         # NEW: env-clones create/get/list
└── cli_commands.py                        # + sub-app registration

frontend/src/
├── graphql/{clone_environment,get_environment_clone,list_environment_clones}.graphql
├── components/environment/{CloneEnvironmentDialog,EnvironmentClonesSection}.tsx
└── pages/environments/EnvironmentDetailPage.tsx   # + entry point

schema.graphql                             # regenerated
docs/docs/concepts-and-architecture/backups-and-restores.md   # + clone section
docs/docs/reference/styrminctl.md          # + env-clones
dev/adr/00XX-environment-clone-*.md        # NEW ADR
dev/knowledge/backend/backup-restore.md    # extended
CONTEXT.md                                 # + Environment clone
```

**Structure Decision**: web-application layout already in place (backend + frontend +
python_sdk + cli); the feature is additive within each surface, centered on
`services/backup/clone.py` and one new Prefect flow module.

## Implementation Phases (for /speckit-tasks)

1. **Foundation** — model + revision + repository + UoW wiring + typed errors.
2. **Cross-target restore** — `create_restore(target_deployment_id=...)`, flow
   source/status split, restored-CR-name handling, counterpart-identity reapply,
   label fix (research D2.1–D2.6). Unit-tested in isolation before the clone uses it.
3. **Clone service + flow** — selection validation, capture with filter (D6), merge
   helper (D7), D8 guard extension, `EXECUTE_ENVIRONMENT_CLONE` flow (D4), D9 delete
   guard, derivation (data-model.md).
4. **GraphQL surface** — mutation/queries/types + schema regen + propagation tests.
5. **SDK + CLI** — resources, operations, commands, generate, unit tests.
6. **Frontend** — dialog, clones section, codegen, Vitest.
7. **E2E + docs** — scenario-driver methods, `test_environment_clone_lifecycle`, run
   to local PASS with evidence; docs/ADR/CONTEXT/knowledge updates.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| New guard on `delete_environment_backup` (deviation from ADR-055 decision 6's guard-free escape hatch) | FR-008: deleting the capture while it is still being taken strands unattributable work | Unguarded deletion (status quo) silently kills clones mid-capture; the guard is scoped to the **capture window only** — post-capture deletion stays legal and *is* the escape hatch (drives a stuck clone `FAILED`, attributed; leaves terminal outcomes untouched), so no permanently-wedged state exists (research D9) |
| New INTERNAL Prefect flow (ADR-055 explicitly shipped *no* environment-level flow) | Clone is the first operation that must **wait** on an async capture before materialising anything (FR-002); every existing dispatch is fire-and-forget | Synchronous mutation would hold a GraphQL request for minutes; non-Prefect background work violates Constitution §III (research D4) |
| Clone capture serialises with other env-level ops on the source (refines the idea brief's "concurrent clones, no lock") | Existing one-op-per-environment invariant (ADR-055 decision 5) + per-instance backup guards make truly concurrent captures degrade to `PARTIAL` | Removing the invariant weakens shipped backup/restore semantics for a marginal concurrency win; post-capture independence preserves the brief's intent (research D8) |
