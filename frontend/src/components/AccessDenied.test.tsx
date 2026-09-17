/**
 * Access-denied browser tab title (issue #332 review follow-up).
 *
 * `AdminOnly` renders this fallback *instead of* the page component, so the
 * page's own `useDocumentTitle` never runs. Without a call here the tab keeps
 * the title of whatever page the user navigated from.
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

import { ThemeProvider } from "@/hooks/use-theme";
import { AccessDenied } from "./AccessDenied";

async function renderAccessDenied() {
  const rootRoute = createRootRoute();
  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/",
    component: () => <AccessDenied area="Users" requiredRole="ADMIN" />,
  });

  const router = createRouter({
    routeTree: rootRoute.addChildren([indexRoute]),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();

  await act(async () => {
    render(
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>,
    );
  });
}

describe("access denied document title", () => {
  beforeEach(() => {
    document.title = "Users · Styrmin";
  });

  it("retitles the tab instead of inheriting the previous page's title", async () => {
    await renderAccessDenied();

    await waitFor(() => expect(document.title).toBe("Access denied · Styrmin"));
  });
});
