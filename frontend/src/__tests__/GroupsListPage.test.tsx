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

import GroupsListPage from "@/pages/groups/GroupsListPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

interface FetchBody {
  query?: string;
  variables?: Record<string, unknown>;
}

function makeGroup(
  i: number,
  overrides: Partial<{ role: "READ_ONLY" | "READ_WRITE" | "ADMIN" }> = {},
) {
  return {
    id: `g-${i}`,
    name: `group${i}`,
    role: overrides.role ?? "READ_ONLY",
  };
}

interface InstallFetchResult {
  fetchMock: Mock;
  calls: FetchBody[];
}

function installFetch(
  builder: (body: FetchBody) => Response,
): InstallFetchResult {
  const calls: FetchBody[] = [];
  const fetchMock = vi.fn(async (_url: unknown, init?: RequestInit) => {
    const body: FetchBody = init?.body
      ? (JSON.parse(init.body as string) as FetchBody)
      : {};
    calls.push(body);
    return builder(body);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}

/**
 * Route the fetch mock based on operation name parsed from the GraphQL query
 * string. Returns appropriate fixtures for `ListGroups` and `ListUsers`; other
 * operations get an empty data shape.
 */
function routedFetchBuilder(
  groups: ReturnType<typeof makeGroup>[],
): (body: FetchBody) => Response {
  return (body) => {
    const q = body.query ?? "";
    if (q.includes("query ListGroups")) {
      const variables = (body.variables ?? {}) as { search?: string | null };
      const search = variables.search;
      const filtered =
        search != null && search !== ""
          ? groups.filter((g) =>
              g.name.toLowerCase().includes(search.toLowerCase()),
            )
          : groups;
      return jsonResponse({ data: { groups: filtered } });
    }
    if (q.includes("query ListUsers")) {
      return jsonResponse({ data: { users: [] } });
    }
    return jsonResponse({ data: {} });
  };
}

function makeTestRouter() {
  const rootRoute = createRootRoute();
  const groupsRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/groups",
    component: () => <GroupsListPage />,
  });
  const groupDetailRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/groups/$id",
    component: () => <div>group detail</div>,
  });
  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/",
    component: () => <div>home</div>,
  });

  return createRouter({
    routeTree: rootRoute.addChildren([
      indexRoute,
      groupsRoute,
      groupDetailRoute,
    ]),
    history: createMemoryHistory({ initialEntries: ["/groups"] }),
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

async function renderGroupsList(): Promise<void> {
  const router = makeTestRouter();
  await router.load();
  const qc = makeQueryClient();
  await act(async () => {
    render(
      <QueryClientProvider client={qc}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
  });
}

describe("GroupsListPage", () => {
  beforeEach(() => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders one table row per group returned by the query", async () => {
    const groups = [
      makeGroup(1, { role: "ADMIN" }),
      makeGroup(2, { role: "READ_WRITE" }),
      makeGroup(3, { role: "READ_ONLY" }),
    ];
    installFetch(routedFetchBuilder(groups));

    await renderGroupsList();

    await waitFor(() => {
      expect(screen.getAllByTestId("groups-row")).toHaveLength(3);
    });

    const rows = screen.getAllByTestId("groups-row");
    expect(rows[0]).toHaveAttribute("data-group-name", "group1");
    expect(rows[1]).toHaveAttribute("data-group-name", "group2");
    expect(rows[2]).toHaveAttribute("data-group-name", "group3");
  });

  it("updates the query variables when the search filter changes", async () => {
    const groups = [
      makeGroup(1, { role: "ADMIN" }),
      makeGroup(2, { role: "READ_WRITE" }),
    ];
    const { calls } = installFetch(routedFetchBuilder(groups));

    await renderGroupsList();

    await waitFor(() => {
      expect(screen.getAllByTestId("groups-row").length).toBeGreaterThan(0);
    });

    const initialListGroupsCalls = calls.filter((c) =>
      (c.query ?? "").includes("query ListGroups"),
    ).length;

    const user = userEvent.setup();
    await user.type(screen.getByTestId("groups-filter-search"), "group1");

    await waitFor(() => {
      const next = calls.filter((c) =>
        (c.query ?? "").includes("query ListGroups"),
      ).length;
      expect(next).toBeGreaterThan(initialListGroupsCalls);
    });

    const listGroupsCalls = calls.filter((c) =>
      (c.query ?? "").includes("query ListGroups"),
    );
    const latest = listGroupsCalls[listGroupsCalls.length - 1]!;
    expect(latest.variables).toMatchObject({ search: "group1" });

    await waitFor(() => {
      expect(screen.getAllByTestId("groups-row")).toHaveLength(1);
    });
  });

  it("paginates with 25 rows per page over 30 groups", async () => {
    const groups = Array.from({ length: 30 }, (_v, i) => makeGroup(i + 1));
    installFetch(routedFetchBuilder(groups));

    await renderGroupsList();

    await waitFor(() => {
      expect(screen.getAllByTestId("groups-row")).toHaveLength(25);
    });

    expect(screen.getByTestId("groups-pagination-page")).toHaveTextContent(
      "Page 1 / 2",
    );

    const user = userEvent.setup();
    await user.click(screen.getByTestId("groups-pagination-next"));

    await waitFor(() => {
      expect(screen.getAllByTestId("groups-row")).toHaveLength(5);
    });
    expect(screen.getByTestId("groups-pagination-page")).toHaveTextContent(
      "Page 2 / 2",
    );
  });
});
