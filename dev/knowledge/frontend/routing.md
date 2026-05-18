<!-- Extracted from specs/001-tanstack-router-migration on 2026-04-26 -->

## Frontend Routing

### Overview

The frontend uses **TanStack Router** with a code-based route tree. Every route in the application is a direct child of a single root layout (the `AppShell`). Type safety is global: route paths, parameters, and navigation calls are all validated against the registered route tree at compile time.

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

<!-- Extracted from specs/011-admin-user-group-mgmt on 2026-05-13 -->

### Auth and role-gated routes

Feature 011 adds an authenticated-user surface and role-gated admin routes on top of the auth foundation from #179 (see [ADR-024](../../adr/adr-024-authentication-and-sessions.md) / [ADR-025](../../adr/adr-025-authorization-model.md)).

#### Routes

| Path | Purpose | Gating |
|------|---------|--------|
| `/login` | Username/password form | Redirect to `/` if already authenticated |
| `/profile` | Self-service: change password, view own role + group memberships | Any authenticated user |
| `/users` | Admin: list/filter users, create | `effectiveRole === ADMIN` |
| `/users/$id` | Admin: edit user, reset password, deactivate, delete | `effectiveRole === ADMIN` |
| `/groups` | Admin: list groups, create | `effectiveRole === ADMIN` |
| `/groups/$id` | Admin: edit group, replace member set, delete | `effectiveRole === ADMIN` |

All admin-only pages share the same `beforeLoad` guard.

#### Router context and `AuthProvider`

`AuthProvider` queries `currentUser` and pushes an `auth` object into the TanStack Router context **synchronously** — not via `useEffect`. The synchronous push (commit `c37d896`) was the fix for a flicker / race where a `beforeLoad` guard could read a stale `undefined` context on the first navigation. Concretely:

```ts
// router.ts — the context shape
export const router = createRouter({
  routeTree,
  context: { auth: undefined as unknown as AuthContextValue },
});

// AuthProvider — updates the context on every render where currentUser changes
router.update({ context: { auth: { currentUser, ... } } });

// route file
beforeLoad: ({ context }) => {
  if (context.auth.currentUser?.effectiveRole !== "ADMIN") {
    throw redirect({ to: "/" });
  }
},

// /login — inverse guard
beforeLoad: ({ context }) => {
  if (context.auth.currentUser != null) throw redirect({ to: "/" });
},
```

`router.update({ context })` rerunning every route's `beforeLoad` when `auth` changes is the desired behaviour — becoming admin should re-evaluate guards.

#### UI affordance gating

In addition to route-level guards, **UI affordances** (nav links, action buttons, menu items) for admin actions are hidden — not disabled — using the role-gating component:

```tsx
<IfRole minimum="ADMIN">
  <Link to="/users">Users</Link>
</IfRole>
```

`useEffectiveRole()` is the hook form for conditional logic. Both read `context.auth.currentUser.effectiveRole`. Gating MUST always read `effectiveRole` — the aggregate of direct role and group-conferred roles — never the raw `role` field on the user. Reading `role` directly bypasses the group-conferred admin pathway and is a bug.

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
