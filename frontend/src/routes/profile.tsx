import { createRoute, lazyRouteComponent } from "@tanstack/react-router";
import { rootRoute } from "./__root";

// The root-level `requireAuth` already gates this route: an unauthenticated
// user is redirected to `/login` before this component mounts. We intentionally
// do NOT add an admin gate — any authenticated user may visit their profile.
export const profileRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/profile",
  component: lazyRouteComponent(() => import("@/pages/profile/ProfilePage")),
});
