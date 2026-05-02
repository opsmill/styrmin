# Implementation Plan: Deployment Deletion

**Branch**: `008-deployment-deletion` | **Date**: 2026-05-01 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/008-deployment-deletion/spec.md`

## Summary

Operators get a first-class **Delete** action exposed both as a GraphQL mutation (`deleteDeployment(id) -> Task!`) and as a button on the deployment detail page. The mutation is *thin*: its only side effect is to patch a new monotonic boolean `spec.deletionRequested` on the cluster-side `StyrminDeployment` CR and emit a `DELETE_DEPLOYMENT` task that is born complete. Every subsequent state transition is observed off the cluster — the existing operator reconciles the spec flip and tears down resources in reverse order (Services → HelmRelease → NetworkPolicies/Secrets → namespace), and the existing status reporter projects the resulting `displayState`/`phase` updates back to the database. On terminal `DELETED`, the backend sets `Deployment.deleted_at` (soft-delete tombstone). The cluster-side CR is garbage-collected by a new kopf timer ~6h after `phase: Deleted`, configurable per cluster via `DELETED_CR_TTL_HOURS`. The frontend gates the destructive action behind a type-to-confirm dialog and adds a `Show deleted` toggle to the list view; tombstoned detail pages are reachable forever and read-only.

## Technical Context

**Language/Version**: Python 3.13 (backend, SDK, operator); TypeScript 5 + React 19 (frontend).
**Primary Dependencies**: Strawberry (GraphQL), SQLModel + Alembic (DB), kopf + kr8s (operator), Pydantic (CRD models). Frontend: urql, Base UI, Tailwind, Vite.
**Storage**: PostgreSQL via SQLModel (`Deployment`, `Task`, `DeploymentTimelineEvent`); Kubernetes etcd via the `StyrminDeployment` CRD.
**Testing**: pytest (unit + GraphQL propagation + E2E via vcluster); Vitest + React Testing Library (frontend). E2E suite lives in `backend/tests/e2e/`. Playwright drives the UI variant.
**Target Platform**: Kubernetes-managed clusters; backend/SDK on Linux (server side), frontend in modern browsers.
**Project Type**: Web application (backend + frontend + SDK + operator) — uses Option 2 (Web application) directory layout.
**Performance Goals**: Deletion mutation acks in < 2s (Spec SC-002); end-state observability bounded by existing reconciliation cadence (no new orchestration is introduced).
**Constraints**: No new long-running Prefect flow. `deleted_at` is set *only* on the `→ DELETED` transition. CRD CEL transition rule requires Kubernetes ≥ 1.25 (already the project baseline). No new external dependencies.
**Scale/Scope**: Single deployment per delete call (no bulk). Cluster-side CR retention is per-cluster. Adds 1 mutation, 1 query argument, 1 scalar field, 2 new lifecycle states (and 2 new CRD enum values), 1 CRD spec field, 1 DB column, 1 task type, 1 timeline event type, 1 SDK method, 1 frontend dialog, 1 list toggle.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| **I. Declarative State Reconciliation** | ✅ PASS | Mutation only writes to *desired* state (`spec.deletionRequested`). All observed state flows through the existing reconciler. Deletion is idempotent — second mutation finds the in-flight task and returns it unchanged. |
| **II. Driver-Based Deployment** | ✅ PASS (N/A) | Drivers are not touched — teardown is handled by the existing operator reconciler against already-deployed resources. |
| **III. Layered Architecture** | ✅ PASS | Resolver → service (`delete_deployment`) → repository (`Deployment`, `Task`, timeline) → DB. CRD patch is encapsulated in the service via the existing kr8s client; resolver does not touch Kubernetes directly. UnitOfWork wraps the DB+task write. **No Prefect flow**, by design (matches the spec's "state-driven, not orchestration-driven" requirement). |
| **IV. Type Safety and Typed Errors** | ✅ PASS | New service exceptions (`DeploymentNotFoundError` reused for already-deleted; `DeploymentRestoringError` and `DeploymentAlreadyTerminalError` added if not present) extend `ServiceError`. Resolver returns `Task!` (non-null) on success; failures surface via `StructuredErrorExtension` with codes documented in `contracts/errors.md`. |
| **V. Test-First Development (E2E + Propagation)** | ✅ PASS | Mandated by spec: `test_delete_deployment_api` (api_only) and `test_delete_deployment_ui` (ui_only) plus full propagation coverage (`spec.deletionRequested`, `DisplayState.Deleting/Deleted`, `DeploymentState.DELETING/DELETED`, `deployments(includeDeleted)`, `Deployment.deletedAt`, `TaskType.DELETE_DEPLOYMENT`, `deleteDeployment` mutation). Definition of done = both E2E pass + propagation tests pass. |
| **VI. Format and Lint Before Commit** | ✅ PASS | `uv run invoke format lint` is in the gate per the project pre-commit hooks; the implementation phase runs it before committing. |

**Governance gates triggered (require explicit acknowledgement before merge)**:

- **DB schema change**: new column `Deployment.deleted_at` and two new enum values (`DELETING`, `DELETED`).
- **GraphQL schema change**: `deleteDeployment` mutation, `Deployment.deletedAt`, `deployments(includeDeleted)` argument, `TaskType.DELETE_DEPLOYMENT`.
- **CRD schema change**: `StyrminDeployment.spec.deletionRequested` with CEL transition rule; new `phase: Deleted` and new `displayState` values `Deleting`/`Deleted`.

These are noted in the source PRD on issue #94 with the design rationale. No new external dependencies.

**Result**: Constitution Check passes; no violations to record under Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/008-deployment-deletion/
├── plan.md              # This file
├── spec.md              # Feature specification (Phase 1 of /speckit-auto-run)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── graphql.md       # Mutation, query argument, field, types, errors
│   ├── crd.md           # CRD schema delta + CEL rule
│   └── sdk.md           # SDK method shape and semantics
├── checklists/
│   └── requirements.md  # Spec-quality checklist (Phase 1)
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
backend/
├── styrmin_backend/
│   ├── api/
│   │   ├── definitions/
│   │   │   ├── deployment/model.py            # add deletedAt, status DELETING/DELETED
│   │   │   └── task/model.py                  # add DELETE_DEPLOYMENT
│   │   └── schema/
│   │       ├── mutation.py                    # add deleteDeployment(id) -> Task!
│   │       └── query.py                       # add includeDeleted on deployments()
│   ├── db/
│   │   ├── models.py                          # add DeploymentState.DELETING/DELETED, Deployment.deleted_at, TaskType.DELETE_DEPLOYMENT
│   │   └── migrations/versions/
│   │       └── <new>_deployment_deletion.py   # alembic migration
│   ├── domain/
│   │   └── models.py                          # mirror enum changes; Deployment.deleted_at
│   ├── operator/
│   │   ├── crd/schema.py                      # DisplayState.Deleting/Deleted; DeploymentPhase.Deleted; spec.deletion_requested field
│   │   ├── handlers/styrmin_deployment.py     # observe spec.deletionRequested in update handler; teardown pipeline; emit phase: Deleted on namespace gone
│   │   └── janitor.py                         # NEW kopf timer for TTL-based CR GC
│   ├── repository/
│   │   └── deployment.py                      # filter by deleted_at; setter for deleted_at; lookup by id ignoring deleted_at
│   └── services/
│       ├── deployment.py                      # NEW delete_deployment(id, uow) — patches CRD, writes Task + timeline event, idempotent semantics
│       ├── deployment_status.py               # extend _DISPLAY_STATE_TO_STATUS with Deleting/Deleted; on Deleted set deleted_at = now()
│       └── deployment_timeline.py             # add DELETE_DEPLOYMENT event type rendering
└── tests/
    ├── unit/
    │   └── api/schema/
    │       └── test_propagation_delete_deployment.py    # NEW propagation tests (per dev/guides/graphql-propagation-tests.md)
    └── e2e/
        ├── test_delete_deployment_api.py                # NEW @api_only
        └── test_delete_deployment_ui.py                 # NEW @ui_only

frontend/
├── src/
│   ├── pages/deployments/
│   │   ├── DeploymentDetailPage.tsx           # add Delete button beside Upgrade/Redeploy; disable on DELETING/DELETED; banner on tombstoned page
│   │   ├── DeploymentList.tsx                 # add Show deleted toggle; render Deleting... badge; greyed-out tombstoned rows
│   │   └── components/
│   │       └── DeleteDeploymentDialog.tsx     # NEW type-to-confirm dialog
│   └── graphql/                               # graphql-codegen consumes schema.graphql
└── tests/                                     # vitest unit; Playwright via backend e2e

python_sdk/
└── src/styrmin_sdk/
    ├── graphql/
    │   └── delete_deployment.graphql          # NEW per project conventions
    └── client/                                # NEW high-level delete_deployment(id) method on the deployment client surface

helm/
└── agent/crds/styrmin.io_styrmindeployments.yaml   # add spec.deletionRequested + CEL rule; add Deleting/Deleted to phase enum; add Deleting/Deleted to displayState enum
```

**Structure Decision**: Web application (Option 2). The feature spans backend (mutation, service, status reporter, repository, migration), operator (CRD, reconciliation handler, janitor timer), frontend (button, dialog, list toggle, tombstone banner), Python SDK (graphql file + high-level client method), and the agent Helm chart (CRD schema). All paths above are real; the layout matches existing project conventions (e.g., `delete_backup` mutation, `update_deployment` service shape, `restore` E2E placement).

## Phase 0 — Research

See [`research.md`](./research.md). All technical-context items are resolved (no `NEEDS CLARIFICATION` markers remain). Key decisions captured:

1. **Mutation shape**: `deleteDeployment(id: UUID!): Task!` (non-null Task; "born complete" `DELETE_DEPLOYMENT` of `TaskStatus.SUCCESS`). Rationale: matches the audit-record-not-progress-channel requirement and existing `delete_backup` precedent. Alternatives — returning `Boolean!` or `Deployment!` — rejected because they break the timeline-as-Task convention.
2. **CRD patch path**: backend uses `kr8s` async client to issue a strategic-merge patch on `spec/deletionRequested`. CEL rule on the field rejects `true → false` server-side; the patch is the *only* mechanism. Alternative — a dedicated subresource — rejected as overengineering.
3. **Status mapping**: extend `_DISPLAY_STATE_TO_STATUS` in `services/deployment_status.py`. The `→ DELETED` transition is the **only** code path that sets `deleted_at = now()`. Atomicity is guaranteed by the existing UnitOfWork commit boundary. Alternative — cron-style sweep — rejected because it would race with the reconciler.
4. **Forensic CR GC**: new kopf timer at module-level (`operator/janitor.py`) firing every 30 minutes. Selects only CRs with `status.phase == Deleted` whose `Deleted` condition's `lastTransitionTime` is older than `DELETED_CR_TTL_HOURS` (default 6, `int` env var). `Deleting`-stuck CRs are explicitly excluded so failures remain visible. Alternative — rely on a Kubernetes TTL controller — rejected because it cannot select on `phase == Deleted`.
5. **Idempotency**: a second mutation while `Deployment.status == DELETING` returns the most recent existing `DELETE_DEPLOYMENT` task. This is implemented in the service (`delete_deployment`) by querying `Task` filtered by `deployment_id` + `type=DELETE_DEPLOYMENT` ordered by `created_at DESC` *before* deciding to issue a new patch.
6. **"Not found" on already-deleted**: the resolver raises `DeploymentNotFoundError` for `status == DELETED`, deliberately conflating with "id doesn't exist". This is the contract — clients distinguish this case by checking the error code (`DEPLOYMENT_NOT_FOUND`) returned by the structured-error middleware. (Alternative — a distinct `DeploymentAlreadyDeletedError` — rejected because the spec says clients MUST be able to treat both cases identically.)
7. **Restore guard**: `services/deployment.py::delete_deployment` short-circuits when `deployment.status == RESTORING` raising `DeploymentRestoringError(error_code=DEPLOYMENT_RESTORING)`. The check is on `Deployment.status` (DB), not the CRD `phase`, because the DB is the source of truth for the lifecycle gate.
8. **Visibility filter**: new `includeDeleted` argument propagates to `repository/deployment.py::list_deployments`; default applies `WHERE deleted_at IS NULL`. `DELETING` rows have `deleted_at IS NULL` until terminal — they remain visible by default. Alternative — separate `listDeletedDeployments` query — rejected because it forces the frontend toggle to swap queries instead of toggling an argument.
9. **Detail-page reachability**: `deployment(id)` is **unfiltered**. The detail-page route renders for any record reachable by id, including tombstones, with the "Deleted at <timestamp>" banner driven by `deletedAt != null`.
10. **Type-to-confirm dialog**: re-use the pattern from `delete_backup` and `delete_environment` dialogs (case-sensitive exact-match input gates the destructive button); dialog body adds the workload+namespace+backup-retention summary.

## Phase 1 — Design & Contracts

### Data Model

See [`data-model.md`](./data-model.md). Summary of new entities and field additions:

- **`Deployment`** (DB + domain): new column `deleted_at: datetime | None` (nullable, indexed for the default-list filter); status enum gains `DELETING`, `DELETED` (terminal). Existing relationships unchanged — `Backup`, `DeploymentTimelineEvent`, `Task` rows survive deletion.
- **`Task`** (DB): `TaskType` gains `DELETE_DEPLOYMENT`. Born `TaskStatus.SUCCESS`. No Prefect flow.
- **`StyrminDeployment` CRD**: `spec.deletionRequested: bool` (default `false`) with CEL transition rule `oldSelf == false || self == true` and `x-kubernetes-validations` block. `status.phase` enum gains `Deleted` (existing `Deleting` reused). `status.displayState` enum gains `Deleting` and `Deleted`.
- **Cluster retention configuration**: env var `DELETED_CR_TTL_HOURS` (int, default `6`). Read once at operator boot.
- **`DeploymentTimelineEvent`**: new event type `DELETE_DEPLOYMENT` representing a deletion request; payload carries the actor (already on the row) and the timestamp. The event is created inside the same UnitOfWork as the Task to guarantee atomic visibility.

### API Contracts

See [`contracts/`](./contracts/) for the GraphQL surface, the CRD delta, and the SDK shape.

- [`graphql.md`](./contracts/graphql.md) — mutation, query argument, scalar field, enum additions, error codes.
- [`crd.md`](./contracts/crd.md) — CRD schema delta + CEL rule + janitor selection rule.
- [`sdk.md`](./contracts/sdk.md) — SDK method signature, semantics, error mapping, query file path.

### Quickstart

See [`quickstart.md`](./quickstart.md) for the engineer-facing recipe: run the migration, regenerate the schema, drive the SDK call, and walk through the UI flow.

### Agent Context

`CLAUDE.md` references this plan via the existing footer pointer (already present from the spec phase). No automated `update-agent-context.sh` invocation per the constitution boundary ("Never execute the script `update-agent-context.sh`").

### Constitution Re-check (post-design)

- All six principles still pass; no violations introduced by the contracts.
- Governance gate tickets are surfaced in the migration / schema / CRD diff; the implementation phase will explicitly call them out in commits.
- E2E + propagation coverage confirmed mandatory in `tasks.md` (next phase).

## Complexity Tracking

> No constitution-check violations to justify. This section intentionally left empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| _none_    | _n/a_      | _n/a_                                |
