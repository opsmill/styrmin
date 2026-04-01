import { createRoute, lazyRouteComponent } from "@tanstack/react-router";
import { rootRoute } from "./__root";

export const deployFormRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/environments/$environmentId/deploy",
  component: lazyRouteComponent(
    () => import("@/pages/deployments/DeployFormPage"),
  ),
});
