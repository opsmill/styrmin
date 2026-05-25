import { createRoute, lazyRouteComponent } from "@tanstack/react-router";
import { rootRoute } from "./__root";

export const clusterDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/clusters/$clusterId",
  component: lazyRouteComponent(
    () => import("@/pages/clusters/ClusterDetailPage"),
  ),
});
