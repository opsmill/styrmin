/**
 * Settings page browser tab title (issue #332).
 *
 * Covers the static-title half of the convention: a page with no loaded object
 * names itself directly, so the tab never shows the Vite scaffold default.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { render, act, waitFor } from "@testing-library/react";
import {
  createRouter,
  createRootRoute,
  createRoute,
  createMemoryHistory,
  RouterProvider,
} from "@tanstack/react-router";

import {
  AuthContext,
  type AuthContextValue,
  type CurrentUser,
} from "@/auth/AuthProvider";
import { ThemeProvider } from "@/hooks/use-theme";
import SettingsPage from "./SettingsPage";

function makeAuthValue(): AuthContextValue {
  const user: CurrentUser = {
    id: "user-admin",
    username: "admin",
    displayName: "Admin",
    role: "ADMIN",
    effectiveRole: "ADMIN",
    active: true,
  };
  return {
    currentUser: user,
    loading: false,
    refresh: () => Promise.resolve(),
    logout: () => Promise.resolve(),
  };
}

async function renderPage() {
  const rootRoute = createRootRoute();
  const settingsRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/settings",
    component: () => <SettingsPage />,
  });
  // The page links to these; registering them keeps `<Link to=...>` resolvable.
  const usersRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/users",
    component: () => <div>users</div>,
  });
  const groupsRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/groups",
    component: () => <div>groups</div>,
  });

  const router = createRouter({
    routeTree: rootRoute.addChildren([settingsRoute, usersRoute, groupsRoute]),
    history: createMemoryHistory({ initialEntries: ["/settings"] }),
  });
  await router.load();

  await act(async () => {
    render(
      <ThemeProvider>
        <AuthContext.Provider value={makeAuthValue()}>
          <RouterProvider router={router} />
        </AuthContext.Provider>
      </ThemeProvider>,
    );
  });
}

describe("settings page document title", () => {
  beforeEach(() => {
    document.title = "";
  });

  it("names the page in the tab title", async () => {
    await renderPage();

    await waitFor(() => expect(document.title).toBe("Settings · Styrmin"));
  });
});
