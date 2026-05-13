import { createRoute, lazyRouteComponent } from "@tanstack/react-router";
import { AdminOnly } from "@/auth/AdminOnly";
import { rootRoute } from "./__root";

const LazyGroupsListPage = lazyRouteComponent(
  () => import("@/pages/groups/GroupsListPage"),
);

function GroupsListRouteComponent() {
  return (
    <AdminOnly area="Groups">
      <LazyGroupsListPage />
    </AdminOnly>
  );
}

export const groupsListRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/groups",
  component: GroupsListRouteComponent,
});
