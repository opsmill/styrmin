# Implementation Plan: Delete Deployments

**Branch**: `001-delete-deployment` | **Date**: 2026-04-20 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-delete-deployment/spec.md`

## Summary

Add end-to-end support for deleting a Styrmin Deployment. An async GraphQL
mutation soft-deletes (tombstones) the `Deployment` record, creates a
`DELETE_INSTANCE` Task, and launches a Prefect workflow that declares
deletion intent on the `StyrminDeployment` CRD. The existing operator
reconciles the CRD and tears down every owned Kubernetes object
(driver CRs, HelmReleases, utility resources, namespace labels). The
frontend adds a delete action on the deployment detail page, gated by
a confirmation dialog that names the deployment and lets the operator
choose whether to retain or remove associated backups.

Technical approach leans entirely on existing primitives:
`InstanceDeletion` diff + `DELETE_INSTANCE` remediation already exist
but are not yet wired end-to-end; this feature completes that wiring,
adds new lifecycle states, a concurrency guard, an operator-selectable
backup disposition, timeline events, and UI.

## Technical Context

**Language/Version**: Python 3.12 (backend, SDK), TypeScript 5.x /
React 19 (frontend)
**Primary Dependencies**: Strawberry GraphQL, SQLModel, Pydantic,
Prefect, kubernetes_asyncio, Alembic (backend); urql / TanStack React
Query, TanStack Router, Base UI (frontend); GraphQL Codegen
**Storage**: PostgreSQL via SQLModel; Kubernetes API (CRDs) for
cluster state; no schema changes to backup storage
**Testing**: pytest (unit + integration + e2e on a real Kind cluster
with FluxCD/Prefect), Vitest + React Testing Library (frontend)
**Target Platform**: Linux containers (backend), modern evergreen
browsers (frontend)
**Project Type**: Web application — backend + frontend + python_sdk
**Performance Goals**: Delete mutation p95 < 500ms for the accept
path (async, returns after Task creation + Prefect submission).
Cluster teardown wall-clock time bounded by existing reconciliation
latency (no new target).
**Constraints**: Must flow through existing reconciliation +
Prefect workflow mechanisms (Constitution I, II). No new dependencies.
Must not change auth model.
**Scale/Scope**: Per-deployment action, one deployment at a time,
bulk delete out of scope. No anticipated change to request volumes.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Status |
| --- | --- | --- |
| I. Declarative State Reconciliation | Teardown runs via `InstanceDeletion` diff → `DELETE_INSTANCE` remediation → Prefect flow → CRD intent → operator. Re-running on converged (already-deleted) state is idempotent. | PASS |
| II. Driver-Based Deployment | No ad-hoc deletion logic; teardown is expressed through CRD + existing driver-owned resources. | PASS |
| III. Layered Architecture | GraphQL mutation → service (`delete_deployment`) → repository via UoW → DB; Prefect launch via `PrefectManager`. No cross-layer shortcuts. | PASS |
| IV. Type Safety and Typed Errors | New `DeploymentMutationInProgressError` (`ServiceError` subclass) + `StructuredErrorExtension` surfaces `extensions.code`. Full type hints across new code. | PASS |
| V. Test-First Development | Unit (service logic, concurrency guard, backup disposition), integration (GraphQL contract), e2e (Kind: deploy → delete with backup retain vs. remove → verify tombstone + resource teardown). | PASS |
| VI. Format and Lint Before Commit | `uv run invoke format lint` clean; frontend `pnpm lint` + `pnpm tsc --noEmit` clean. | PASS |

### Governance Gates (require explicit discussion before implementation)

Two governance gates are triggered and MUST be confirmed before
implementation begins:

1. **Database schema change**: add `DELETION_REQUESTED`,
   `DELETION_IN_PROGRESS`, `DELETED` to `DeploymentState` enum and an
   Alembic migration. See `data-model.md` for shape.
2. **GraphQL schema modification**: new `deleteDeployment` mutation
   with `deploymentId: UUID!` + `backupDisposition: BackupDisposition!`
   input and `Task!` payload. See `contracts/delete_deployment.graphql`.

No new dependencies, no CI/CD changes, no auth/permissions changes.

### Complexity Tracking

No Constitution violations; no Complexity Tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/001-delete-deployment/
├── plan.md                        # This file
├── spec.md                        # Feature spec (complete)
├── research.md                    # Phase 0 output — key design decisions
├── data-model.md                  # Phase 1 — lifecycle states, entities, transitions
├── quickstart.md                  # Phase 1 — how to try it locally
├── contracts/
│   └── delete_deployment.graphql  # Phase 1 — GraphQL mutation contract
└── checklists/
    └── requirements.md            # Spec quality checklist (passing)
```

### Source Code (repository root)

```text
backend/
├── styrmin_backend/
│   ├── domain/
│   │   └── models.py                       # DeploymentState: add DELETION_* + DELETED
│   ├── db/
│   │   └── models.py                       # DeploymentState mirror + Deployment.deleted_at
│   ├── db/migrations/versions/
│   │   └── XXXX_add_deletion_states.py     # Alembic migration (new enum values + column)
│   ├── services/
│   │   ├── deployment.py                   # NEW: delete_deployment(...)
│   │   ├── errors.py                       # NEW: DeploymentMutationInProgressError
│   │   └── reconciliation/
│   │       ├── diffs/diffs.py              # InstanceDeletion already exists — verify coverage
│   │       └── remediation.py              # InstanceDeletionStrategy wiring to Prefect
│   ├── repository/
│   │   └── deployment.py                   # list_active_tasks(deployment_id) helper
│   ├── workflows/
│   │   ├── models.py                       # PrefectAction.DELETE_INSTANCE (exists) — verify
│   │   └── catalogue.py                    # Register DELETE_INSTANCE workflow definition
│   ├── workflows/flows/
│   │   └── delete_instance.py              # NEW: Prefect flow — declares CRD deletion intent
│   ├── operator/handlers/
│   │   └── styrmin_deployment.py           # Reconcile deletion intent → tear down resources
│   └── api/schema/
│       └── mutation.py                     # NEW: delete_deployment mutation
└── tests/
    ├── unit/services/test_deployment_delete.py                   # NEW
    ├── unit/services/test_deployment_delete_concurrency.py       # NEW
    ├── integration/api/test_delete_deployment_mutation.py        # NEW
    └── e2e/test_deployment_deletion.py                           # NEW

frontend/
├── src/
│   ├── pages/deployments/
│   │   ├── DeploymentDetailPage.tsx        # Add Delete action + wire to dialog
│   │   └── DeleteDeploymentDialog.tsx      # NEW — confirmation + backup choice
│   └── graphql/operations/
│       └── delete_deployment.graphql       # NEW — frontend mutation document
└── src/pages/deployments/
    └── __tests__/DeleteDeploymentDialog.test.tsx  # NEW

python_sdk/
├── src/styrmin_sdk/
│   ├── graphql/delete_deployment.graphql   # NEW — SDK mutation document
│   └── resources/deployments.py            # NEW: delete(deployment_id, backup_disposition)

schema.graphql                              # Regenerated by `uv run styrmin export graphql-schema`
```

**Structure Decision**: Web application (backend + frontend +
python_sdk) — matches the existing monorepo layout. No new top-level
directories introduced; all changes extend existing modules.

## Phase 2 Note

`/speckit.plan` ends here. `/speckit.tasks` (Phase 2) is responsible
for turning the artefacts in this directory into an ordered task
list. Do not pre-generate `tasks.md`.

## Complexity Tracking

> No violations to justify. This feature extends existing primitives
> (UoW, reconciliation diffs, Prefect workflows, operator handlers,
> React dialog patterns) rather than introducing new ones.
