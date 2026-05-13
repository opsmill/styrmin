import { createRoute, lazyRouteComponent } from "@tanstack/react-router";
import { AdminOnly } from "@/auth/AdminOnly";
import { rootRoute } from "./__root";

const LazyUserDetailPage = lazyRouteComponent(
  () => import("@/pages/users/UserDetailPage"),
);

function UserDetailRouteComponent() {
  return (
    <AdminOnly area="User detail">
      <LazyUserDetailPage />
    </AdminOnly>
  );
}

export const userDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/users/$id",
  component: UserDetailRouteComponent,
});
