## ADR-010: Migrate Frontend Routing from React Router to TanStack Router

**Status**: Accepted
**Date**: 2026-04-26
**Source**: specs/archive/001-tanstack-router-migration/research.md (R001–R007, R010)

## Context

The Styrmin frontend previously used React Router v7 to define a flat route tree under a single `AppShell` layout (11 routes, 7 page components consuming route params, 8 programmatic-navigation call sites). React Router's hooks return weakly typed values — `useParams()` yields `Record<string, string | undefined>` regardless of the route, requiring manual type assertions or runtime guards in every page component. `Link` and `navigate` accept arbitrary strings, so renaming or removing a route does not produce a compile error at the call sites. This was a recurring source of defensive boilerplate and a class of latent bugs that escaped both type-check and lint.

TanStack Router was already on the team's radar because the project was simultaneously adopting other TanStack libraries (Query, Form). Standardizing the frontend on a single ecosystem reduces version-skew and conceptual surface area for future contributors.

## Decision

Replace React Router with TanStack Router using a **code-based** route tree (not file-based):

1. Define each route via `createRoute` / `createRootRoute` in `src/routes/`, with the assembled tree exported from `src/routeTree.ts`.
2. Create the router instance in `src/router.ts` and register its type globally via `declare module '@tanstack/react-router' { interface Register { router: typeof router } }` so `Link`, `useNavigate`, and `Route.useParams` infer types from the live tree.
3. Use `lazyRouteComponent(() => import('...'))` for every page component (preserving the current code-splitting behavior of `React.lazy` + `Suspense`).
4. Make the AppShell layout the `component` of `rootRoute`, with `<Outlet />` rendering child routes; replace `useLocation` + manual `isActive` with `<Link activeProps={...}>`.
5. Add a `notFoundComponent` on the root route to handle unmatched URLs (no explicit `*` catch-all is needed — TanStack Router handles unmatched routes structurally).
6. Replace `MemoryRouter` in `src/test/utils.tsx` with a per-test router built from `createMemoryHistory` + `createRouter` + `RouterProvider`.
7. Remove `react-router` and `react-router-dom` from `package.json`.

## Consequences

**Easier:**

- All route params are non-optional and typed per-route via `Route.useParams()` — no defensive guards.
- `Link to=` and `navigate({ to, params })` are type-checked against the registered route tree; renaming a route surfaces every broken call site at compile time.
- Active-link styling is declarative via `activeProps`/`activeOptions`, eliminating the `useLocation` + manual matching pattern.
- Lazy loading is a route-tree concern, integrated with the router's pending/loading states rather than ad-hoc `Suspense` boundaries.

**Harder:**

- Programmatic navigation now uses an object form (`navigate({ to: '/drivers/$driverId', params: { driverId: id } })`) rather than string interpolation; existing call sites must be rewritten.
- Route param syntax uses `$paramId` rather than `:paramId`; URL patterns and any string-based references must be updated.
- Tests now require constructing a real `Router` instance (with `createMemoryHistory`) rather than wrapping in a single `MemoryRouter` element, increasing per-test setup slightly.
- The type-registration step (`declare module`) is mandatory — without it, type-safe `Link`/`useNavigate` silently degrade.

## Alternatives Considered

- **File-based routing**: Auto-generated tree (`routeTree.gen.ts`) via the TanStack Router Vite plugin. Better at large scale (50+ routes) but adds a build-tooling dependency and a generated file that complicates code review. Rejected — 11 routes do not justify the indirection, and an explicit tree is easier to verify against the React Router tree during the migration PR.
- **Virtual file routes**: Hybrid of code-based and file-based. Rejected for the same scale reason.
- **Stay on React Router**: Rejected; the recurring `string | undefined` param friction was the entire motivation, and TanStack ecosystem alignment is a separate cumulative benefit.
