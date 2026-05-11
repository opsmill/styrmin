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
import {
  AuthContext,
  type AuthContextValue,
  type CurrentUser,
} from "@/auth/AuthProvider";

interface CustomRenderOptions extends Omit<RenderOptions, "wrapper"> {
  initialLocation?: string;
  /**
   * Override the AuthContext value provided by the test wrapper. When
   * omitted the wrapper supplies a synthetic ADMIN user — enough to
   * make any `<IfRole minimum=...>` wrapper render its children, so
   * tests that don't care about role gating keep behaving as they did
   * before role gates were introduced. Tests that DO care about role
   * gating pass an explicit `auth` value.
   */
  auth?: AuthContextValue;
}

function makeDefaultAuth(): AuthContextValue {
  const user: CurrentUser = {
    id: "test-admin",
    username: "test-admin",
    displayName: "Test Admin",
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
  const { initialLocation, auth, ...renderOptions } = options ?? {};
  const authValue = auth ?? makeDefaultAuth();

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
        <AuthContext.Provider value={authValue}>
          <RouterProvider router={router} />
        </AuthContext.Provider>
      </QueryClientProvider>
    </ThemeProvider>,
    renderOptions,
  );
}

export { render, screen, within, waitFor };
export { default as userEvent } from "@testing-library/user-event";
