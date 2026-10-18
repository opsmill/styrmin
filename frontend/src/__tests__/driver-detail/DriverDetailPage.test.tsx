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
 *   (f) the header logo follows the selected version, with a fallback,
 *   (g) the description and the Overview links follow the selected version,
 *       render as plain text, and are absent when not set,
 *   (h) a long description is cut to three lines with a "Show more" button.
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
import {
  render,
  screen,
  waitFor,
  act,
  within,
  fireEvent,
} from "@testing-library/react";
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
    driverDirectory: null as string | null,
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

  it("searches the version picker down to a single match", async () => {
    // Long histories are the reason the picker is searchable at all: scrolling
    // is not a way to find one version among many.
    useGetDriverQueryMock.mockReturnValue(
      makeQueryResult(
        makeDriver([
          makeVersion({
            id: "v3",
            version: "3.2.1",
            createdOn: "2026-03-01T00:00:00Z",
          }),
          makeVersion({
            id: "v2",
            version: "3.0.7",
            createdOn: "2026-02-01T00:00:00Z",
          }),
          makeVersion({
            id: "v1",
            version: "2.9.9",
            createdOn: "2026-01-01T00:00:00Z",
          }),
        ]),
      ),
    );
    await renderPage();
    const user = userEvent.setup();

    expect(
      await screen.findByText("3 driver versions loaded"),
    ).toBeInTheDocument();

    await user.click(screen.getByLabelText("Switch version"));
    await user.type(await screen.findByLabelText("Search versions"), "3.0");

    await waitFor(() => {
      expect(screen.queryByText("2.9.9")).not.toBeInTheDocument();
    });
    expect(screen.getByText("3.0.7")).toBeInTheDocument();
    expect(
      screen.getByText("Searching all 3 loaded versions"),
    ).toBeInTheDocument();
  });

  it("shows the driver directory of each version in the picker and searches on it", async () => {
    // Two drivers of one name, loaded from two driver directories at one commit.
    useGetDriverQueryMock.mockReturnValue(
      makeQueryResult(
        makeDriver([
          makeVersion({
            id: "vb",
            version: "1.0.0",
            createdOn: "2026-03-02T00:00:00Z",
            sourcePath: "drivers/b",
            driverDirectory: "drivers/b",
          }),
          makeVersion({
            id: "va",
            version: "1.0.0",
            createdOn: "2026-03-01T00:00:00Z",
            sourcePath: "drivers/a",
            driverDirectory: "drivers/a",
          }),
        ]),
      ),
    );
    await renderPage();
    const user = userEvent.setup();

    const trigger = screen.getByLabelText("Switch version");
    expect(trigger).toHaveTextContent("1.0.0@abcdef1 · drivers/b");

    await user.click(trigger);
    await user.type(
      await screen.findByLabelText("Search versions"),
      "drivers/a",
    );

    await waitFor(() => {
      expect(
        screen.queryByRole("option", { name: /drivers\/b/ }),
      ).not.toBeInTheDocument();
    });
    expect(
      screen.getByRole("option", { name: /1\.0\.0@abcdef1 · drivers\/a/ }),
    ).toBeInTheDocument();
  });

  it("names each copy button of the Overview tab by the value it copies", async () => {
    useGetDriverQueryMock.mockReturnValue(
      makeQueryResult(
        makeDriver([
          makeVersion({
            id: "v1",
            version: "1.0.0",
            createdOn: "2026-03-01T00:00:00Z",
            sourcePath: "drivers/a",
            driverDirectory: "drivers/a",
          }),
        ]),
      ),
    );

    await renderPage();

    const names = within(screen.getByTestId("driver-overview"))
      .getAllByRole("button")
      .map((button) => button.getAttribute("aria-label"));
    expect(names).toEqual([
      "Copy source",
      "Copy driver directory",
      "Copy full commit SHA",
      "Copy chart repository",
    ]);
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

    // The header logo is always in view, so it loads without waiting.
    expect(headerLogo().querySelector("img")).toHaveAttribute(
      "loading",
      "eager",
    );
    expect(headerLogo()).toHaveAttribute("data-logo-state", "loading");
    fireEvent.load(headerLogo().querySelector("img")!);
    expect(headerLogo()).toHaveAttribute("data-logo-state", "image");
    expect(headerLogo().querySelector("img")).toHaveAttribute("src", NEW_LOGO);

    await user.click(screen.getByLabelText("Switch version"));
    await user.click(await screen.findByRole("option", { name: /1\.0\.0/ }));

    await waitFor(() => {
      expect(
        screen.getByTestId("driver-detail").getAttribute("data-version-id"),
      ).toBe("old");
    });
    expect(headerLogo()).toHaveAttribute("data-logo-state", "loading");
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
  it("shows the selected version's full description as plain text", async () => {
    const description =
      "Deploys <b>Example</b> & its worker.\nSecond line <script>alert(1)</script>";
    useGetDriverQueryMock.mockReturnValue(
      makeQueryResult(
        makeDriver([
          makeVersion({
            id: "v1",
            version: "1.0.0",
            createdOn: "2026-03-01T00:00:00Z",
            description,
          }),
        ]),
      ),
    );

    await renderPage();

    const el = screen.getByTestId("driver-description");
    expect(el.textContent).toBe(description);
    expect(el).toHaveClass("whitespace-pre-line");
    expect(el.querySelector("b")).toBeNull();
    expect(el.querySelector("script")).toBeNull();
  });

  it("lists the selected version's links in the Overview tab, in order, opening in a new tab", async () => {
    const links = [
      { label: "Homepage", url: "https://example.com/" },
      { label: "Documentation", url: "https://docs.example.com/guide" },
      { label: "Github <source>", url: "https://github.com/example/repo" },
    ];
    useGetDriverQueryMock.mockReturnValue(
      makeQueryResult(
        makeDriver([
          makeVersion({
            id: "v1",
            version: "1.0.0",
            createdOn: "2026-03-01T00:00:00Z",
            links,
          }),
        ]),
      ),
    );

    const user = userEvent.setup();
    await renderPage();

    const overview = screen.getByTestId("driver-overview");
    const anchors = within(
      within(overview).getByTestId("driver-links"),
    ).getAllByRole("link");
    expect(anchors.map((a) => a.textContent)).toEqual(
      links.map((l) => `${l.label} (opens in a new tab)`),
    );
    anchors.forEach((a, i) => {
      expect(a).toHaveAttribute("href", links[i].url);
      expect(a).toHaveAttribute("target", "_blank");
      expect(a).toHaveAttribute("rel", "noopener noreferrer");
      // screen readers announce the new tab; the icon is decorative
      expect(a).toHaveAccessibleName(`${links[i].label} (opens in a new tab)`);
    });
    expect(
      within(overview)
        .getAllByTestId("driver-link-host")
        .map((el) => el.textContent),
    ).toEqual(["example.com", "docs.example.com", "github.com"]);

    // the links belong to the Overview tab only
    await user.click(screen.getByRole("button", { name: /parameters/i }));
    await waitFor(() => {
      expect(screen.queryByTestId("driver-links")).not.toBeInTheDocument();
    });
  });

  it("shows the description and links of the ?version version", async () => {
    useGetDriverQueryMock.mockReturnValue(makeQueryResult(twoVersions()));

    await renderPage("/drivers/driver-1?version=old");

    expect(screen.getByTestId("driver-description")).toHaveTextContent(
      "Old description",
    );
    expect(
      within(screen.getByTestId("driver-links")).getByRole("link", {
        name: /^Docs/,
      }),
    ).toHaveAttribute("href", "https://example.com/docs/v1");
  });

  it("cuts a long description to three lines with a Show more button", async () => {
    const description = "Line one.\nLine two.\nLine three.\nLine four.";
    useGetDriverQueryMock.mockReturnValue(
      makeQueryResult(
        makeDriver([
          makeVersion({
            id: "v1",
            version: "1.0.0",
            createdOn: "2026-03-01T00:00:00Z",
            description,
          }),
        ]),
      ),
    );
    // jsdom has no layout: report text taller than its clamped box.
    const scrollHeight = vi
      .spyOn(HTMLElement.prototype, "scrollHeight", "get")
      .mockReturnValue(80);
    const clientHeight = vi
      .spyOn(HTMLElement.prototype, "clientHeight", "get")
      .mockReturnValue(60);
    try {
      const user = userEvent.setup();
      await renderPage();

      const el = screen.getByTestId("driver-description");
      expect(el).toHaveClass("line-clamp-3");
      const toggle = screen.getByRole("button", { name: "Show more" });
      expect(toggle).toHaveAttribute("aria-expanded", "false");
      expect(toggle).toHaveAttribute("aria-controls", el.id);

      await user.click(toggle);
      expect(el).not.toHaveClass("line-clamp-3");
      expect(screen.getByRole("button", { name: "Show less" })).toHaveAttribute(
        "aria-expanded",
        "true",
      );
    } finally {
      scrollHeight.mockRestore();
      clientHeight.mockRestore();
    }
  });

  it("shows no Show more button when the description fits", async () => {
    useGetDriverQueryMock.mockReturnValue(
      makeQueryResult(
        makeDriver([
          makeVersion({
            id: "v1",
            version: "1.0.0",
            createdOn: "2026-03-01T00:00:00Z",
            description: "Short.",
          }),
        ]),
      ),
    );

    await renderPage();

    expect(screen.getByTestId("driver-description")).toHaveTextContent(
      "Short.",
    );
    expect(
      screen.queryByRole("button", { name: "Show more" }),
    ).not.toBeInTheDocument();
  });

  it("shows the driver directory row in the Overview tab for a git version loaded from one", async () => {
    useGetDriverQueryMock.mockReturnValue(
      makeQueryResult(
        makeDriver([
          makeVersion({
            id: "v1",
            version: "1.0.0",
            createdOn: "2026-03-01T00:00:00Z",
            sourcePath: "drivers/a",
            driverDirectory: "drivers/a",
          }),
        ]),
      ),
    );

    await renderPage();

    const row = screen.getByTestId("driver-overview-driver-directory");
    expect(within(row).getByText("Driver directory")).toBeInTheDocument();
    expect(within(row).getByText("drivers/a")).toBeInTheDocument();
    expect(
      within(row).getByRole("button", { name: "Copy driver directory" }),
    ).toBeInTheDocument();
    // The row follows the Source row.
    expect(row.previousElementSibling).toHaveTextContent("Source");
  });

  it.each([
    [
      "a git version without a driver directory",
      { sourceType: "git", sourcePath: null },
    ],
    [
      "a local version",
      {
        sourceType: "local",
        sourceRepository: null,
        sourceBranch: null,
        sourcePath: "/opt/drivers/a",
        sourceCommitSha: null,
        contentHash: "0123456789abcdef",
      },
    ],
  ])("shows no driver directory row for %s", async (_case, source) => {
    useGetDriverQueryMock.mockReturnValue(
      makeQueryResult(
        makeDriver([
          makeVersion({
            id: "v1",
            version: "1.0.0",
            createdOn: "2026-03-01T00:00:00Z",
            ...(source as Partial<VersionShape>),
          }),
        ]),
      ),
    );

    await renderPage();

    expect(screen.getByTestId("driver-overview")).toBeInTheDocument();
    expect(
      screen.queryByTestId("driver-overview-driver-directory"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Driver directory")).not.toBeInTheDocument();
  });

  it("renders no description area and no links section when the version has neither", async () => {
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

    expect(screen.getByTestId("driver-overview")).toBeInTheDocument();
    expect(screen.queryByTestId("driver-description")).not.toBeInTheDocument();
    expect(screen.queryByTestId("driver-links")).not.toBeInTheDocument();
    expect(screen.queryByText("Links")).not.toBeInTheDocument();
  });
});
