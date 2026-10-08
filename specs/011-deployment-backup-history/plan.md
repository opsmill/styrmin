# Implementation Plan: Keep a Deployment's Backup History When It Gets a New Instance

**Branch**: `fac/fix-backup-history-disappears-f8kjf` | **Date**: 2026-10-08 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/011-deployment-backup-history/spec.md`. Source PRD: [issue #304, comment 6070292805](https://github.com/opsmill/styrmin/issues/304#issuecomment-6070292805).

## Summary

The Backups tab, `styrminctl backups list`, `styrminctl backups restore --last` and the `backups` query list only the backups of a deployment's active instance. An upgrade, a config edit, a refresh or an environment config change gives the deployment a new active instance, so the earlier backups drop out of every view.

The fix lists a deployment's backups by deployment id. A new repository method joins `backup` to `applicationinstance` and filters by `applicationinstance.deployment_id`. The `backups` query gains an optional `deploymentId` argument, and `instanceId` becomes optional, with the backup service requiring exactly one of them (ADR-031, `AmbiguousIdentifierError` → `VALIDATION_ERROR`). The SDK, the CLI and the Backups tab list by deployment id and show the application version of each backup's instance, which the `Backup` type already exposes. No database change, no restore change.

## Technical Context

**Language/Version**: Python 3.14+ (backend, SDK, CLI); TypeScript 5.9.3 with React 19 (frontend, Node 22)

**Primary Dependencies**: Strawberry GraphQL, SQLModel and SQLAlchemy (async), Pydantic v2, Cyclopts (CLI), httpx and ariadne-codegen (SDK); TanStack Query v5 and graphql-codegen (frontend). No new dependency (research R10).

**Storage**: PostgreSQL through SQLModel. No schema change and no Alembic revision (research R1).

**Testing**: pytest (unit, functional GraphQL propagation, E2E on vCluster with the API and UI variants); Vitest with React Testing Library (frontend)

**Target Platform**: Styrmin backend on Kubernetes; web UI; `styrminctl` on operator machines

**Project Type**: Web service with a GraphQL API, a Python SDK, a CLI and a React frontend

**Performance Goals**: One SQL query per `backups(deploymentId:)` call. The `instance { applicationVersion }` projection is read through the existing `application_instances` data loader, so a list of N backups reads their instances with one batched query.

**Constraints**: `backups(instanceId:)` results do not change (SC-004). No pagination (spec Out of Scope). No new index, because an index needs an Alembic revision, which the PRD excludes. The number of instances per deployment grows by one per operation and stays small.

**Scale/Scope**: Six modules extended, none created:

- backup repository
- backup service
- `backups` resolver
- SDK backups binding
- `styrminctl backups`
- Backups tab

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | How this plan meets it |
|-----------|--------|------------------------|
| I. Declarative state reconciliation | Pass | No change to reconciliation. The four operations keep creating instances as they do today. |
| II. Driver-based deployment | Pass | No driver change. |
| III. Layered architecture | Pass | The `backups` resolver calls `get_backups` in the backup service, which calls `BackupRepository.get_by_deployment_id` or `get_by_instance_id`. |
| IV. Typed errors | Pass | The "exactly one argument" rule raises `AmbiguousIdentifierError`, a `ServiceError` subclass mapped to `VALIDATION_ERROR` (research R3). No union error types. |
| V. Test-first development | Pass | Unit, functional propagation, four-operation integration, SDK, CLI and frontend tests, plus an extension of `test_backup_and_restore_lifecycle` run in both variants (research R8, R9). GraphQL propagation test for `deploymentId` ships with the change. |
| VI. Format and lint before commit | Pass | `uv run invoke format lint`, `pnpm lint` and `pnpm build` in the task list. |
| VII. Documentation accuracy | Pass | `docs/` pages, `cli/README.md`, CLI help, `dev/knowledge/backend/backup-restore.md`, `CONTEXT.md` and a changelog fragment updated in the same change (research R11). |

**Governance gates** (`AGENTS.md` "Ask First", Constitution "Governance Gates"):

| Gate | Crossed | Note |
|------|---------|------|
| GraphQL schema change | Yes | `backups` gains `deploymentId`; `instanceId` becomes optional. Confirmed in the PRD review session on 2026-10-08. Requires regenerating `schema.graphql` and the SDK and frontend types. |
| Database schema or migration | No | |
| New dependency | No | |
| CI/CD workflow change | No | |
| Authentication or authorization | No | `backups` has no field-level role check; the new argument is on the same field. |
| Skipping E2E, propagation test or docs | No | All three ship with the fix. |

Post-design re-check: no change. The design adds no layer, no error type, no table and no dependency.

## Project Structure

### Documentation (this feature)

```text
specs/011-deployment-backup-history/
├── spec.md
├── plan.md              # this file
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── graphql.md       # backups(deploymentId:, instanceId:, status:)
│   ├── sdk.md           # BackupsResource.list_backups
│   ├── cli.md           # styrminctl backups list / restore --last
│   └── ui.md            # Backups tab
├── checklists/
│   └── requirements.md
└── tasks.md             # created by /speckit-tasks
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── repository/backup.py                      # + BackupRepository.get_by_deployment_id (abstract + SQLModel)
├── services/backup/service.py                # get_backups(uow, *, deployment_id, instance_id, status)
└── api/schema/query.py                       # backups(deployment_id=None, instance_id=None, status=None)

backend/tests/
├── unit/repository/backup/test_backup_repository.py      # extend
├── unit/services/backup/test_backup_service.py           # extend
├── unit/services/fakes.py                                # FakeBackupRepository.get_by_deployment_id
├── functional/graphql/test_backup_history_propagation.py # new: propagation + four operations
├── functional/graphql/operations/list_backup_history.graphql  # new
└── e2e/
    ├── test_backup_restore.py                # extend test_backup_and_restore_lifecycle
    ├── drivers/protocol.py                   # + list_backups(deployment_id)
    ├── drivers/api_driver.py                 # + list_backups
    ├── drivers/ui_driver.py                  # + list_backups
    ├── drivers/refs.py                       # BackupRef.application_version
    └── pages/deployment_detail.py            # read all backup rows + data-backup-application-version

python_sdk/
├── src/styrmin_sdk/graphql/list_backups.graphql   # $deploymentId, $instanceId optional; instance { id applicationVersion }
├── src/styrmin_sdk/graphql/_generated/            # regenerated (uv run invoke generate)
├── src/styrmin_sdk/resources/backups.py           # list_backups(instance_id=None, status=None, *, deployment_id=None)
└── tests/test_backups.py                          # extend

cli/
├── src/styrminctl/resolve.py              # + resolve_deployment_id
├── src/styrminctl/commands/backups.py     # list by deployment, version column, restore --last by deployment
├── tests/test_backups.py                  # extend
└── README.md                              # "Backups and restores"

frontend/src/
├── graphql/list_backups.graphql           # ($deploymentId: UUID!) + instance { id applicationVersion }
├── generated/graphql.ts                   # regenerated
├── pages/deployments/DeploymentDetailPage.tsx  # query by deploymentId; Version column; row attribute
└── __tests__/deployment-detail/
    ├── BackupExpiry.test.tsx              # extend
    └── *.test.tsx                         # update ListBackups fixtures for the new instance field

schema.graphql                             # regenerated
docs/docs/concepts-and-architecture/backups-and-restores.md
docs/docs/reference/styrminctl.md
dev/knowledge/backend/backup-restore.md
CONTEXT.md
changelog/304.fixed.md
```

**Structure Decision**: The existing web-application layout (`backend/`, `frontend/`, `python_sdk/`, `cli/`). Every change extends an existing module.

## Design

### Backend

1. **Repository** (`repository/backup.py`): add `get_by_deployment_id(deployment_id, status=None) -> Sequence[Backup]` to the abstract `BackupRepository` and implement it in `SQLModelBackupRepository` with the join in [data-model.md](data-model.md). Same ordering as `get_by_instance_id`.
2. **Service** (`services/backup/service.py`): change `get_backups` to `get_backups(uow, *, deployment_id=None, instance_id=None, status=None)`. Raise `AmbiguousIdentifierError` when both or neither are set (messages modelled on `resolve_cluster`). Dispatch to the matching repository method. `get_backups` has one caller today, the `backups` resolver.
3. **Resolver** (`api/schema/query.py`): `backups(self, info, deployment_id: UUID | None = None, instance_id: UUID | None = None, status: ... = None)`, with a field description stating the exactly-one rule and the history meaning. The resolver forwards the arguments and does no validation.
4. **Fake repository** (`tests/unit/services/fakes.py`): `FakeBackupRepository.get_by_deployment_id`, walking backup → instance through an `instance_source` wired by `FakeUnitOfWork`, the same way `FakeRestoreRepository` already does.
5. Regenerate `schema.graphql`.

### SDK

`list_backups` signature and variables as in [contracts/sdk.md](contracts/sdk.md). `ListBackups` operation as in [contracts/graphql.md](contracts/graphql.md). Regenerate with `uv run invoke generate`.

### CLI

As in [contracts/cli.md](contracts/cli.md). `resolve_deployment_id(sdk, *, deployment_name, deployment_id, environment) -> str` in `resolve.py` reuses `_resolve_by_name` and validates the name and `--id` selectors, without requiring an active instance. `list_backups` dispatches between instance and deployment. `_prepare_restore` lists by `target.deployment_id` when it is set.

### Frontend

As in [contracts/ui.md](contracts/ui.md). Regenerate types with `pnpm codegen` (through `uv run invoke generate`). Every test that builds a `ListBackupsQuery` backup fixture adds the `instance` field so `tsc -b` passes.

### E2E

As in research R9:

- re-read the active instance before the backup
- after the backup completes, edit the `server` component's env vars, and wait for the deployment to run and its pods to be ready
- assert through the new `list_backups` driver method that the backup is listed with application version `0.1.0`
- revert the env vars in `finally`

The test keeps its markers (`ci`, `shard_backup`) and runs in both variants.

### Documentation

As in research R11.

## Risks

| Risk | Mitigation |
|------|------------|
| The in-place restore in the E2E test includes the HelmRelease, so it may put the pre-edit `server` spec back after the config edit | The restore assertions read Postgres data, not the `server` env var. The `finally` revert re-converges. Fallback in research R9: move the edit and the history check after the restore is verified. |
| Frontend test fixtures typed as `ListBackupsQuery["backups"][number]` fail `tsc -b` once the selection adds `instance` | A task updates every fixture in `frontend/src/__tests__/` that builds one. |
| Other callers rely on `backups(instanceId: UUID!)` being non-null | A non-null variable is valid in a nullable argument; `validate-graphql` checks every existing operation file. |
| `refresh_deployment` has no caller, so only the service-layer test reaches it | Recorded in research R2. The history does not depend on which operation created an instance. |

## Complexity Tracking

No Constitution violations to justify.
