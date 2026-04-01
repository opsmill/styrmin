import { createRoute, lazyRouteComponent } from "@tanstack/react-router";
import { rootRoute } from "./__root";

export const driverDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/drivers/$driverId",
  component: lazyRouteComponent(
    () => import("@/pages/drivers/DriverDetailPage"),
  ),
});
