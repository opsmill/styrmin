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
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "@/hooks/use-theme";

interface CustomRenderOptions extends Omit<RenderOptions, "wrapper"> {
  initialLocation?: string;
}

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: Infinity,
      },
      mutations: {
        retry: false,
      },
    },
  });
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

  const queryClient = createTestQueryClient();

  return rtlRender(
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </ThemeProvider>,
    renderOptions,
  );
}

export { render, screen, within, waitFor };
export { default as userEvent } from "@testing-library/user-event";
