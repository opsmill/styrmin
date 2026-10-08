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

function mkVersion(
  id: string,
  version: string,
  createdOn: string,
  icon: string | null = null,
  description: string | null = null,
): Version {
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
    icon,
    description,
  } as Version;
}

function data(drivers: Driver[]): ListDriversQuery {
  return { applicationDrivers: drivers } as ListDriversQuery;
}

const INFRAHUB_OLD_LOGO = "https://example.com/infrahub-old.svg";
const INFRAHUB_NEW_LOGO = "https://example.com/infrahub-new.svg";
const INFRAHUB_OLD_DESCRIPTION = "Old Infrahub description";
const INFRAHUB_NEW_DESCRIPTION =
  "Infrahub is a source of truth and network automation platform for the whole infrastructure";

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
      mkVersion(
        "i1",
        "2.0.3",
        "2026-01-01T00:00:00Z",
        INFRAHUB_OLD_LOGO,
        INFRAHUB_OLD_DESCRIPTION,
      ),
      mkVersion(
        "i2",
        "2.1.0",
        "2026-03-01T00:00:00Z",
        INFRAHUB_NEW_LOGO,
        INFRAHUB_NEW_DESCRIPTION,
      ),
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

function driverGroup(driverName: string): HTMLElement {
  const group = document.querySelector<HTMLElement>(
    `[data-testid="driver-group"][data-driver-name="${driverName}"]`,
  );
  expect(group).not.toBeNull();
  return group!;
}

function groupLogo(driverName: string): HTMLElement {
  return within(driverGroup(driverName)).getByTestId("driver-logo");
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

  it("shows the Latest badge only on a multi-version driver's latest-wins winner", async () => {
    useListDriversQueryMock.mockReturnValue(ok(data(DRIVERS)));
    await renderPage();
    // exactly one badge: infrahub's 2.1.0 — grafana has a single version, so
    // its only (trivially latest) version carries no badge
    expect(screen.getAllByText("Latest")).toHaveLength(1);

    // narrowing the filter to the older version must not transfer the badge
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Filter drivers"), "2.0.3");
    await waitFor(() => {
      expect(screen.queryByText("2.1.0")).not.toBeInTheDocument();
    });
    expect(screen.queryByText("Latest")).not.toBeInTheDocument();
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

  it("shows the latest version's logo in the group header", async () => {
    useListDriversQueryMock.mockReturnValue(ok(data(DRIVERS)));
    await renderPage();
    const logo = groupLogo("infrahub");
    expect(logo).toHaveAttribute("data-logo-state", "image");
    expect(logo.querySelector("img")).toHaveAttribute("src", INFRAHUB_NEW_LOGO);

    // filtering down to the older version keeps the latest version's logo
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Filter drivers"), "2.0.3");
    await waitFor(() => {
      expect(screen.queryByText("2.1.0")).not.toBeInTheDocument();
    });
    expect(groupLogo("infrahub").querySelector("img")).toHaveAttribute(
      "src",
      INFRAHUB_NEW_LOGO,
    );
  });

  it("shows the fallback logo for a driver without an icon", async () => {
    useListDriversQueryMock.mockReturnValue(ok(data(DRIVERS)));
    await renderPage();
    const logo = groupLogo("grafana");
    expect(logo).toHaveAttribute("data-logo-state", "fallback");
    expect(logo.querySelector("img")).toBeNull();
  });

  it("shows one logo per row, for the row's own version, in the flat view", async () => {
    useListDriversQueryMock.mockReturnValue(ok(data(DRIVERS)));
    await renderPage();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Flat list" }));
    await waitFor(() => {
      expect(
        document.querySelector('[data-testid="driver-group"]'),
      ).not.toBeInTheDocument();
    });

    // rows: grafana 1.4.2, infrahub 2.1.0, infrahub 2.0.3
    const logos = screen.getAllByTestId("driver-logo");
    expect(logos).toHaveLength(3);
    expect(logos.map((l) => l.getAttribute("data-logo-state"))).toEqual([
      "fallback",
      "image",
      "image",
    ]);
    expect(logos[1].querySelector("img")).toHaveAttribute(
      "src",
      INFRAHUB_NEW_LOGO,
    );
    expect(logos[2].querySelector("img")).toHaveAttribute(
      "src",
      INFRAHUB_OLD_LOGO,
    );
  });

  it("shows the latest version's description in the group header, with the full text as its title", async () => {
    useListDriversQueryMock.mockReturnValue(ok(data(DRIVERS)));
    await renderPage();
    const description = within(driverGroup("infrahub")).getByTestId(
      "driver-description",
    );
    expect(description).toHaveTextContent(INFRAHUB_NEW_DESCRIPTION);
    expect(description).toHaveAttribute("title", INFRAHUB_NEW_DESCRIPTION);
    expect(description).toHaveClass("truncate");
    expect(
      screen.queryByText(INFRAHUB_OLD_DESCRIPTION),
    ).not.toBeInTheDocument();

    // filtering down to the older version keeps the latest version's description
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Filter drivers"), "2.0.3");
    await waitFor(() => {
      expect(screen.queryByText("2.1.0")).not.toBeInTheDocument();
    });
    expect(
      within(driverGroup("infrahub")).getByTestId("driver-description"),
    ).toHaveTextContent(INFRAHUB_NEW_DESCRIPTION);
  });

  it("omits the description when the latest version has none", async () => {
    useListDriversQueryMock.mockReturnValue(
      ok(
        data([
          ...DRIVERS,
          {
            id: "id-netbox",
            name: "netbox",
            versions: [
              mkVersion(
                "n1",
                "4.0.0",
                "2026-01-01T00:00:00Z",
                null,
                "Old NetBox description",
              ),
              mkVersion("n2", "4.1.0", "2026-03-01T00:00:00Z"),
            ],
          } as Driver,
        ]),
      ),
    );
    await renderPage();
    expect(
      within(driverGroup("grafana")).queryByTestId("driver-description"),
    ).not.toBeInTheDocument();
    // an older version's description does not stand in for the latest one
    expect(
      within(driverGroup("netbox")).queryByTestId("driver-description"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Old NetBox description"),
    ).not.toBeInTheDocument();
  });

  it("renders no description in the flat view", async () => {
    useListDriversQueryMock.mockReturnValue(ok(data(DRIVERS)));
    await renderPage();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Flat list" }));
    await waitFor(() => {
      expect(
        document.querySelector('[data-testid="driver-group"]'),
      ).not.toBeInTheDocument();
    });
    expect(screen.queryAllByTestId("driver-description")).toHaveLength(0);
    expect(
      screen.queryByText(INFRAHUB_NEW_DESCRIPTION),
    ).not.toBeInTheDocument();
  });

  it("hides the Load driver action for a read-only user", async () => {
    useListDriversQueryMock.mockReturnValue(ok(data(DRIVERS)));
    await renderPage("READ_ONLY");
    expect(
      screen.queryByRole("button", { name: /load driver/i }),
    ).not.toBeInTheDocument();
  });
});
