# Implementation Plan: Replace urql with TanStack Query

**Branch**: `001-tanstack-query-migration` | **Date**: 2026-04-03 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-tanstack-query-migration/spec.md`

## Summary

Replace urql with TanStack Query as the frontend GraphQL data fetching layer. The migration covers all 28 GraphQL operations (14 queries, 14 mutations) across ~11 page components, reconfigures codegen to generate TanStack Query hooks, and updates the test infrastructure. This is a frontend-only change with no backend modifications.

## Technical Context

**Language/Version**: TypeScript 5.9.3, Node 22
**Primary Dependencies**: React 19.2.4, TanStack Router 1.168.x (already installed), TanStack Query v5 (new), `@graphql-codegen/typescript-react-query` (new)
**Storage**: N/A (frontend-only, data via GraphQL API at `/graphql`)
**Testing**: Vitest, @testing-library/react 16.3.2, jsdom
**Target Platform**: Web (SPA served by Vite 8)
**Project Type**: Web application (frontend module of monorepo)
**Performance Goals**: No regression — page loads and data display must be indistinguishable from current behavior
**Constraints**: Zero downtime on migration (big-bang swap, no dual-library state in production)
**Scale/Scope**: ~11 page components, ~38 hook invocations, 28 `.graphql` operation files

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | N/A | Backend concern — no changes to reconciliation |
| II. Driver-Based Deployment | N/A | Backend concern — no changes to drivers |
| III. Layered Architecture | PASS | Frontend-only change; backend layers untouched |
| IV. Type Safety and Typed Errors | PASS | Codegen ensures full type safety for all hooks; GraphQL union types preserved |
| V. Test-First Development | PASS | Test utilities updated with QueryClient wrapper; existing tests must pass |
| VI. Format and Lint Before Commit | PASS | ESLint/Prettier enforced via existing config |

**Governance Gates**:

| Gate | Status | Notes |
|------|--------|-------|
| Database schema changes | N/A | No database changes |
| GraphQL schema modifications | N/A | No schema changes — same `.graphql` operations |
| New dependencies | FLAGGED | Adding `@tanstack/react-query`, `@tanstack/react-query-devtools`, `@graphql-codegen/typescript-react-query`. Removing `urql`, `@urql/core`, `@graphql-codegen/typescript-urql` |
| CI/CD workflow changes | N/A | No CI changes needed |
| Auth/authz changes | N/A | No auth changes |

**Gate Resolution**: New dependencies are direct replacements for removed packages within the same domain (GraphQL data fetching). Net dependency count stays the same or decreases. This is a standard library swap, not a new capability addition.

## Project Structure

### Documentation (this feature)

```text
specs/001-tanstack-query-migration/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
frontend/
├── codegen.ts                          # MODIFY: swap urql plugin → react-query plugin
├── package.json                        # MODIFY: swap dependencies
├── src/
│   ├── App.tsx                         # MODIFY: swap Provider (urql → QueryClient)
│   ├── lib/
│   │   ├── urql.ts                     # DELETE: urql client config
│   │   └── query-client.ts             # CREATE: QueryClient config
│   ├── lib/graphql-fetcher.ts          # CREATE: fetch-based GraphQL transport
│   ├── generated/
│   │   └── graphql.ts                  # REGENERATE: TanStack Query hooks
│   ├── hooks/
│   │   └── useAutoRefresh.ts           # DELETE: replaced by refetchInterval
│   ├── pages/
│   │   ├── deployments/
│   │   │   ├── DeployFormPage.tsx       # MODIFY: update hook usage
│   │   │   └── DeploymentDetailPage.tsx # MODIFY: update hook usage + pause→enabled
│   │   ├── drivers/
│   │   │   ├── DriverListPage.tsx       # MODIFY: update hook usage
│   │   │   ├── DriverDetailPage.tsx     # MODIFY: update hook usage
│   │   │   └── AddDriverPage.tsx        # MODIFY: update hook usage
│   │   ├── environments/
│   │   │   ├── EnvironmentListPage.tsx  # MODIFY: update hook usage
│   │   │   └── EnvironmentDetailPage.tsx # MODIFY: update hook usage
│   │   ├── backup-storage-locations/
│   │   │   ├── BackupStorageLocationListPage.tsx   # MODIFY: update hook usage
│   │   │   └── BackupStorageLocationDetailPage.tsx # MODIFY: update hook usage
│   │   └── settings/
│   │       ├── SettingsPage.tsx          # MODIFY: update hook usage
│   │       └── ClusterDetailPage.tsx     # MODIFY: update hook usage
│   └── test/
│       └── utils.tsx                    # MODIFY: add QueryClientProvider wrapper
└── tests/                               # MODIFY: update any test files as needed
```

**Structure Decision**: This feature modifies the existing `frontend/` directory structure. No new directories are created beyond `contracts/` in the spec directory. The change is a library swap within the existing architecture.

## Complexity Tracking

No constitution violations to justify. This is a straightforward library replacement within the frontend module.
