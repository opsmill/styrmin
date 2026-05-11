import {
  createRoute,
  lazyRouteComponent,
  redirect,
} from "@tanstack/react-router";
import { rootRoute } from "./__root";

export const groupDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/groups/$id",
  beforeLoad: ({ context }) => {
    if (context.auth?.currentUser?.effectiveRole !== "ADMIN") {
      throw redirect({ to: "/" });
    }
  },
  component: lazyRouteComponent(() => import("@/pages/groups/GroupDetailPage")),
});
