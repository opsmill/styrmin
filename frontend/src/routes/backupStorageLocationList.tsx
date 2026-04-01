import { createRoute, lazyRouteComponent } from "@tanstack/react-router";
import { rootRoute } from "./__root";

export const backupStorageLocationListRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/backup-storage-locations",
  component: lazyRouteComponent(
    () =>
      import("@/pages/backup-storage-locations/BackupStorageLocationListPage"),
  ),
});
