# Implementation Plan: Enforce Single-Cluster Limit

**Branch**: `002-single-cluster-limit` | **Date**: 2026-03-28 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/002-single-cluster-limit/spec.md`

## Summary

Enforce a single-cluster constraint at the service layer, add a default cluster name of "default", and update the frontend Settings page to reflect single-cluster semantics (hide creation button when a cluster exists, switch from grid to single-item layout).

## Technical Context

**Language/Version**: Python 3.12+ (backend), TypeScript 5.9.3 (frontend)
**Primary Dependencies**: Strawberry GraphQL, SQLModel, Pydantic (backend); React 19, urql, React Hook Form, Zod, Radix UI (frontend)
**Storage**: PostgreSQL via SQLModel/SQLAlchemy (async) — no schema/migration changes
**Testing**: pytest with async fixtures and fake repositories (backend); Vitest + React Testing Library (frontend)
**Target Platform**: Web application (SPA + GraphQL API)
**Project Type**: Web (backend + frontend)
**Performance Goals**: N/A — admin-only operation, no performance-sensitive paths
**Constraints**: No database migrations; GraphQL schema change limited to making `name` parameter optional with default
**Scale/Scope**: Single-cluster system; affects 3 backend files, 2 frontend files, plus tests

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | N/A | No deployment/reconciliation changes |
| II. Driver-Based Deployment | N/A | No driver changes |
| III. Layered Architecture | PASS | Changes follow GraphQL → Service → Repository → DB layering |
| IV. Type Safety and Typed Errors | PASS | New `ClusterLimitReachedError` follows existing typed error pattern; `name` default uses Python type system |
| V. Test-First Development | PASS | Plan includes unit tests for service constraint and frontend component tests |
| VI. Format and Lint Before Commit | PASS | Standard workflow applies |

**Governance Gates:**

| Gate | Status | Notes |
|------|--------|-------|
| Database schema changes | PASS | No migrations required |
| GraphQL schema modifications | MINOR CHANGE | `name: String!` → `name: String! = "default"` in `createCluster` mutation. This is a backward-compatible default value addition, not a structural change. Schema regeneration required. |
| New dependencies | PASS | No new dependencies |
| CI/CD workflow changes | PASS | No CI changes |
| Auth/authz changes | PASS | No auth changes |

## Project Structure

### Documentation (this feature)

```text
specs/002-single-cluster-limit/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── create_cluster_mutation.md
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
backend/
├── styrmin_backend/
│   ├── api/
│   │   └── schema/
│   │       └── mutation.py           # Update: make name optional with default
│   ├── services/
│   │   ├── clusters.py               # Update: add single-cluster check, default name
│   │   └── exceptions.py             # Update: add ClusterLimitReachedError
│   └── db/
│       └── models.py                 # No changes
└── tests/
    └── unit/
        └── services/
            └── test_cluster_services.py  # Update: add constraint tests

frontend/
├── src/
│   └── pages/settings/
│       ├── SettingsPage.tsx           # Update: conditional layout and button visibility
│       └── CreateClusterDialog.tsx    # Update: pre-fill name with "default"
└── tests/                             # Update: add component tests
```

**Structure Decision**: Existing web application structure (backend/ + frontend/) with no new directories. Changes are localized to existing files.

## Complexity Tracking

No constitution violations to justify.
