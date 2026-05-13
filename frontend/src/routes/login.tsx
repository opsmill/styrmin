import {
  createRoute,
  lazyRouteComponent,
  redirect,
} from "@tanstack/react-router";
import { safeNext } from "@/lib/safe-next";
import { rootRoute } from "./__root";

interface LoginSearch {
  next?: string;
}

export const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  validateSearch: (search: Record<string, unknown>): LoginSearch => {
    const candidate = safeNext(search.next);
    return candidate == null ? {} : { next: candidate };
  },
  beforeLoad: ({ context, search }) => {
    // Already authenticated → bounce to the requested `next` if it's a safe
    // same-origin path, otherwise '/'.
    if (context.auth?.currentUser != null) {
      const dest = safeNext(search.next) ?? "/";
      throw redirect({ to: dest });
    }
  },
  component: lazyRouteComponent(() => import("@/pages/login/LoginPage")),
});
