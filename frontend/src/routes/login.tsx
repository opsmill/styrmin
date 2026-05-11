import {
  createRoute,
  lazyRouteComponent,
  redirect,
} from "@tanstack/react-router";
import { rootRoute } from "./__root";

export const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  beforeLoad: ({ context }) => {
    // Already authenticated → no reason to be on /login; send to '/'.
    if (context.auth?.currentUser != null) {
      throw redirect({ to: "/" });
    }
  },
  component: lazyRouteComponent(() => import("@/pages/login/LoginPage")),
});
