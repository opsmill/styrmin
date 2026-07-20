import { createRoute, lazyRouteComponent } from "@tanstack/react-router";
import { rootRoute } from "./__root";

interface DriverDetailSearch {
  version?: string;
}

export const driverDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/drivers/$driverId",
  validateSearch: (search: Record<string, unknown>): DriverDetailSearch => ({
    version: typeof search.version === "string" ? search.version : undefined,
  }),
  component: lazyRouteComponent(
    () => import("@/pages/drivers/DriverDetailPage"),
  ),
});
