import { createRoute, lazyRouteComponent } from "@tanstack/react-router";
import { AdminOnly } from "@/auth/AdminOnly";
import { rootRoute } from "./__root";

const LazyUsersListPage = lazyRouteComponent(
  () => import("@/pages/users/UsersListPage"),
);

function UsersListRouteComponent() {
  return (
    <AdminOnly area="Users">
      <LazyUsersListPage />
    </AdminOnly>
  );
}

export const usersListRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/users",
  component: UsersListRouteComponent,
});
