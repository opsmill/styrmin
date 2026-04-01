# Research: Migrate from React Router to TanStack Router

**Feature**: 001-tanstack-router-migration
**Date**: 2026-04-01

## R-001: Code-Based vs File-Based Routing

**Decision**: Code-based routing using `createRoute` / `createRootRoute` API

**Rationale**:
- The route tree is small and stable (11 routes) — file-based routing's auto-generation adds build tooling complexity (Vite plugin, generated `routeTree.gen.ts`) without proportional benefit.
- Code-based routing produces an explicit, reviewable route tree — critical for a migration PR where reviewers need to verify 1:1 parity.
- No additional Vite plugin dependency required.
- TanStack Router's code-based API provides identical type safety to file-based routing — both register the route tree via `declare module '@tanstack/react-router' { interface Register { router: typeof router } }`.

**Alternatives considered**:
- **File-based routing**: Auto-generates route tree from filesystem conventions. Better for large apps with 50+ routes. Rejected because the added build complexity (Vite plugin, codegen step) outweighs the benefit for 11 routes.
- **Virtual file routes**: Hybrid approach. Rejected for the same reason — unnecessary for this scale.

## R-002: Lazy Route Loading Pattern

**Decision**: Use TanStack Router's `lazy` route option with `lazyRouteComponent`

**Rationale**:
- Current implementation uses `React.lazy()` + `Suspense` for all 11 page components.
- TanStack Router has built-in lazy route support via the `lazy` option on route definitions, which integrates with its own loading/pending states.
- The `lazyRouteComponent` utility wraps dynamic imports for use in the `component` field of lazy routes.
- This approach replaces `React.lazy` + `Suspense` with TanStack Router's native mechanism, which provides better loading state control.

**Pattern**:
```tsx
// Option A: lazy on the route definition (preferred — splits route config + component)
const environmentDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/environments/$environmentId',
  component: lazy(() => import('@/pages/environments/EnvironmentDetailPage')),
})

// Option B: lazyRouteComponent helper
import { lazyRouteComponent } from '@tanstack/react-router'

const environmentDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/environments/$environmentId',
  component: lazyRouteComponent(
    () => import('@/pages/environments/EnvironmentDetailPage'),
  ),
})
```

**Alternatives considered**:
- **Keep React.lazy + Suspense**: Would work but misses TanStack Router's built-in pending/loading UI capabilities. Rejected to use the idiomatic approach.
- **No lazy loading**: Rejected — current app already lazy-loads and we must preserve performance characteristics (FR-005).

## R-003: Route Parameter Syntax

**Decision**: Use TanStack Router's `$param` syntax (replacing React Router's `:param`)

**Rationale**:
- TanStack Router uses `$paramName` instead of `:paramName` for route parameters.
- All route params are fully typed — `useParams` returns typed objects, not `string | undefined`.
- The `params` type is inferred from the route definition and the registered route tree.

**Migration mapping**:
| React Router Path | TanStack Router Path |
|-------------------|---------------------|
| `/environments/:environmentId` | `/environments/$environmentId` |
| `/environments/:environmentId/deploy` | `/environments/$environmentId/deploy` |
| `/environments/:environmentId/deployments/:deploymentId` | `/environments/$environmentId/deployments/$deploymentId` |
| `/backup-storage-locations/:id` | `/backup-storage-locations/$id` |
| `/drivers/:driverId` | `/drivers/$driverId` |
| `/settings/clusters/:clusterId` | `/settings/clusters/$clusterId` |

**Alternatives considered**: None — this is TanStack Router's only parameter syntax.

## R-004: Layout Route and Outlet Pattern

**Decision**: Use `createRootRoute` with `Outlet` from `@tanstack/react-router`

**Rationale**:
- Current AppShell uses React Router's `<Outlet />` to render child routes.
- TanStack Router provides its own `Outlet` component with identical behavior.
- The root route's `component` renders the AppShell layout with `<Outlet />` for child content.
- `useLocation` (for active nav link detection) is replaced by `useRouterState` or the `Link` component's built-in `activeProps`/`activeOptions`.

**Pattern**:
```tsx
import { createRootRoute, Outlet, Link } from '@tanstack/react-router'
import { AppShell } from '@/components/AppShell'

export const rootRoute = createRootRoute({
  component: AppShell,  // AppShell renders <Outlet /> internally
})
```

**AppShell changes**:
- Replace `import { Outlet, Link, useLocation } from 'react-router'` → `import { Outlet, Link, useRouterState } from '@tanstack/react-router'`
- Replace `useLocation().pathname` → `useRouterState({ select: (s) => s.location.pathname })`
- Alternatively, use TanStack Router's `Link` `activeProps` for active link styling, eliminating the need for manual `isActive()` logic.

**Alternatives considered**:
- **Pathless layout route (non-root)**: Not needed — AppShell wraps all routes, making it the natural root route component.

## R-005: Navigation API Migration

**Decision**: Replace React Router hooks with TanStack Router equivalents

**Rationale**: TanStack Router provides type-safe equivalents for all React Router navigation hooks.

**Hook migration mapping**:

| React Router | TanStack Router | Type Safety Improvement |
|-------------|----------------|------------------------|
| `useParams()` → `{ param: string \| undefined }` | `Route.useParams()` → `{ param: string }` | Params are non-optional, typed per-route |
| `useNavigate()` → `navigate('/path')` | `useNavigate()` → `navigate({ to: '/path', params: {...} })` | Target route + params type-checked |
| `<Link to="/path">` | `<Link to="/path" params={{...}}>` | Path + params type-checked at compile time |
| `useLocation()` | `useRouterState({ select: s => s.location })` | Same, with selector pattern |

**Key behavioral differences**:
- `useNavigate` uses an object API `{ to, params, search }` instead of a string path. String interpolation like `` navigate(`/drivers/${id}`) `` becomes `navigate({ to: '/drivers/$driverId', params: { driverId: id } })`.
- `Link` `to` prop accepts route paths with `$param` placeholders; actual values go in `params` prop.
- Route-specific hooks like `Route.useParams()` provide the tightest types — only the params for that specific route.

**Alternatives considered**: None — these are the standard TanStack Router APIs.

## R-006: Test Infrastructure Migration

**Decision**: Replace `MemoryRouter` with `createMemoryHistory` + `createRouter` + `RouterProvider`

**Rationale**:
- React Router's `MemoryRouter` is a single-component wrapper. TanStack Router requires explicit router creation with memory history.
- The test utility in `src/test/utils.tsx` will create a router instance per test using `createMemoryHistory`.
- For simple component tests that just need a router context (e.g., components that render `Link`), a minimal route tree is sufficient.

**New test utility pattern**:
```tsx
import { render, type RenderOptions } from '@testing-library/react'
import {
  createRouter,
  createRootRoute,
  createMemoryHistory,
  RouterProvider,
  Outlet,
} from '@tanstack/react-router'

const rootRoute = createRootRoute({ component: () => <Outlet /> })

function createTestRouter(initialLocation = '/') {
  return createRouter({
    routeTree: rootRoute.addChildren([]),
    history: createMemoryHistory({ initialEntries: [initialLocation] }),
  })
}

function customRender(ui: ReactElement, options?: Omit<RenderOptions, 'wrapper'>) {
  const router = createTestRouter()
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <RouterProvider router={router}>{children}</RouterProvider>
  }
  return render(ui, { ...options, wrapper: Wrapper })
}
```

**Alternatives considered**:
- **Mock the router entirely**: Rejected — a real router instance is trivial to create and provides better test fidelity.
- **Use file-based route test utilities**: Rejected — code-based approach doesn't need `routeTree.gen.ts`.

## R-007: Router Instance and Type Registration

**Decision**: Create router instance in `src/router.ts` with module augmentation for global type safety

**Rationale**:
- TanStack Router's type safety relies on registering the router type via TypeScript module augmentation.
- The `declare module` pattern tells TypeScript the shape of the entire route tree, enabling type-safe `Link`, `useNavigate`, and `useParams` across the app.
- Placing the router in a dedicated file (`router.ts`) keeps the route tree separate from the app entry point and avoids circular imports.

**Pattern**:
```tsx
// src/router.ts
import { createRouter } from '@tanstack/react-router'
import { routeTree } from './routeTree'

export const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
```

**Alternatives considered**:
- **Inline in App.tsx**: Works but makes it harder to import the router in test utilities without circular dependencies. Rejected.

## R-008: Bundle Size Impact

**Decision**: Expected bundle size to be within 5% tolerance (SC-006)

**Rationale**:
- `react-router` 7.x: ~15-20KB gzipped (includes history, matching, components)
- `@tanstack/react-router`: ~12-18KB gzipped (similar scope, no history polyfill needed)
- Both libraries tree-shake well with Vite's bundler.
- The migration is a swap, not an addition — `react-router` is fully removed.
- Verification: Run `pnpm build` before and after, compare `dist/` output sizes.

**Alternatives considered**: N/A — this is a measurement, not a design decision.

## R-009: Active Link Styling

**Decision**: Use TanStack Router's `Link` `activeProps` for active link styling

**Rationale**:
- Current AppShell uses `useLocation().pathname` + manual `isActive()` function to apply active styles to nav links.
- TanStack Router's `Link` component has built-in `activeProps` and `activeOptions` props that automatically apply CSS classes/styles when the link matches the current route.
- This eliminates custom active-detection logic and is more idiomatic.

**Pattern**:
```tsx
<Link
  to="/"
  activeProps={{ className: 'bg-accent text-accent-foreground' }}
  activeOptions={{ exact: true }}
>
  Environments
</Link>
```

**Alternatives considered**:
- **Keep manual isActive logic with useRouterState**: Works but TanStack Router's built-in mechanism is cleaner. Rejected.

## R-010: Not Found / Catch-All Route

**Decision**: Add a `notFoundComponent` on the root route

**Rationale**:
- The current React Router setup has no explicit catch-all route — unmatched URLs render nothing inside AppShell.
- TanStack Router provides `notFoundComponent` on routes, which renders when no child route matches.
- Adding this to the root route satisfies edge case EC-001 from the spec and aligns with FR-009.

**Pattern**:
```tsx
const rootRoute = createRootRoute({
  component: AppShell,
  notFoundComponent: () => <div>Page not found</div>,
})
```

**Alternatives considered**:
- **Catch-all route with `*` path**: TanStack Router doesn't use `*` catch-alls; `notFoundComponent` is the idiomatic approach.
