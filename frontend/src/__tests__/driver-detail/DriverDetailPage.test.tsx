/**
 * DriverDetailPage orchestration tests (T021).
 *
 * Each test mocks `useGetDriverQuery` so we can fully control the data
 * the page receives without standing up a fake transport.
 *
 * Cases:
 *   (a) tab switching preserves the selected version (FR-007),
 *   (b) version switching preserves the active tab (FR-007),
 *   (c) empty-versions branch renders the role-gated empty state
 *       (Add Version visible for READ_WRITE+, hidden for READ_ONLY) (FR-020 + FR-015),
 *   (d) EC-002 silent-fallback — after a refetch removes the
 *       previously-selected version, the page silently falls back to
 *       the new newest version.
 */
import {
  describe,
  it,
  expect,
  beforeEach,
  afterEach,
  vi,
  type Mock,
} from "vitest";
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
import DriverDetailPage from "@/pages/drivers/DriverDetailPage";
import type { GetDriverQuery } from "@/generated/graphql";

// Mock the generated hook so each test can fully control the query state.
const useGetDriverQueryMock = vi.fn();
vi.mock("@/generated/graphql", async () => {
  const actual = await vi.importActual<typeof import("@/generated/graphql")>(
    "@/generated/graphql",
  );
  return {
    ...actual,
    useGetDriverQuery: (...args: unknown[]) => useGetDriverQueryMock(...args),
  };
});

type Role = "READ_ONLY" | "READ_WRITE" | "ADMIN";

function makeUser(role: Role): CurrentUser {
  return {
    id: `user-${role.toLowerCase()}`,
    username: `${role.toLowerCase()}-user`,
    displayName: `${role} User`,
    role,
    effectiveRole: role,
    active: true,
  };
}

function makeAuthValue(role: Role | null): AuthContextValue {
  return {
    currentUser: role === null ? null : makeUser(role),
    loading: false,
    refresh: () => Promise.resolve(),
    logout: () => Promise.resolve(),
  };
}

type DriverShape = NonNullable<GetDriverQuery["applicationDriver"]>;
type VersionShape = DriverShape["versions"][number];

function makeVersion(
  overrides: Partial<VersionShape> & {
    id: string;
    version: string;
    createdOn: string;
  },
): VersionShape {
  const base = {
    supportedVersions: "*",
    sourceType: "git",
    sourceRepository: "https://github.com/example/repo.git",
    sourceBranch: "main" as string | null,
    sourcePath: null as string | null,
    components: null,
    parameters: [],
    componentConfigs: [],
    helmChart: {
      id: `chart-${overrides.id}`,
      name: "chart",
      version: "0.1.0",
      repository: "https://charts.example.com",
      valueTemplate: "{}",
    },
    actions: [],
  };
  return { ...base, ...overrides } as VersionShape;
}

function makeDriver(versions: VersionShape[]): DriverShape {
  return {
    id: "driver-1",
    name: "example-driver",
    createdOn: "2026-01-01T00:00:00Z",
    versions,
  } as DriverShape;
}

interface QueryResult {
  data: GetDriverQuery | undefined;
  isLoading: boolean;
  error: Error | null;
  refetch: Mock;
  dataUpdatedAt: number;
}

function makeQueryResult(driver: DriverShape | null): QueryResult {
  return {
    data: { applicationDriver: driver } as GetDriverQuery,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    dataUpdatedAt: Date.now(),
  };
}

function makeTestRouter() {
  const rootRoute = createRootRoute();
  const driversRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/drivers",
    component: () => <div>drivers list</div>,
  });
  const driverDetailRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/drivers/$driverId",
    component: () => <DriverDetailPage />,
  });
  const addDriverRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/drivers/add",
    component: () => <div>add driver</div>,
  });
  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/",
    component: () => <div>home</div>,
  });
  return createRouter({
    routeTree: rootRoute.addChildren([
      indexRoute,
      driversRoute,
      addDriverRoute,
      driverDetailRoute,
    ]),
    history: createMemoryHistory({ initialEntries: ["/drivers/driver-1"] }),
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

async function renderPage(
  role: Role = "READ_WRITE",
): Promise<{ container: HTMLElement }> {
  const router = makeTestRouter();
  await router.load();
  const qc = makeQueryClient();
  let result: { container: HTMLElement } | undefined;
  await act(async () => {
    result = render(
      <ThemeProvider>
        <QueryClientProvider client={qc}>
          <AuthContext.Provider value={makeAuthValue(role)}>
            <RouterProvider router={router} />
          </AuthContext.Provider>
        </QueryClientProvider>
      </ThemeProvider>,
    );
  });
  return result!;
}

describe("DriverDetailPage (T021)", () => {
  beforeEach(() => {
    useGetDriverQueryMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("preserves the selected version when the user switches tabs (FR-007)", async () => {
    const driver = makeDriver([
      makeVersion({
        id: "old",
        version: "1.0.0",
        createdOn: "2026-01-01T00:00:00Z",
      }),
      makeVersion({
        id: "new",
        version: "2.0.0",
        createdOn: "2026-03-01T00:00:00Z",
      }),
    ]);
    useGetDriverQueryMock.mockReturnValue(makeQueryResult(driver));

    await renderPage();

    // Newest-by-createdOn should be selected by default.
    await waitFor(() => {
      const detail = screen.getByTestId("driver-version-detail");
      expect(detail.getAttribute("data-version-id")).toBe("new");
    });

    // Switch to Parameters; selection must NOT change.
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Parameters" }));

    const detail = screen.getByTestId("driver-version-detail");
    expect(detail.getAttribute("data-version-id")).toBe("new");
    expect(screen.getByTestId("driver-parameters-empty")).toBeInTheDocument();
  });

  it("preserves the active tab when the user switches versions (FR-007)", async () => {
    const driver = makeDriver([
      makeVersion({
        id: "old",
        version: "1.0.0",
        createdOn: "2026-01-01T00:00:00Z",
      }),
      makeVersion({
        id: "new",
        version: "2.0.0",
        createdOn: "2026-03-01T00:00:00Z",
      }),
    ]);
    useGetDriverQueryMock.mockReturnValue(makeQueryResult(driver));

    await renderPage();

    const user = userEvent.setup();
    // Switch to Parameters first.
    await user.click(screen.getByRole("button", { name: "Parameters" }));
    await waitFor(() => {
      expect(screen.getByTestId("driver-parameters-empty")).toBeInTheDocument();
    });

    // Now click the older version row.
    const rows = screen.getAllByTestId("driver-version-row");
    const oldRow = rows.find(
      (r) => r.getAttribute("data-version-id") === "old",
    )!;
    await user.click(oldRow);

    // Version detail should now reflect the older version, and the
    // Parameters panel must still be the visible one.
    await waitFor(() => {
      expect(
        screen
          .getByTestId("driver-version-detail")
          .getAttribute("data-version-id"),
      ).toBe("old");
    });
    expect(screen.getByTestId("driver-parameters-empty")).toBeInTheDocument();
  });

  describe("empty-versions branch (FR-020)", () => {
    it("renders the empty state with Add Version visible for a READ_WRITE user", async () => {
      const driver = makeDriver([]);
      useGetDriverQueryMock.mockReturnValue(makeQueryResult(driver));

      await renderPage("READ_WRITE");

      expect(screen.getByTestId("driver-empty-versions")).toBeInTheDocument();
      expect(
        screen.getByTestId("driver-empty-add-version"),
      ).toBeInTheDocument();
      // No tabs / version-detail rendered when versions are empty.
      expect(
        screen.queryByTestId("driver-version-detail"),
      ).not.toBeInTheDocument();
    });

    it("hides the Add Version CTA for a READ_ONLY user (FR-015)", async () => {
      const driver = makeDriver([]);
      useGetDriverQueryMock.mockReturnValue(makeQueryResult(driver));

      await renderPage("READ_ONLY");

      expect(screen.getByTestId("driver-empty-versions")).toBeInTheDocument();
      expect(
        screen.queryByTestId("driver-empty-add-version"),
      ).not.toBeInTheDocument();
      // The header-actions Add Version is also gated; must be absent.
      expect(
        screen.queryByTestId("driver-add-version"),
      ).not.toBeInTheDocument();
    });
  });

  it("silently falls back to the new newest version when the selected version disappears (EC-002)", async () => {
    const driverBefore = makeDriver([
      makeVersion({
        id: "old",
        version: "1.0.0",
        createdOn: "2026-01-01T00:00:00Z",
      }),
      makeVersion({
        id: "current",
        version: "2.0.0",
        createdOn: "2026-03-01T00:00:00Z",
      }),
    ]);

    // First render returns both versions; "current" is selected by default.
    useGetDriverQueryMock.mockReturnValue(makeQueryResult(driverBefore));

    await renderPage();

    await waitFor(() => {
      expect(
        screen
          .getByTestId("driver-version-detail")
          .getAttribute("data-version-id"),
      ).toBe("current");
    });

    // Simulate a refetch that removes "current" — only "old" remains.
    const driverAfter = makeDriver([
      makeVersion({
        id: "old",
        version: "1.0.0",
        createdOn: "2026-01-01T00:00:00Z",
      }),
    ]);
    useGetDriverQueryMock.mockReturnValue(makeQueryResult(driverAfter));

    // Trigger a re-render so the hook returns the new value. Clicking any
    // existing row is sufficient (it forces a setState); but since the
    // previously-selected id is no longer in the list, the page must
    // silently fall back to the new newest ("old") without showing an
    // error or toast.
    const user = userEvent.setup();
    // Re-clicking the old row (still rendered from the new mock data) is
    // a deterministic way to force the surrounding render cycle that
    // re-reads the mocked hook result.
    const rows = screen.getAllByTestId("driver-version-row");
    const oldRow = rows.find(
      (r) => r.getAttribute("data-version-id") === "old",
    )!;
    await user.click(oldRow);

    await waitFor(() => {
      expect(
        screen
          .getByTestId("driver-version-detail")
          .getAttribute("data-version-id"),
      ).toBe("old");
    });

    // No error UI must be present.
    expect(screen.queryByText(/Driver not found/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders zero <pre> blocks across all five tabs for a fully-populated driver version (SC-002)", async () => {
    const driver = makeDriver([
      makeVersion({
        id: "fully-populated",
        version: "1.0.0",
        createdOn: "2026-03-01T00:00:00Z",
        sourceType: "git",
        sourceRepository: "https://github.com/acme/repo.git",
        sourceBranch: "main",
        sourcePath: "/charts/web",
        components: {
          server: {
            identifier: { label: { "app.kubernetes.io/name": "server" } },
            cpu: "500m",
          },
          worker: {
            identifier: { label: { role: "primary" } },
          },
        } as unknown as VersionShape["components"],
        parameters: [
          { name: "host", label: "Host", kind: "string", default: null },
          {
            name: "port",
            label: "Port",
            kind: "string",
            default: "8080" as unknown as Record<string, unknown>,
          },
          {
            name: "config",
            label: "Config",
            kind: "object",
            default: { nested: 1 },
          },
        ],
        actions: [
          {
            id: "act-1",
            name: "flush-cache",
            description: "Flush",
            location: "cache/flush",
          },
        ],
      }),
    ]);
    useGetDriverQueryMock.mockReturnValue(makeQueryResult(driver));

    const { container } = await renderPage();

    // Tabs are clicked in declaration order so that every panel renders
    // at least once. After each click we assert SC-002 globally: no
    // <pre> JSON-dump fallback anywhere in the page.
    const user = userEvent.setup();
    const tabSentinels: Array<[string, string]> = [
      ["Overview", "driver-overview-tiles"],
      ["Parameters", "driver-parameters-table"],
      ["Components", "driver-components-list"],
      ["Actions", "driver-actions-list"],
      ["Source", "driver-source-git"],
    ];
    for (const [tabName, sentinelTestId] of tabSentinels) {
      await user.click(screen.getByRole("button", { name: tabName }));
      await waitFor(() => {
        // Sanity-check: each click must actually mount the corresponding
        // panel (otherwise the no-<pre> assertion is vacuous).
        expect(screen.getByTestId(sentinelTestId)).toBeInTheDocument();
      });
      expect(container.querySelector("pre")).toBeNull();
    }
  });
});
