# Implementation Plan: Migrate from React Router to TanStack Router

**Branch**: `001-tanstack-router-migration` | **Date**: 2026-04-01 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-tanstack-router-migration/spec.md`

## Summary

Replace React Router 7.13.1 with TanStack Router to achieve fully type-safe routing across the Styrmin frontend. The migration converts 11 routes from React Router's declarative `<Route>` JSX to TanStack Router's code-based `createRoute` / `createRootRoute` API, providing compile-time type safety for all route parameters, `Link` components, and programmatic navigation. The approach is a 1:1 route replacement — no new routes, layouts, or navigation patterns are introduced.

## Technical Context

**Language/Version**: TypeScript 5.9.3, React 19.2.4, Node 22
**Primary Dependencies**: `@tanstack/react-router` (new), urql 5.0.1, Radix UI, React Hook Form 7, Zod 4
**Removed Dependencies**: `react-router` 7.13.1
**Storage**: N/A (frontend-only change)
**Testing**: Vitest 4.1.0, React Testing Library 16.3.2, user-event 14.6.1
**Target Platform**: Web SPA (Vite 8.0.1 dev/build)
**Project Type**: Web application (frontend-only change within monorepo)
**Performance Goals**: No increase in production bundle size (within 5% tolerance per SC-006)
**Constraints**: All 11 existing routes must resolve identically; zero runtime routing regressions
**Scale/Scope**: 11 routes, 6 `useParams` call sites, 6 `useNavigate` call sites, 9 files using `Link`, 1 `useLocation` call site, 1 test utility file

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | N/A | Backend-only principle; frontend routing change |
| II. Driver-Based Deployment | N/A | Backend-only principle |
| III. Layered Architecture | N/A | Backend-only principle; no API layer changes |
| IV. Type Safety and Typed Errors | **PASS** | Migration *improves* type safety — route params become fully typed at compile time instead of `string \| undefined` |
| V. Test-First Development | **PASS** | Test infrastructure will be updated (MemoryRouter → createMemoryHistory); existing tests must pass |
| VI. Format and Lint Before Commit | **PASS** | ESLint + Prettier enforced via `pnpm lint`; no backend changes so `uv run invoke format lint` not applicable |

**Governance Gates**:

| Gate | Status | Notes |
|------|--------|-------|
| Database schema changes | N/A | No database involvement |
| GraphQL schema modifications | N/A | No GraphQL schema changes |
| New dependencies | **TRIGGERED** | Adding `@tanstack/react-router`; removing `react-router`. Net dependency change: swap one routing library for another. |
| CI/CD workflow changes | N/A | No CI changes needed |
| Auth/authz changes | N/A | No auth changes |

**Gate Resolution**: The "New dependencies" gate is triggered. `@tanstack/react-router` replaces `react-router` — it is a swap, not an addition. The new library is a widely-adopted, actively-maintained routing solution with strong TypeScript support. Bundle size is comparable. This is justified by the core requirement for compile-time type-safe routing.

## Project Structure

### Documentation (this feature)

```text
specs/001-tanstack-router-migration/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
frontend/
├── src/
│   ├── routes/              # NEW: TanStack Router route definitions
│   │   ├── __root.tsx       # Root route (AppShell layout + Outlet)
│   │   ├── index.tsx        # "/" → EnvironmentListPage
│   │   └── ...              # All 11 routes as code-based route files
│   ├── routeTree.ts         # NEW: Assembled route tree
│   ├── router.ts            # NEW: Router instance + Register type
│   ├── components/
│   │   └── AppShell.tsx     # MODIFIED: useLocation → useRouterState, Outlet import source
│   ├── pages/               # MODIFIED: useParams/useNavigate/Link import sources
│   ├── test/
│   │   └── utils.tsx        # MODIFIED: MemoryRouter → createMemoryHistory + RouterProvider
│   ├── App.tsx              # MODIFIED: BrowserRouter/Routes/Route → RouterProvider
│   └── main.tsx             # May need RouterProvider moved here
└── package.json             # MODIFIED: swap react-router → @tanstack/react-router
```

**Structure Decision**: Code-based routing (not file-based) is chosen because:
1. The route tree is small (11 routes) and stable — file-based routing adds build tooling complexity without proportional benefit
2. Code-based routing gives explicit control over the route tree shape, which is easier to review in a migration PR
3. No Vite plugin required — simpler build configuration

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| None | — | — |
