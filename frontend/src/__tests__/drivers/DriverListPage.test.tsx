import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
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
import { Toaster } from "@/components/ui/toast";
import DriverListPage from "@/pages/drivers/DriverListPage";
import type { ListDriversQuery } from "@/generated/graphql";

const useListDriversQueryMock = vi.fn();
vi.mock("@/generated/graphql", async () => {
  const actual = await vi.importActual<typeof import("@/generated/graphql")>(
    "@/generated/graphql",
  );
  return {
    ...actual,
    useListDriversQuery: (...args: unknown[]) =>
      useListDriversQueryMock(...args),
  };
});

type Role = "READ_ONLY" | "READ_WRITE" | "ADMIN";
function makeAuthValue(role: Role): AuthContextValue {
  const user: CurrentUser = {
    id: "u",
    username: "u",
    displayName: "U",
    role,
    effectiveRole: role,
    active: true,
  };
  return {
    currentUser: user,
    loading: false,
    refresh: () => Promise.resolve(),
    logout: () => Promise.resolve(),
  };
}

type Driver = ListDriversQuery["applicationDrivers"][number];
type Version = Driver["versions"][number];

function mkVersion(id: string, version: string, createdOn: string): Version {
  return {
    id,
    version,
    supportedVersions: ">=1.0,<2.0",
    sourceType: "git",
    sourceRepository: "opsmill/drivers",
    sourceBranch: "main",
    sourcePath: null,
    sourceCommitSha: "abc1234",
    contentHash: null,
    createdOn,
  } as Version;
}

function data(drivers: Driver[]): ListDriversQuery {
  return { applicationDrivers: drivers } as ListDriversQuery;
}

const DRIVERS: Driver[] = [
  {
    id: "id-grafana",
    name: "grafana",
    versions: [mkVersion("g1", "1.4.2", "2026-02-01T00:00:00Z")],
  } as Driver,
  {
    id: "id-infrahub",
    name: "infrahub",
    versions: [
      mkVersion("i1", "2.0.3", "2026-01-01T00:00:00Z"),
      mkVersion("i2", "2.1.0", "2026-03-01T00:00:00Z"),
    ],
  } as Driver,
];

function makeRouter() {
  const rootRoute = createRootRoute();
  const listRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/drivers",
    component: () => <DriverListPage />,
  });
  const detailRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/drivers/$driverId",
    validateSearch: (s: Record<string, unknown>) => ({
      version: typeof s.version === "string" ? s.version : undefined,
    }),
    component: () => <div>driver detail page</div>,
  });
  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/",
    component: () => <div>home</div>,
  });
  return createRouter({
    routeTree: rootRoute.addChildren([indexRoute, listRoute, detailRoute]),
    history: createMemoryHistory({ initialEntries: ["/drivers"] }),
  });
}

async function renderPage(role: Role = "READ_WRITE") {
  const router = makeRouter();
  await router.load();
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  await act(async () => {
    render(
      <ThemeProvider>
        <QueryClientProvider client={qc}>
          <AuthContext.Provider value={makeAuthValue(role)}>
            <Toaster>
              <RouterProvider router={router} />
            </Toaster>
          </AuthContext.Provider>
        </QueryClientProvider>
      </ThemeProvider>,
    );
  });
}

function ok(d: ListDriversQuery) {
  return { data: d, isLoading: false, error: null, refetch: vi.fn() };
}

describe("DriverListPage", () => {
  beforeEach(() => useListDriversQueryMock.mockReset());
  afterEach(() => vi.restoreAllMocks());

  it("renders the empty state when no drivers are loaded", async () => {
    useListDriversQueryMock.mockReturnValue(ok(data([])));
    await renderPage();
    expect(screen.getByText(/no drivers loaded yet/i)).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: /load driver/i }).length,
    ).toBeGreaterThan(0);
  });

  it("groups by application by default and lists version rows", async () => {
    useListDriversQueryMock.mockReturnValue(ok(data(DRIVERS)));
    await renderPage();
    expect(screen.getByText("grafana")).toBeInTheDocument();
    expect(screen.getByText("infrahub")).toBeInTheDocument();
    expect(screen.getByText("2.1.0")).toBeInTheDocument();
    expect(screen.getByText("2.0.3")).toBeInTheDocument();
  });

  it("filters live and highlights the match", async () => {
    useListDriversQueryMock.mockReturnValue(ok(data(DRIVERS)));
    await renderPage();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Filter drivers"), "infra");
    await waitFor(() => {
      expect(screen.queryByText("grafana")).not.toBeInTheDocument();
    });
    const mark = screen.getByText("infra");
    expect(mark.tagName).toBe("MARK");
  });

  it("navigates to the version detail when a row is clicked", async () => {
    useListDriversQueryMock.mockReturnValue(ok(data(DRIVERS)));
    await renderPage();
    const user = userEvent.setup();
    await user.click(screen.getByText("2.1.0"));
    await waitFor(() => {
      expect(screen.getByText("driver detail page")).toBeInTheDocument();
    });
  });

  it("hides the Load driver action for a read-only user", async () => {
    useListDriversQueryMock.mockReturnValue(ok(data(DRIVERS)));
    await renderPage("READ_ONLY");
    expect(
      screen.queryByRole("button", { name: /load driver/i }),
    ).not.toBeInTheDocument();
  });
});
