# Implementation Plan: An In-Place Restore Always Restores Into the Deployment Its Backup Was Taken Of

**Branch**: `fac/remove-targetnamespace-restore-8n884` | **Date**: 2026-10-19 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/031-inplace-restore-target/spec.md`

## Summary

An in-place restore restores a backup into whatever namespace the caller names, and the restore flow deletes that namespace first ([#532](https://github.com/opsmill/styrmin/issues/532)). The fix moves the choice of target to the server:

- A new service function, `resolve_restore_target`, returns the deployment that receives a restore, its namespace `styrmin-<id>` and its active instance. `create_restore` stores both on the `Restore` row and no longer takes a namespace or an instance (research R-001, R-002).
- `createRestore` takes only `backupId`; GraphQL validation refuses the two removed arguments. The Python SDK's `create_restore()` takes only the backup id. The web app stops sending the namespace (R-006, R-009, R-011).
- `styrminctl backups restore` drops `--target-namespace`, and refuses a backup id combined with `--target-deployment`, `--target-deployment-id` or `--target-instance-id` before calling the server. With `--last`, those options keep choosing whose backup history the newest backup comes from (R-010).
- The environment restore and the environment clone stop building the namespace and use the same function (R-004).
- After the change, a restore's namespaces differ exactly when its deployment ids differ, so the Velero Restore and the restore flow agree on every restore (R-016).

## Technical Context

**Language/Version**: Python 3.14+ (backend, SDK, CLI); TypeScript 5.9.3 (frontend)

**Primary Dependencies**: Strawberry GraphQL 0.312.2 and graphql-core 3.2.8 (argument removal and validation), Cyclopts 4.10.1 (CLI), ariadne-codegen (SDK types), graphql-codegen (frontend types), Prefect (unchanged flow contract)

**Storage**: PostgreSQL through SQLModel. No table, column or migration change (R-015).

**Testing**: pytest unit tests (restore target resolution, CLI, SDK), the functional GraphQL test for `createRestore` as the propagation test, and one existing E2E node extended (`test_backup_and_restore_lifecycle`, `shard_backup`, both variants)

**Target Platform**: The Styrmin server, `styrminctl`, the Python SDK and the web app

**Project Type**: Web service with CLI, SDK and SPA clients

**Performance Goals**: N/A. The service reads the deployment it already reads today.

**Constraints**:

- No new server error code (PRD).
- No change to the in-flight restore guard (R-005).
- No change to the restore flow's parameters (R-003).
- No visible change on the Backups tab (R-011).

**Scale/Scope**: About 8 source files and 4 operation files; about 12 test files; 5 documentation files; 2 changelog fragments; regenerated `schema.graphql`, SDK and frontend types.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative state reconciliation | Pass | No change to reconciliation. The restore's target is derived from records, not from client input. |
| II. Driver-based deployment | Pass | No driver change. |
| III. Layered architecture | Pass | The rule lives in the service layer (`resolve_restore_target`). The mutation passes only the backup id. The clone flow and the environment restore call the same service. |
| IV. Type safety and typed errors | Pass | No new error type. `RestoreTarget` is a typed frozen dataclass. GraphQL validation refuses the removed arguments; the errors for a missing backup, an internal or deleted deployment and a restore in flight stay as they are. |
| V. Test-first development | Pass, with the agreed exception | Unit tests for the new function and the CLI; the functional GraphQL test is the propagation test (R-008). No new E2E node: the maintainer agreed to extend `test_backup_and_restore_lifecycle` (PRD; AGENTS.md "Ask First"). Local PASS evidence is required for both variants. |
| VI. Format and lint | Pass | `uv run invoke format lint` and the frontend lint before each commit. |
| VII. Documentation accuracy | Pass | `cli/README.md`, the `styrminctl` reference, the "Backups and restores" page, `dev/knowledge/backend/api.md`, `dev/knowledge/backend/backup-restore.md`, `CONTEXT.md`, and changelog fragments `532.removed.md` and `532.fixed.md` in the same change (R-014). |
| Governance gates | Pass, approved | GraphQL schema modification: two arguments removed from `createRestore`, approved in the PRD. No database, dependency, CI or authorization change. |

Post-design re-check: unchanged. The design adds one service function and one dataclass, and removes parameters from one service function, one mutation, one SDK method, one CLI command and one E2E driver method.

## Project Structure

### Documentation (this feature)

```text
specs/031-inplace-restore-target/
├── spec.md
├── plan.md                      # This file
├── research.md                  # R-001 to R-016
├── data-model.md                # Restore column semantics, RestoreTarget
├── quickstart.md                # Validation steps
├── contracts/
│   ├── graphql-api.md           # createRestore before and after
│   ├── sdk-and-cli.md           # SDK method and styrminctl options
│   └── internal-interfaces.md   # Service function, callers, E2E drivers
├── checklists/requirements.md
└── tasks.md                     # Created by /speckit-tasks
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── services/backup/service.py               # RestoreTarget, resolve_restore_target, create_restore signature, guard docstring
├── services/backup/environment.py           # restore_environment_backup: no namespace building
├── workflows/templates/clone.py             # _dispatch_cross_target_restore: no namespace building
├── repository/deployment.py                 # delete_all_for_environment docstring only (critique E1)
└── api/schema/mutation.py                   # createRestore(backupId)

backend/tests/
├── unit/services/backup/test_restore.py               # resolve_restore_target tests; create_restore calls
├── unit/services/backup/test_environment_clone_service.py
├── unit/services/backup/test_environment_backup.py    # wrappers pass through; assertions on rows
├── functional/graphql/operations/create_restore.graphql
├── functional/graphql/test_create_restore.py          # propagation test, refusal test
├── functional/graphql/test_environment_clone.py
└── e2e/
    ├── drivers/protocol.py, api_driver.py, ui_driver.py
    ├── pages/deployment_detail.py
    ├── test_backup_restore.py                         # lifecycle assertions; other calls
    ├── test_backup_restore_databases.py
    └── test_infrahub_backup_restore.py

python_sdk/
├── src/styrmin_sdk/graphql/create_restore.graphql
├── src/styrmin_sdk/graphql/_generated/              # regenerated
├── src/styrmin_sdk/resources/backups.py
└── tests/test_backups.py

cli/
├── src/styrminctl/commands/backups.py       # restore, _prepare_restore
├── src/styrminctl/types.py                  # help texts of the three target options
├── tests/test_backups.py
└── README.md

frontend/src/
├── graphql/create_restore.graphql
├── generated/graphql.ts                     # regenerated
└── pages/deployments/DeploymentDetailPage.tsx

schema.graphql                               # regenerated
docs/docs/reference/styrminctl.md
docs/docs/concepts-and-architecture/backups-and-restores.md
dev/knowledge/backend/api.md
dev/knowledge/backend/backup-restore.md
CONTEXT.md                                   # committed with the spec
changelog/532.removed.md, changelog/532.fixed.md
```

**Structure Decision**: The existing layout. Every change is inside the restore service, its three callers, and the four clients of `createRestore` (SDK, CLI, web app, E2E drivers).

## Implementation Order

1. Service: `RestoreTarget`, `resolve_restore_target`, the new `create_restore` signature, and the guard docstring, with the unit tests (R-001, R-002, R-005, R-013).
2. Callers: the environment restore and the clone (R-004), with their tests.
3. GraphQL: the mutation, `schema.graphql`, the three operation files, `uv run invoke validate-graphql` and `uv run invoke generate` (R-006). Then the functional propagation and refusal tests (R-007, R-008).
4. SDK method and test (R-009).
5. CLI command, help texts and tests (R-010).
6. Frontend page and type check (R-011).
7. E2E drivers, page object and test calls; the lifecycle assertions; run both variants and record the evidence (R-012).
8. Documentation and changelog fragments (R-014).

Steps 4 to 6 depend on step 3, because they use the regenerated types. Step 7 depends on steps 3 to 6.

## Risks

- **A caller outside the repository passes the removed arguments.** It fails at once with a validation error or a `TypeError`. The changelog fragment of type `removed` says so, and that no replacement exists until deployment clone ships.
- **Clients and server at different versions.** A `styrminctl`, SDK or open web page from before the change sends `targetNamespace` on every restore and the new server refuses it; a client from after the change sends no `targetNamespace` and an older server refuses it. The `removed` fragment says that clients and server must be upgraded together (critique X1).
- **Scripts that follow the old README example.** `styrminctl backups restore <backup id> --target-deployment X` is refused. The refusal message tells the user to run the command again without the option, and the `removed` fragment names the form (critique X1, P4).
- **A test seeds a restore into another namespace through `create_restore`.** Such tests no longer compile. They insert the row through the fake repository instead, which is what an earlier release's row looks like (R-013).
- **The E2E UI variant reads the dialog's namespace.** The page object keeps the check, with the namespace computed from the driver's bound deployment id (R-012).

## Complexity Tracking

No constitution violation to justify.
