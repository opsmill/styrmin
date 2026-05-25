import { createRoute, lazyRouteComponent } from "@tanstack/react-router";
import { rootRoute } from "./__root";

export const clusterListRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/clusters",
  component: lazyRouteComponent(
    () => import("@/pages/clusters/ClusterListPage"),
  ),
});
