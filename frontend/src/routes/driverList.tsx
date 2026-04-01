import { createRoute, lazyRouteComponent } from "@tanstack/react-router";
import { rootRoute } from "./__root";

export const driverListRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/drivers",
  component: lazyRouteComponent(() => import("@/pages/drivers/DriverListPage")),
});
