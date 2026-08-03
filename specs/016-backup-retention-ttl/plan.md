# Implementation Plan: Configurable Backup Retention TTL

**Branch**: `fac/fix-backup-ttl-npf7g` | **Date**: 2026-08-03 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/016-backup-retention-ttl/spec.md`

## Summary

Backup retention becomes a first-class, optional config policy: an optional `backup_ttl` field on the shared config base (`BaseConfigSection`, per ADR-029) settable at cluster, environment, and deployment scope, resolved deepest-wins in the backup workflow with an unchanged built-in default of `720h`. The resolved TTL is passed explicitly to the Velero backup builder (both hardcoded `720h` literals removed), recorded on the backup's existing `metadata` JSON column together with Velero's reported expiration, and surfaced as nullable `Backup.ttl` / `Backup.expiresAt` GraphQL fields consumed by the web UI backup list (expiry column + TTL tooltip) and `styrminctl backups list` (Expires column). Typed environment-update and deployment-config inputs carry `backup_ttl` so full-replacement updates cannot silently wipe it. No DB migration, no driver changes, no new dependencies.

## Technical Context

**Language/Version**: Python 3.14+ (backend, SDK, CLI); TypeScript 5.9.3 / Node 22 (frontend)

**Primary Dependencies**: Strawberry GraphQL, SQLModel/SQLAlchemy (async), Pydantic v2, Prefect (workflows), Velero (cluster-side backup engine); React 19, TanStack Query v5, Tailwind (frontend); Cyclopts + Rich (CLI); httpx + ariadne-codegen (SDK)

**Storage**: PostgreSQL via SQLModel. No schema change — `backup_ttl` lives in the existing per-scope `config` JSON columns; applied TTL + expiration live in the existing `Backup.metadata_` JSON column (`metadata`). No Alembic revision needed (note: Alembic IS in use — 17 revisions exist — contrary to the stale `metadata.create_all()` note in AGENTS.md; this plan deliberately avoids needing one).

**Testing**: pytest (unit, functional/propagation, E2E on per-session vCluster); Vitest + React Testing Library (frontend); CLI unit tests via cyclopts app invocation

**Target Platform**: Linux server (backend + Prefect workers), Kubernetes cluster with Velero (agent side), browser SPA, terminal CLI

**Project Type**: Web service + SPA + CLI/SDK monorepo (`backend/`, `frontend/`, `python_sdk/`, `cli/`)

**Performance Goals**: N/A — one extra in-memory dict lookup per backup creation; no hot path affected

**Constraints**: Backup spec must stay byte-identical to today when `backup_ttl` is unset at every scope (FR-003); no modification of existing Velero backups (FR-009); validation must reject malformed values at submission on every input surface (FR-004)

**Scale/Scope**: ~15 source files touched across 4 workspaces + regenerated artifacts (schema.graphql, SDK `_generated/`, frontend `generated/graphql.ts`); 4 GraphQL surface additions (2 input fields, 2 output fields)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| §I Declarative state reconciliation | ✅ PASS | `backup_ttl` is desired state in config; changes ride the standard instance-version + fanout flow, deliberately un-special-cased. Existing backups are immutable history (Velero derives expiration at creation) — documented limitation, not a reconciliation gap. |
| §II Driver-based deployment | ✅ PASS | No driver, component, or template change. Driver templates do not reference the field; env-scope changes produce a Helm-level no-op fanout. |
| §III Layered architecture | ✅ PASS | Config model validates (context layer); workflow/service resolves and records; agent builders stay pure renderers (TTL becomes an explicit required input); GraphQL exposes. No cross-layer calls added. |
| §IV Type safety & typed errors | ✅ PASS | Pydantic-native field validator on `BaseConfigSection` naming the field and hinting syntax; surfaces through the existing `validate_*_config` → `Invalid*ContextError` (ServiceError) path with `extensions.code`. No union-type error handling. No new ServiceError subclass needed (plan-time call per PRD). |
| §V Test-first / E2E required | ✅ PASS | E2E: extend `backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle` (existing `shard_backup` node — "reuse before you boot"; no new node, no new fixture). Unit: validator + resolution + builder suites. Local PASS evidence required per §V. |
| §V GraphQL ↔ DB propagation tests | ✅ PASS | Four covered: `backup_ttl` on `UpdateEnvironmentInput`, `backup_ttl` on `DeploymentConfigInput` (deploy + update paths), `Backup.ttl`, `Backup.expiresAt`. The schema-walking guard (`test_update_environment_input_covers_every_environment_config_field`) enforces the env-input addition mechanically. |
| §VI Format & lint before commit | ✅ PASS | `uv run invoke format lint` in the workflow. |
| §VII Documentation accuracy | ✅ PASS | Same-change updates: `docs/docs/concepts-and-architecture/backups-and-restores.md` (new Retention section + future-backups-only limitation + expired-backup warning), `dev/knowledge/backend/backup-restore.md`, `CONTEXT.md` glossary entry **Backup retention TTL**. |

**Governance gates**:

| Gate | Crossed? | Handling |
|---|---|---|
| DB schema / migration | ❌ No | Avoided by design (ADR-029 config JSON + existing `Backup.metadata_` JSON column). |
| GraphQL schema modification | ✅ Yes | Approved in the source PRD (grilled brief on issue #305). Two input fields + two output fields; requires `schema.graphql` + SDK/frontend regeneration and the four propagation tests. |
| New dependency | ❌ No | Validation is a regex + Pydantic validator; no Go-duration library. |
| CI/CD workflow change | ❌ No | Rides existing shards; no marker changes. |
| Auth change | ❌ No | — |

**Post-design re-check (after Phase 1)**: no new violations introduced; `Complexity Tracking` stays empty.

## Project Structure

### Documentation (this feature)

```text
specs/016-backup-retention-ttl/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── graphql-delta.md # GraphQL surface contract (inputs, outputs, errors)
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── context/
│   ├── models/config.py                 # BaseConfigSection: + backup_ttl field + validator (single home)
│   └── resolvers.py                     # untouched — scalar rides the exclude_none dict spread
├── services/backup/
│   ├── ttl.py                           # NEW: DEFAULT_BACKUP_TTL, GO_DURATION_* validation helper, resolve_backup_ttl()
│   └── service.py                       # update_backup_status(): merge metadata updates (ttl, ttl_source, expires_at)
├── workflows/templates/backup.py        # resolve TTL (deployment→env→cluster→default), log value+scope,
│                                        # pass ttl= to build_velero_backup, propagate status.expiration
├── agent/service/kubernetes/
│   ├── resources/builders/backup.py     # build_velero_backup: ttl becomes required param (720h literal removed)
│   └── velero/resources.py              # VeleroBackup dataclass: ttl required (720h literal removed)
└── api/
    ├── definitions/backup/backup.py     # Backup type: + ttl / expires_at strawberry fields (read metadata_)
    ├── definitions/environment/inputs.py# UpdateEnvironmentInput: + backup_ttl
    └── definitions/deployment/inputs.py # DeploymentConfigInput: + backup_ttl (covers deploy + updateDeployment)

schema.graphql                           # regenerated
python_sdk/src/styrmin_sdk/graphql/
├── list_backups.graphql                 # + ttl expiresAt
├── get_backup.graphql                   # + ttl expiresAt
├── create_backup.graphql                # + ttl expiresAt
└── _generated/                          # regenerated (uv run invoke generate)

cli/src/styrminctl/commands/backups.py   # list: + Expires column; get: + TTL/Expires lines

frontend/src/
├── graphql/list_backups.graphql         # + ttl expiresAt
├── generated/graphql.ts                 # regenerated
├── pages/deployments/DeploymentDetailPage.tsx  # backups tab: + Expires column; BackupRow: expiry cell + TTL tooltip
└── lib/
    ├── deployment-input.ts              # deploymentConfigToInput: map backup_ttl (FR-005 round-trip)
    └── config-diff.ts                   # register backupTtl scalar (diff visibility)

backend/tests/
├── unit/context/test_base_config_section.py      # + parametrised accept/reject cases (FR-004)
├── unit/services/test_backup_ttl_resolution.py   # NEW: precedence hops, fallback, source scope (FR-001/FR-003/FR-006)
├── unit/agent/test_velero_resources.py           # explicit ttl supplied; default assertion relocated
├── unit/agent/test_backup_builders.py            # explicit ttl supplied; default assertion relocated
├── functional/graphql/test_environment_update_propagation.py  # + backup_ttl round-trip (schema-walk guard forces it)
├── functional/graphql/test_update_deployment_input_propagation.py  # + backup_ttl round-trip
├── functional/graphql/test_deploy_input_propagation.py             # + backup_ttl round-trip
├── functional/graphql/test_backup_fields.py      # NEW (or extend existing backup functional tests): Backup.ttl / Backup.expiresAt projection
└── e2e/test_backup_restore.py                    # extend lifecycle test: set env backup_ttl, assert Velero spec.ttl + Backup.ttl/expiresAt

cli/tests/test_backups.py                          # + Expires column cases (value and "—")
frontend/src/__tests__/deployment-detail/BackupExpiry.test.tsx  # NEW: expiry cell renders date / "—", tooltip shows TTL

docs/docs/concepts-and-architecture/backups-and-restores.md  # + Retention section
dev/knowledge/backend/backup-restore.md                      # metadata keys, TTL resolution, Velero integration
CONTEXT.md                                                   # + Backup retention TTL glossary entry
```

**Structure Decision**: Monorepo with four workspaces (`backend/`, `frontend/`, `python_sdk/`, `cli/`) — all touched, plus regenerated artifacts. The single new backend module is `services/backup/ttl.py` (validation constant + pure resolution helper); everything else extends existing files, matching the PRD's "extends, not builds" module list.

## Complexity Tracking

No constitution violations to justify — table intentionally empty.
