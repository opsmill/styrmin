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

import UsersListPage from "@/pages/users/UsersListPage";

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

function makeUser(
  i: number,
  overrides: Partial<{
    role: "READ_ONLY" | "READ_WRITE" | "ADMIN";
    active: boolean;
  }> = {},
) {
  return {
    id: `u-${i}`,
    username: `user${i}`,
    displayName: `User ${i}`,
    role: overrides.role ?? "READ_ONLY",
    effectiveRole: overrides.role ?? "READ_ONLY",
    active: overrides.active ?? true,
    groups: [],
    createdOn: "2025-01-01T00:00:00Z",
    updatedOn: null,
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

function makeTestRouter() {
  const rootRoute = createRootRoute();
  const usersRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/users",
    component: () => <UsersListPage />,
  });
  const userDetailRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/users/$id",
    component: () => <div>user detail</div>,
  });
  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/",
    component: () => <div>home</div>,
  });

  return createRouter({
    routeTree: rootRoute.addChildren([indexRoute, usersRoute, userDetailRoute]),
    history: createMemoryHistory({ initialEntries: ["/users"] }),
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

async function renderUsersList(): Promise<void> {
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

describe("UsersListPage", () => {
  beforeEach(() => {
    // jsdom does not implement window.confirm — stub before any test runs.
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders one table row per user returned by the query", async () => {
    const users = [
      makeUser(1, { role: "ADMIN" }),
      makeUser(2, { role: "READ_WRITE" }),
      makeUser(3, { role: "READ_ONLY", active: false }),
    ];
    installFetch(() => jsonResponse({ data: { users } }));

    await renderUsersList();

    await waitFor(() => {
      expect(screen.getAllByTestId("users-row")).toHaveLength(3);
    });

    const rows = screen.getAllByTestId("users-row");
    expect(rows[0]).toHaveAttribute("data-username", "user1");
    expect(rows[1]).toHaveAttribute("data-username", "user2");
    expect(rows[2]).toHaveAttribute("data-username", "user3");
  });

  it("updates the query variables when the role filter changes", async () => {
    const { calls } = installFetch((body) => {
      const variables = (body.variables ?? {}) as { role?: string | null };
      const role = variables.role ?? null;
      const filteredUsers =
        role === "ADMIN"
          ? [makeUser(1, { role: "ADMIN" })]
          : [
              makeUser(1, { role: "ADMIN" }),
              makeUser(2, { role: "READ_WRITE" }),
            ];
      return jsonResponse({ data: { users: filteredUsers } });
    });

    await renderUsersList();

    await waitFor(() => {
      expect(screen.getAllByTestId("users-row").length).toBeGreaterThan(0);
    });

    const initialCallCount = calls.length;

    const user = userEvent.setup();
    await user.click(screen.getByTestId("users-filter-role-trigger"));
    // Options are rendered with the humanised role label (see roleLabel).
    const adminOption = await screen.findByRole("option", { name: "Admin" });
    await user.click(adminOption);

    await waitFor(() => {
      expect(calls.length).toBeGreaterThan(initialCallCount);
    });

    // The latest call's variables should carry role=ADMIN.
    const latest = calls[calls.length - 1]!;
    expect(latest.variables).toMatchObject({ role: "ADMIN" });

    await waitFor(() => {
      expect(screen.getAllByTestId("users-row")).toHaveLength(1);
    });
  });

  it("paginates with 25 rows per page over 30 users", async () => {
    const users = Array.from({ length: 30 }, (_v, i) => makeUser(i + 1));
    installFetch(() => jsonResponse({ data: { users } }));

    await renderUsersList();

    await waitFor(() => {
      expect(screen.getAllByTestId("users-row")).toHaveLength(25);
    });

    expect(screen.getByTestId("users-pagination-page")).toHaveTextContent(
      "Page 1 / 2",
    );

    const user = userEvent.setup();
    await user.click(screen.getByTestId("users-pagination-next"));

    await waitFor(() => {
      // Second page has the remaining 5 users.
      expect(screen.getAllByTestId("users-row")).toHaveLength(5);
    });
    expect(screen.getByTestId("users-pagination-page")).toHaveTextContent(
      "Page 2 / 2",
    );
  });
});
