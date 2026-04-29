<!-- Extracted from specs/001-tanstack-router-migration on 2026-04-26 -->

## Frontend Routing

### Overview

The frontend uses **TanStack Router** with a code-based route tree. Every route in the application is a direct child of a single root layout (the `AppShell`). Type safety is global: route paths, parameters, and navigation calls are all validated against the registered route tree at compile time.

See [ADR-010](../../adr/adr-010-migrate-frontend-router-to-tanstack.md) for the migration rationale.

### File Layout

```text
frontend/src/
├── routes/
│   ├── __root.tsx          # rootRoute = createRootRoute(...) (AppShell + notFoundComponent)
│   ├── index.tsx           # indexRoute
│   ├── environmentDetail.tsx
│   ├── ...                 # one file per route, camelCase, exports a `createRoute(...)`
├── routeTree.ts            # Assembles the tree: rootRoute.addChildren([...])
├── router.ts               # createRouter({ routeTree }) + module augmentation
└── pages/                  # Page components consumed lazily by route definitions
```

### Route Tree

All routes are children of the root route. There are no nested layout routes — the AppShell wraps every page directly via `<Outlet />`.

```text
rootRoute (AppShell layout)
├── /                                                       indexRoute
├── /environments/$environmentId                            environmentDetailRoute
├── /environments/$environmentId/deploy                     deployFormRoute
├── /environments/$environmentId/deployments/$deploymentId  deploymentDetailRoute
├── /backup-storage-locations                               backupStorageLocationListRoute
├── /backup-storage-locations/$id                           backupStorageLocationDetailRoute
├── /drivers                                                driverListRoute
├── /drivers/add                                            addDriverRoute
├── /drivers/$driverId                                      driverDetailRoute
├── /settings                                               settingsRoute
└── /settings/clusters/$clusterId                           clusterDetailRoute
```

Route parameters use `$paramName` (TanStack Router syntax), not `:paramName`.

### Type Registration

`src/router.ts` registers the router type globally so TypeScript can infer route paths and params everywhere `Link`, `useNavigate`, or `useParams` are used.

```ts
// src/router.ts
import { createRouter } from "@tanstack/react-router";
import { routeTree } from "./routeTree";

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
```

Without the `declare module` block, `Link to=` and `useNavigate({ to })` fall back to plain strings and lose type safety. The registration is mandatory.

### Root Layout and Outlet

The `AppShell` component is the `component` of `rootRoute` and renders `<Outlet />` itself for child route content. There is no separate "layout route" beneath the root.

```tsx
import { createRootRoute, Outlet } from "@tanstack/react-router";

export const rootRoute = createRootRoute({
  component: AppShell, // AppShell renders <Outlet /> internally
  notFoundComponent: NotFound,
});
```

Active-link styling lives on `<Link>` itself via `activeProps` / `activeOptions`. There is no manual `useLocation().pathname` matching in nav components.

### Lazy Loading

Every page component is loaded with `lazyRouteComponent`, integrating with the router's pending state rather than ad-hoc `Suspense` boundaries.

```tsx
import { createRoute, lazyRouteComponent } from "@tanstack/react-router";

export const environmentDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/environments/$environmentId",
  component: lazyRouteComponent(
    () => import("@/pages/environments/EnvironmentDetailPage"),
  ),
});
```

### Not Found

The root route's `notFoundComponent` renders for any unmatched URL. There is no `*` catch-all — TanStack Router handles unmatched routes structurally.

### Test Router

`src/test/utils.tsx` builds a fresh router per test using `createMemoryHistory`. The custom `render()` wraps children in `<RouterProvider router={...}>`.

```tsx
import {
  createRouter,
  createRootRoute,
  createMemoryHistory,
  RouterProvider,
  Outlet,
} from "@tanstack/react-router";

const rootRoute = createRootRoute({ component: () => <Outlet /> });

function createTestRouter(initialLocation = "/") {
  return createRouter({
    routeTree: rootRoute.addChildren([]),
    history: createMemoryHistory({ initialEntries: [initialLocation] }),
  });
}
```

For component tests that just need router context (e.g. anything rendering a `<Link>`), an empty child-route tree is sufficient. Tests that need a typed `useParams` should add the relevant route.

### What Was Replaced

| Concept | Before (React Router) | After (TanStack Router) |
|---------|-----------------------|-------------------------|
| Param syntax | `:environmentId` | `$environmentId` |
| Param type | `string \| undefined` | `string` (per-route) |
| Param hook | `useParams()` (global) | `Route.useParams()` (per-route, tightest type) |
| Navigation | `navigate('/path')` | `navigate({ to: '/path/$id', params: { id } })` |
| Active link | `useLocation()` + manual match | `<Link activeProps={...}>` |
| Test wrapper | `<MemoryRouter>` | `RouterProvider` + `createMemoryHistory` |
| Lazy page | `React.lazy` + `<Suspense>` | `lazyRouteComponent` |
