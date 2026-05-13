import { createRoute, lazyRouteComponent } from "@tanstack/react-router";
import { AdminOnly } from "@/auth/AdminOnly";
import { rootRoute } from "./__root";

const LazyGroupDetailPage = lazyRouteComponent(
  () => import("@/pages/groups/GroupDetailPage"),
);

function GroupDetailRouteComponent() {
  return (
    <AdminOnly area="Group detail">
      <LazyGroupDetailPage />
    </AdminOnly>
  );
}

export const groupDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/groups/$id",
  component: GroupDetailRouteComponent,
});
