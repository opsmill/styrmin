# Data Model: Migrate from React Router to TanStack Router

**Feature**: 001-tanstack-router-migration
**Date**: 2026-04-01

## Overview

This migration has no backend data model changes. The "data model" for this feature is the **route tree** — the compile-time type structure that defines all routes, their parameters, and their relationships.

## Route Tree Entity Model

### Route

A typed route definition that maps a URL pattern to a page component.

| Field | Type | Description |
|-------|------|-------------|
| `path` | `string` (literal type) | URL pattern with `$param` segments |
| `component` | `React.ComponentType` | Page component (lazy-loaded) |
| `getParentRoute` | `() => Route` | Parent route reference (forms tree) |
| `params` | Inferred from path | Route parameters extracted from `$` segments |

### Route Parameters

All route parameters are **string** typed and **non-optional** when accessed within their route's component.

| Route Path | Parameter(s) | Used By |
|------------|-------------|---------|
| `/environments/$environmentId` | `{ environmentId: string }` | EnvironmentDetailPage |
| `/environments/$environmentId/deploy` | `{ environmentId: string }` | DeployFormPage |
| `/environments/$environmentId/deployments/$deploymentId` | `{ environmentId: string; deploymentId: string }` | DeploymentDetailPage |
| `/backup-storage-locations/$id` | `{ id: string }` | BackupStorageLocationDetailPage |
| `/drivers/$driverId` | `{ driverId: string }` | DriverDetailPage |
| `/settings/clusters/$clusterId` | `{ clusterId: string }` | ClusterDetailPage |

### Route Tree Structure

```
rootRoute (AppShell layout)
├── indexRoute                          "/"
├── environmentDetailRoute              "/environments/$environmentId"
├── deployFormRoute                     "/environments/$environmentId/deploy"
├── deploymentDetailRoute               "/environments/$environmentId/deployments/$deploymentId"
├── backupStorageLocationListRoute      "/backup-storage-locations"
├── backupStorageLocationDetailRoute    "/backup-storage-locations/$id"
├── driverListRoute                     "/drivers"
├── addDriverRoute                      "/drivers/add"
├── driverDetailRoute                   "/drivers/$driverId"
├── settingsRoute                       "/settings"
└── clusterDetailRoute                  "/settings/clusters/$clusterId"
```

**Note**: All routes are direct children of `rootRoute` (flat hierarchy under AppShell). There are no nested layout routes beyond the root.

### Type Registration

The router type is registered globally via TypeScript module augmentation:

```typescript
declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router  // Enables type-safe Link, useNavigate, useParams
  }
}
```

This registration enables:
- `Link` `to` prop autocompletes to valid route paths only
- `useNavigate()` validates `to` + `params` combinations at compile time
- `Route.useParams()` returns the exact param shape for each route

## State Transitions

N/A — routes are stateless definitions. No entity state transitions apply.

## Validation Rules

- Route parameters are always `string` (parsed from URL segments)
- Parameter values must be non-empty (enforced by URL matching — empty segments don't match `$param`)
- UUIDs and other parameter formats are validated by the consuming page component, not by the router (consistent with current behavior)
