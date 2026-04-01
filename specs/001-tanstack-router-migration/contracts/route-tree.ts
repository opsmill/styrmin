/**
 * Route Tree Contract — TanStack Router Migration
 *
 * This file defines the target route tree structure as a type contract.
 * It is NOT production code — it documents the expected API surface
 * that the implementation must satisfy.
 */

// === Route Paths (exhaustive list) ===

type RoutePaths =
  | "/"
  | "/environments/$environmentId"
  | "/environments/$environmentId/deploy"
  | "/environments/$environmentId/deployments/$deploymentId"
  | "/backup-storage-locations"
  | "/backup-storage-locations/$id"
  | "/drivers"
  | "/drivers/add"
  | "/drivers/$driverId"
  | "/settings"
  | "/settings/clusters/$clusterId";

// === Route Parameter Types (per route) ===

interface RouteParams {
  "/": Record<string, never>;
  "/environments/$environmentId": { environmentId: string };
  "/environments/$environmentId/deploy": { environmentId: string };
  "/environments/$environmentId/deployments/$deploymentId": {
    environmentId: string;
    deploymentId: string;
  };
  "/backup-storage-locations": Record<string, never>;
  "/backup-storage-locations/$id": { id: string };
  "/drivers": Record<string, never>;
  "/drivers/add": Record<string, never>;
  "/drivers/$driverId": { driverId: string };
  "/settings": Record<string, never>;
  "/settings/clusters/$clusterId": { clusterId: string };
}

// === Navigation Contract ===

/**
 * All `Link` and `useNavigate` calls must satisfy:
 * - `to` is one of `RoutePaths`
 * - `params` matches `RouteParams[to]` when the route has params
 * - Compile-time error if `to` or `params` are invalid
 *
 * Examples:
 *   <Link to="/environments/$environmentId" params={{ environmentId: "uuid" }}>
 *   navigate({ to: "/drivers/$driverId", params: { driverId: "uuid" } })
 */

// === useParams Contract ===

/**
 * Within a route component, `Route.useParams()` returns:
 * - The exact `RouteParams[path]` for that route
 * - All params are `string` (non-optional, non-undefined)
 *
 * Example (in EnvironmentDetailPage):
 *   const { environmentId } = Route.useParams()
 *   // environmentId: string (not string | undefined)
 */

// === Layout Contract ===

/**
 * Root route renders AppShell with <Outlet />.
 * All 11 routes are direct children of root route.
 * No nested layout routes.
 */

export type { RoutePaths, RouteParams };
