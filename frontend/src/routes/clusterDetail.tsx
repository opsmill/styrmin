import { createRoute, lazyRouteComponent } from "@tanstack/react-router";
import { rootRoute } from "./__root";

export const clusterDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings/clusters/$clusterId",
  component: lazyRouteComponent(
    () => import("@/pages/settings/ClusterDetailPage"),
  ),
});
