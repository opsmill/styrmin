/**
 * DeployFormPage driver-version dropdown tests (feature 013 follow-up).
 *
 * Asserts the trigger and items each render
 * `<driverName> v<version>@<short>` for fixture drivers with content
 * hashes, and that two driver versions with the same `version` string
 * but different fingerprints render as visually distinct options.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
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

import {
  AuthContext,
  type AuthContextValue,
  type CurrentUser,
} from "@/auth/AuthProvider";
import { ThemeProvider } from "@/hooks/use-theme";
import DeployFormPage from "@/pages/deployments/DeployFormPage";
import type { ListApplicationDriversQuery } from "@/generated/graphql";

const useListApplicationDriversQueryMock = vi.fn();
const noopMutationResult = {
  mutateAsync: vi.fn().mockResolvedValue({}),
  mutate: vi.fn(),
  isPending: false,
  isError: false,
  error: null,
};
vi.mock("@/generated/graphql", async () => {
  const actual = await vi.importActual<typeof import("@/generated/graphql")>(
    "@/generated/graphql",
  );
  return {
    ...actual,
    useListApplicationDriversQuery: (...args: unknown[]) =>
      useListApplicationDriversQueryMock(...args),
    useDeployMutation: () => noopMutationResult,
  };
});

function makeUser(): CurrentUser {
  return {
    id: "user-rw",
    username: "rw-user",
    displayName: "RW User",
    role: "READ_WRITE",
    effectiveRole: "READ_WRITE",
    active: true,
  };
}

function makeAuthValue(): AuthContextValue {
  return {
    currentUser: makeUser(),
    loading: false,
    refresh: () => Promise.resolve(),
    logout: () => Promise.resolve(),
  };
}

type DriversShape = ListApplicationDriversQuery["applicationDrivers"];

function makeQueryResult(drivers: DriversShape) {
  return {
    data: { applicationDrivers: drivers } as ListApplicationDriversQuery,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    dataUpdatedAt: Date.now(),
  };
}

function makeTestRouter() {
  const rootRoute = createRootRoute();
  const homeRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/",
    component: () => <div>home</div>,
  });
  const envRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/environments/$environmentId",
    component: () => <div>environment</div>,
  });
  const deployRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/environments/$environmentId/deploy",
    component: () => <DeployFormPage />,
  });
  return createRouter({
    routeTree: rootRoute.addChildren([homeRoute, envRoute, deployRoute]),
    history: createMemoryHistory({
      initialEntries: ["/environments/env-1/deploy"],
    }),
  });
}

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

async function renderPage() {
  const router = makeTestRouter();
  await router.load();
  const qc = makeQueryClient();
  await act(async () => {
    render(
      <ThemeProvider>
        <QueryClientProvider client={qc}>
          <AuthContext.Provider value={makeAuthValue()}>
            <RouterProvider router={router} />
          </AuthContext.Provider>
        </QueryClientProvider>
      </ThemeProvider>,
    );
  });
}

describe("DeployFormPage driver-version dropdown", () => {
  beforeEach(() => {
    useListApplicationDriversQueryMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders each dropdown option as <driverName> v<version>@<short>", async () => {
    const drivers: DriversShape = [
      {
        id: "drv-nginx",
        name: "nginx",
        versions: [
          {
            id: "v-nginx-1",
            version: "1.2.3",
            supportedVersions: "*",
            defaultVersion: null,
            contentHash: "a".repeat(64),
            sourceCommitSha: null,
            parameters: [],
          },
        ],
      },
      {
        id: "drv-redis",
        name: "redis",
        versions: [
          {
            id: "v-redis-1",
            version: "2.0.0",
            supportedVersions: "*",
            defaultVersion: null,
            contentHash: null,
            sourceCommitSha: "b".repeat(40),
            parameters: [],
          },
        ],
      },
    ] as DriversShape;
    useListApplicationDriversQueryMock.mockReturnValue(
      makeQueryResult(drivers),
    );

    await renderPage();

    const user = userEvent.setup();
    const trigger = await screen.findByTestId("driver-version-select");
    await user.click(trigger);

    // Each option renders `<driverName> v<version>@<short>`.
    await waitFor(() => {
      expect(screen.getByText("nginx v1.2.3@aaaaaaa")).toBeInTheDocument();
    });
    expect(screen.getByText("redis v2.0.0@bbbbbbb")).toBeInTheDocument();
  });

  it("shows the same formatted label on the trigger when a version is selected", async () => {
    const drivers: DriversShape = [
      {
        id: "drv-nginx",
        name: "nginx",
        versions: [
          {
            id: "v-nginx-1",
            version: "1.2.3",
            supportedVersions: "*",
            defaultVersion: null,
            contentHash: "a".repeat(64),
            sourceCommitSha: null,
            parameters: [],
          },
        ],
      },
    ] as DriversShape;
    useListApplicationDriversQueryMock.mockReturnValue(
      makeQueryResult(drivers),
    );

    await renderPage();

    const user = userEvent.setup();
    const trigger = await screen.findByTestId("driver-version-select");
    await user.click(trigger);

    const option = await screen.findByText("nginx v1.2.3@aaaaaaa");
    await user.click(option);

    await waitFor(() => {
      const trigger2 = screen.getByTestId("driver-version-select");
      expect(
        within(trigger2).getByText("nginx v1.2.3@aaaaaaa"),
      ).toBeInTheDocument();
    });
  });

  it("renders two same-version different-fingerprint driver versions as visually distinct options", async () => {
    const drivers: DriversShape = [
      {
        id: "drv-nginx",
        name: "nginx",
        versions: [
          {
            id: "v-nginx-old",
            version: "1.2.3",
            supportedVersions: "*",
            defaultVersion: null,
            contentHash: "a".repeat(64),
            sourceCommitSha: null,
            parameters: [],
          },
          {
            id: "v-nginx-new",
            version: "1.2.3",
            supportedVersions: "*",
            defaultVersion: null,
            contentHash: "c".repeat(64),
            sourceCommitSha: null,
            parameters: [],
          },
        ],
      },
    ] as DriversShape;
    useListApplicationDriversQueryMock.mockReturnValue(
      makeQueryResult(drivers),
    );

    await renderPage();

    const user = userEvent.setup();
    const trigger = await screen.findByTestId("driver-version-select");
    await user.click(trigger);

    await waitFor(() => {
      expect(screen.getByText("nginx v1.2.3@aaaaaaa")).toBeInTheDocument();
    });
    expect(screen.getByText("nginx v1.2.3@ccccccc")).toBeInTheDocument();
  });
});
