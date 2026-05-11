import {
  createRoute,
  lazyRouteComponent,
  redirect,
} from "@tanstack/react-router";
import { rootRoute } from "./__root";

export const groupsListRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/groups",
  beforeLoad: ({ context }) => {
    if (context.auth?.currentUser?.effectiveRole !== "ADMIN") {
      throw redirect({ to: "/" });
    }
  },
  component: lazyRouteComponent(() => import("@/pages/groups/GroupsListPage")),
});
