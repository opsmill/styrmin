/**
 * DriverDetailPage tests.
 *
 * The redesigned detail is a persistent header (identity + version switcher +
 * status) over a tabbed body (Overview / Parameters / Components). A single
 * version is addressed by the `?version=<id>` search param, defaulting to the
 * newest by `createdOn`. `useGetDriverQuery` is mocked so each test controls
 * the data.
 *
 * Cases:
 *   (a) defaults to the newest version and marks it "Latest",
 *   (b) `?version` selects an older version and flags "Update available",
 *   (c) tabs switch between Overview / Parameters / Components,
 *   (d) a driver with no versions renders an error (not a crash),
 *   (e) no <pre> JSON-dump fallback renders across tabs (SC-002),
 *   (f) the header logo follows the selected version, with a fallback.
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
import DriverDetailPage from "@/pages/drivers/DriverDetailPage";
import type { GetDriverQuery } from "@/generated/graphql";

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
    supportedVersions: ">=1.0,<2.0",
    sourceType: "git",
    sourceRepository: "https://github.com/example/repo.git",
    sourceBranch: "main" as string | null,
    sourcePath: null as string | null,
    sourceCommitSha: "abcdef1234567890" as string | null,
    contentHash: null as string | null,
    icon: null as string | null,
    description: null as string | null,
    links: [] as Array<{ label: string; url: string }>,
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

function makeTestRouter(initialEntry = "/drivers/driver-1") {
  const rootRoute = createRootRoute();
  const driversRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/drivers",
    component: () => <div>drivers list</div>,
  });
  const driverDetailRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/drivers/$driverId",
    validateSearch: (search: Record<string, unknown>) => ({
      version: typeof search.version === "string" ? search.version : undefined,
    }),
    component: () => <DriverDetailPage />,
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
      driverDetailRoute,
    ]),
    history: createMemoryHistory({ initialEntries: [initialEntry] }),
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
  initialEntry = "/drivers/driver-1",
  role: Role = "READ_WRITE",
): Promise<{ container: HTMLElement }> {
  const router = makeTestRouter(initialEntry);
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

const OLD_LOGO = "https://example.com/logo-v1.svg";
const NEW_LOGO = "https://example.com/logo-v2.svg";

const twoVersions = () =>
  makeDriver([
    makeVersion({
      id: "old",
      version: "1.0.0",
      createdOn: "2026-01-01T00:00:00Z",
      icon: OLD_LOGO,
      description: "Old description",
      links: [{ label: "Docs", url: "https://example.com/docs/v1" }],
    }),
    makeVersion({
      id: "new",
      version: "2.0.0",
      createdOn: "2026-03-01T00:00:00Z",
      icon: NEW_LOGO,
      description: "New description",
      links: [{ label: "Docs", url: "https://example.com/docs/v2" }],
    }),
  ]);

/** The logo in the PageLayout header, next to the driver name. */
function headerLogo(): HTMLElement {
  const header = screen
    .getByRole("heading", { level: 1, name: "example-driver" })
    .closest("header");
  expect(header).not.toBeNull();
  return within(header!).getByTestId("driver-logo");
}

describe("DriverDetailPage", () => {
  beforeEach(() => {
    useGetDriverQueryMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("defaults to the newest version and marks it Latest", async () => {
    useGetDriverQueryMock.mockReturnValue(makeQueryResult(twoVersions()));

    await renderPage();

    await waitFor(() => {
      expect(
        screen.getByTestId("driver-detail").getAttribute("data-version-id"),
      ).toBe("new");
    });
    expect(screen.getByText("Latest")).toBeInTheDocument();
    // A version switcher is offered because there is more than one version.
    expect(screen.getByLabelText("Switch version")).toBeInTheDocument();
  });

  it("selects the ?version version and flags Update available on an older one", async () => {
    useGetDriverQueryMock.mockReturnValue(makeQueryResult(twoVersions()));

    await renderPage("/drivers/driver-1?version=old");

    await waitFor(() => {
      expect(
        screen.getByTestId("driver-detail").getAttribute("data-version-id"),
      ).toBe("old");
    });
    expect(screen.getByText("Older version")).toBeInTheDocument();
    expect(screen.getByText(/newest loaded version/i)).toBeInTheDocument();
  });

  it("switches between Overview, Parameters and Components tabs", async () => {
    const driver = makeDriver([
      makeVersion({
        id: "v1",
        version: "1.0.0",
        createdOn: "2026-03-01T00:00:00Z",
        parameters: [
          { name: "host", label: "Host", kind: "string", default: null },
        ] as unknown as VersionShape["parameters"],
        components: {
          server: { identifier: { label: { app: "server" } }, cpu: 2 },
        } as unknown as VersionShape["components"],
      }),
    ]);
    useGetDriverQueryMock.mockReturnValue(makeQueryResult(driver));

    const user = userEvent.setup();
    await renderPage();

    // Overview is the default tab: the Details panel is visible.
    expect(screen.getByTestId("driver-overview")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /parameters/i }));
    await waitFor(() => {
      expect(screen.getByTestId("driver-parameters-table")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /components/i }));
    await waitFor(() => {
      expect(screen.getByTestId("driver-components-list")).toBeInTheDocument();
    });
  });

  it("renders an error (not a crash) when the driver has no versions", async () => {
    useGetDriverQueryMock.mockReturnValue(makeQueryResult(makeDriver([])));

    await renderPage();

    expect(screen.getByText(/no versions/i)).toBeInTheDocument();
    expect(screen.queryByTestId("driver-detail")).not.toBeInTheDocument();
  });

  it("renders no <pre> JSON dump across tabs (SC-002)", async () => {
    const driver = makeDriver([
      makeVersion({
        id: "full",
        version: "1.0.0",
        createdOn: "2026-03-01T00:00:00Z",
        sourcePath: "/charts/web",
        components: {
          server: {
            identifier: { label: { "app.kubernetes.io/name": "server" } },
            cpu: "500m",
            backup: { enabled: true, kind: "disk" },
          },
        } as unknown as VersionShape["components"],
        parameters: [
          { name: "host", label: "Host", kind: "string", default: null },
          { name: "cfg", label: "Config", kind: "object", default: { a: 1 } },
        ] as unknown as VersionShape["parameters"],
      }),
    ]);
    useGetDriverQueryMock.mockReturnValue(makeQueryResult(driver));

    const user = userEvent.setup();
    const { container } = await renderPage();

    for (const tab of [/overview/i, /parameters/i, /components/i]) {
      await user.click(screen.getByRole("button", { name: tab }));
      expect(container.querySelector("pre")).toBeNull();
    }
  });

  it("shows the selected version's logo in the header and switches with the version", async () => {
    useGetDriverQueryMock.mockReturnValue(makeQueryResult(twoVersions()));

    const user = userEvent.setup();
    await renderPage();

    expect(headerLogo()).toHaveAttribute("data-logo-state", "image");
    expect(headerLogo().querySelector("img")).toHaveAttribute("src", NEW_LOGO);

    await user.click(screen.getByLabelText("Switch version"));
    await user.click(await screen.findByRole("option", { name: /1\.0\.0/ }));

    await waitFor(() => {
      expect(
        screen.getByTestId("driver-detail").getAttribute("data-version-id"),
      ).toBe("old");
    });
    expect(headerLogo()).toHaveAttribute("data-logo-state", "image");
    expect(headerLogo().querySelector("img")).toHaveAttribute("src", OLD_LOGO);
  });

  it("shows the fallback logo in the header when the version has no icon", async () => {
    useGetDriverQueryMock.mockReturnValue(
      makeQueryResult(
        makeDriver([
          makeVersion({
            id: "v1",
            version: "1.0.0",
            createdOn: "2026-03-01T00:00:00Z",
          }),
        ]),
      ),
    );

    await renderPage();

    expect(headerLogo()).toHaveAttribute("data-logo-state", "fallback");
    expect(headerLogo().querySelector("img")).toBeNull();
  });
});
