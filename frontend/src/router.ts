import { createRouter } from "@tanstack/react-router";
import { routeTree } from "./routeTree";
import type { AuthContextValue } from "./auth/AuthProvider";

export interface RouterContext {
  // Pushed in by <AuthProvider> via router.update({ context: { auth } }).
  // It is initially undefined while the AuthProvider is still mounting; route
  // `beforeLoad` guards must tolerate that and treat it the same as "no user".
  auth?: AuthContextValue;
}

export const router = createRouter({
  routeTree,
  context: { auth: undefined } satisfies RouterContext,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
