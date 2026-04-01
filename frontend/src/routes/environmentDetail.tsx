import { createRoute, lazyRouteComponent } from "@tanstack/react-router";
import { rootRoute } from "./__root";

export const environmentDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/environments/$environmentId",
  component: lazyRouteComponent(
    () => import("@/pages/environments/EnvironmentDetailPage"),
  ),
});
