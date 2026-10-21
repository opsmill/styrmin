/**
 * The Backup Storage Location select on the environment's Parameters tab
 * shows the name of the assigned location, not its id.
 */
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, waitFor, act, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createRouter,
  createRootRoute,
  createRoute,
  createMemoryHistory,
  RouterProvider,
} from "@tanstack/react-router";

import { AuthContext, type AuthContextValue } from "@/auth/AuthProvider";
import EnvironmentDetailPage from "@/pages/environments/EnvironmentDetailPage";

const ENVIRONMENT_ID = "env-1";
const LOCATION = { id: "d71fa4f9-e68d-4640-b9e4-b5200000000a", name: "local" };

const AUTH: AuthContextValue = {
  currentUser: {
    id: "user-admin",
    username: "admin",
    displayName: "Admin",
    role: "ADMIN",
    effectiveRole: "ADMIN",
    active: true,
  },
  loading: false,
  refresh: () => Promise.resolve(),
  logout: () => Promise.resolve(),
};

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

/** Answer the page's queries; ``listed`` is what ListBackupStorageLocations returns. */
function installFetch(listed: (typeof LOCATION)[]): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: unknown, init?: RequestInit) => {
      const body = typeof init?.body === "string" ? init.body : "";
      if (body.includes("GetEnvironment")) {
        return jsonResponse({
          data: {
            environment: {
              id: ENVIRONMENT_ID,
              name: "network-lab-upgrade",
              config: {},
              cluster: { id: "cluster-1", name: "local" },
              backupStorageLocation: LOCATION,
              deployments: [],
            },
          },
        });
      }
      if (body.includes("ListBackupStorageLocations")) {
        return jsonResponse({
          data: {
            backupStorageLocations: listed.map((location) => ({
              ...location,
              endpoint: "http://garage.styrmin.svc:3900",
              bucket: "velero",
              region: "garage",
              createdOn: "2026-10-21T00:00:00Z",
              updatedOn: null,
              environmentCount: 1,
            })),
          },
        });
      }
      return jsonResponse({ data: {} });
    }),
  );
}

async function openParametersTab(): Promise<HTMLElement> {
  const rootRoute = createRootRoute();
  const environmentRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/environments/$environmentId",
    component: EnvironmentDetailPage,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([environmentRoute]),
    history: createMemoryHistory({
      initialEntries: [`/environments/${ENVIRONMENT_ID}`],
    }),
  });
  await router.load();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  await act(async () => {
    render(
      <AuthContext.Provider value={AUTH}>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </AuthContext.Provider>,
    );
  });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Parameters" }));
  return screen.getByTestId("bsl-selector");
}

describe("EnvironmentDetailPage backup storage location select", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the name of the assigned location, not its id", async () => {
    installFetch([LOCATION]);

    const selector = await openParametersTab();

    const trigger = within(selector).getByRole("combobox");
    await waitFor(() => expect(trigger).toHaveTextContent("local"));
    expect(trigger).not.toHaveTextContent(LOCATION.id);
  });

  it("shows the name before the list of locations has loaded", async () => {
    // The list query returns no location, as while it is still loading.
    installFetch([]);

    const selector = await openParametersTab();

    const trigger = within(selector).getByRole("combobox");
    await waitFor(() => expect(trigger).toHaveTextContent("local"));
    expect(trigger).not.toHaveTextContent(LOCATION.id);
  });
});
