import {
  createRoute,
  lazyRouteComponent,
  redirect,
} from "@tanstack/react-router";
import { rootRoute } from "./__root";

export const userDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/users/$id",
  beforeLoad: ({ context }) => {
    if (context.auth?.currentUser?.effectiveRole !== "ADMIN") {
      throw redirect({ to: "/" });
    }
  },
  component: lazyRouteComponent(() => import("@/pages/users/UserDetailPage")),
});
