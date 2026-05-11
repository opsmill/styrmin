import {
  createRoute,
  lazyRouteComponent,
  redirect,
} from "@tanstack/react-router";
import { rootRoute } from "./__root";

export const usersListRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/users",
  beforeLoad: ({ context }) => {
    if (context.auth?.currentUser?.effectiveRole !== "ADMIN") {
      throw redirect({ to: "/" });
    }
  },
  component: lazyRouteComponent(() => import("@/pages/users/UsersListPage")),
});
