import { createRoute, lazyRouteComponent } from "@tanstack/react-router";
import { rootRoute } from "./__root";

export const addDriverRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/drivers/add",
  component: lazyRouteComponent(() => import("@/pages/drivers/AddDriverPage")),
});
