import { createRoute, lazyRouteComponent } from "@tanstack/react-router";
import { rootRoute } from "./__root";

export const backupStorageLocationDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/backup-storage-locations/$id",
  component: lazyRouteComponent(
    () =>
      import("@/pages/backup-storage-locations/BackupStorageLocationDetailPage"),
  ),
});
