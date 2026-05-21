# Implementation Plan: Driver Detail Page Redesign (Tabbed Layout)

**Branch**: `012-driver-detail-tabs` | **Date**: 2026-05-21 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/012-driver-detail-tabs/spec.md`

## Summary

Replace the single-column **application driver** detail page with a tabbed layout: a left rail of **driver versions** ordered newest-first by registration time, a vertical divider, and a right pane with **Overview / Parameters / Components / Actions / Source** tabs. Replace the raw JSON dumps of `components` and `componentConfigs` with structured rendering.

Technical approach: pure frontend refactor of `frontend/src/pages/drivers/DriverDetailPage.tsx` split into ~7 sub-components, driven by the existing `useGetDriverQuery` hook. One backend GraphQL schema addition is required to expose `createdOn: DateTime!` on both `ApplicationDriver` and `ApplicationDriverVersion` (the database column already exists on `StyrminModel`). No database migration, no new dependencies, no new auth surface. Local component state holds the active **driver version** and active tab — no URL search-param persistence (matches `DeploymentDetailPage` convention).

## Technical Context

**Language/Version**: TypeScript 5.9.3 (frontend); Python 3.14+ (backend GraphQL surface)
**Primary Dependencies**: React 19.2.4, TanStack Router 1.168.x, TanStack Query v5, Tailwind, existing `@/components/ui/tabs` (frontend); Strawberry GraphQL, SQLModel, Pydantic (backend)
**Storage**: PostgreSQL via SQLModel — **no schema changes** (`created_on` already exists on `StyrminModel`)
**Testing**: Vitest + React Testing Library (unit); pytest (backend unit + GraphQL propagation); pytest + Playwright (`ui_only` E2E in `backend/tests/e2e/`)
**Target Platform**: Web — Linux containers for backend, modern browsers for frontend
**Project Type**: Web application (existing `frontend/` + `backend/`)
**Performance Goals**: Tab switch < 1 s with cached data (no network round-trip); page renders without overflow for drivers with up to 20 **driver versions**
**Constraints**: No new dependencies; preserve existing 10 s `AutoRefreshIndicator` behaviour; no DB schema change; structured rendering only — zero `<pre>` JSON dumps on the rendered page
**Scale/Scope**: ~7 new React components, 5 tab panels, 1 added GraphQL field on 2 types, 1 GraphQL propagation test, 1 `ui_only` E2E test, ~3 to ~6 unit tests on the page

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Verdict | Justification |
|-----------|---------|---------------|
| §I Declarative state reconciliation | ✅ N/A | Read-only UI rendering; no reconciliation behaviour added or changed. |
| §II Driver-based deployment | ✅ Aligned | Displays what an **application driver** declares; no ad-hoc deployment logic introduced. |
| §III Layered architecture | ✅ Aligned | Backend change is a thin resolver-layer addition on existing Strawberry types; no cross-layer shortcuts. |
| §IV Type safety and typed errors | ✅ Aligned | No new `ServiceError` subclasses; query failures continue to surface via the existing `ErrorState` component; the new field is non-null `DateTime!` on existing types. |
| §V Test-first / E2E required | ✅ Planned | `ui_only` E2E `test_driver_detail_inspects_versions_via_tabs` ships with the feature, executed and observed to PASS locally before declaring done. Evidence captured per §V NON-NEGOTIABLE. |
| §V GraphQL ↔ DB propagation test | ✅ Planned | New `createdOn` field on `ApplicationDriver` and `ApplicationDriverVersion` triggers the propagation-test obligation; one test seeds rows with known `created_on` and asserts the resolver returns those values. Procedure: `dev/guides/graphql-propagation-tests.md`. |
| §VI Format and lint | ✅ Standard | `uv run invoke format lint` (backend) and frontend lint pass via pre-commit hooks. |

**Governance Gates Crossed**:

- ✅ **GraphQL schema modification** — adding `createdOn: DateTime!` to `ApplicationDriver` and `ApplicationDriverVersion`. Acknowledged and tracked. Propagation test is mandatory and is captured in tasks. Post-gate regeneration steps (`uv run styrmin export graphql-schema schema.graphql`, update `get_driver.graphql`, `uv run invoke generate`) are tracked as tasks, not as separate gates.

All other Governance Gates: not crossed. No DB schema change, no new dependency, no CI change, no auth change.

**Gate verdict**: ✅ PASS — ready for Phase 0.

## Project Structure

### Documentation (this feature)

```text
specs/012-driver-detail-tabs/
├── plan.md                  # This file
├── research.md              # Phase 0 output
├── data-model.md            # Phase 1 output
├── quickstart.md            # Phase 1 output
├── contracts/
│   └── get_driver.graphql   # Updated GraphQL contract (additive: createdOn)
├── spec.md
├── checklists/
│   └── requirements.md
└── tasks.md                 # Phase 2 output (NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
backend/
└── styrmin_backend/
    └── api/
        └── definitions/
            └── application_driver/
                └── model.py            # add createdOn field to ApplicationDriver, ApplicationDriverVersion

backend/tests/
└── functional/
    └── graphql/
        └── operations/                 # extend or add propagation test for createdOn

backend/tests/e2e/
└── drivers/
    └── test_driver_detail.py           # new ui_only E2E test

frontend/
├── src/
│   ├── graphql/
│   │   └── get_driver.graphql          # request createdOn on both types
│   ├── generated/
│   │   └── graphql.ts                  # regenerated
│   ├── routes/
│   │   └── driverDetail.tsx            # unchanged
│   └── pages/
│       └── drivers/
│           ├── DriverDetailPage.tsx     # rewritten — slim orchestrator
│           └── driver-detail/           # new sub-directory
│               ├── types.ts             # tab-id union, shared narrowed types
│               ├── DriverHeader.tsx
│               ├── VersionList.tsx
│               ├── VersionListItem.tsx
│               ├── VersionDetail.tsx
│               ├── VersionHeader.tsx
│               └── tabs/
│                   ├── OverviewTab.tsx
│                   ├── ParametersTab.tsx
│                   ├── ComponentsTab.tsx
│                   ├── ActionsTab.tsx
│                   └── SourceTab.tsx
└── src/__tests__/
    └── driver-detail/                   # new unit tests
        ├── DriverDetailPage.test.tsx
        └── VersionList.test.tsx

schema.graphql                            # regenerated (root)
python_sdk/src/styrmin_sdk/graphql/_generated/  # regenerated
```

**Structure Decision**: this is the existing "Web application" structure of the Styrmin repo (`frontend/` + `backend/`). The feature lives mainly under `frontend/src/pages/drivers/`, with one resolver edit under `backend/styrmin_backend/api/definitions/application_driver/`, one propagation test added under `backend/tests/functional/graphql/operations/`, and one E2E added under `backend/tests/e2e/drivers/`. No new top-level directories.

## Complexity Tracking

*No Constitution Check violations to justify — this section intentionally empty.*
