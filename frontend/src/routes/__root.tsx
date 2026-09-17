import { createRootRouteWithContext, redirect } from "@tanstack/react-router";
import { AppShell } from "@/components/AppShell";
import { NotFound } from "@/components/NotFound";
import { safeNext } from "@/lib/safe-next";
import type { AuthContextValue } from "@/auth/AuthProvider";

// Re-declare the router context shape here to avoid a circular import with
// router.ts (which imports the route tree, which imports this module).
interface RouterContext {
  auth?: AuthContextValue;
}

const PUBLIC_PATHS: ReadonlySet<string> = new Set(["/login"]);

function requireAuth({
  context,
  location,
}: {
  context: RouterContext;
  location: { pathname: string };
}): void {
  if (PUBLIC_PATHS.has(location.pathname)) {
    return;
  }
  if (context.auth?.currentUser == null) {
    // Preserve the intended destination so the user lands back where they
    // were trying to go after sign-in. Only the pathname is forwarded —
    // search/hash are dropped to avoid leaking tokens or other sensitive
    // query params through the login URL bar / browser history.
    const next = safeNext(location.pathname);
    throw redirect({
      to: "/login",
      search: next == null ? undefined : { next },
    });
  }
}

export const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: AppShell,
  beforeLoad: requireAuth,
  notFoundComponent: NotFound,
});
