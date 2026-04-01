import type { ReactElement } from "react";
import {
  render as rtlRender,
  type RenderOptions,
  screen,
  within,
  waitFor,
} from "@testing-library/react";
import {
  createRouter,
  createRootRoute,
  createRoute,
  createMemoryHistory,
  RouterProvider,
} from "@tanstack/react-router";

interface CustomRenderOptions extends Omit<RenderOptions, "wrapper"> {
  initialLocation?: string;
}

async function render(ui: ReactElement, options?: CustomRenderOptions) {
  const { initialLocation, ...renderOptions } = options ?? {};

  const rootRoute = createRootRoute();
  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/",
    component: () => ui,
  });

  const router = createRouter({
    routeTree: rootRoute.addChildren([indexRoute]),
    history: createMemoryHistory({
      initialEntries: [initialLocation ?? "/"],
    }),
  });

  await router.load();

  return rtlRender(<RouterProvider router={router} />, renderOptions);
}

export { render, screen, within, waitFor };
export { default as userEvent } from "@testing-library/user-event";
