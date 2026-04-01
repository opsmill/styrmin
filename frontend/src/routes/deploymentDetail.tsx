import { createRoute, lazyRouteComponent } from "@tanstack/react-router";
import { rootRoute } from "./__root";

export const deploymentDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/environments/$environmentId/deployments/$deploymentId",
  component: lazyRouteComponent(
    () => import("@/pages/deployments/DeploymentDetailPage"),
  ),
});
