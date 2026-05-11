import { createRootRouteWithContext, redirect } from "@tanstack/react-router";
import { AppShell } from "@/components/AppShell";
import type { AuthContextValue } from "@/auth/AuthProvider";

// Re-declare the router context shape here to avoid a circular import with
// router.ts (which imports the route tree, which imports this module).
interface RouterContext {
  auth?: AuthContextValue;
}

const PUBLIC_PATHS: ReadonlySet<string> = new Set([
  "/login",
]);

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
    throw redirect({ to: "/login" });
  }
}

export const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: AppShell,
  beforeLoad: requireAuth,
  notFoundComponent: () => <div>Page not found</div>,
});
