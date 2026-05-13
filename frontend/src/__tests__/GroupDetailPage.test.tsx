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

import GroupDetailPage from "@/pages/groups/GroupDetailPage";

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

const GROUP_ID = "g-1";

function makeGroup() {
  return { id: GROUP_ID, name: "engineering", role: "READ_WRITE" as const };
}

function makeUser(opts: {
  id: string;
  username: string;
  active: boolean;
  inGroup: boolean;
}) {
  return {
    id: opts.id,
    username: opts.username,
    displayName: `${opts.username} display`,
    role: "READ_ONLY" as const,
    effectiveRole: "READ_ONLY" as const,
    active: opts.active,
    groups: opts.inGroup
      ? [{ id: GROUP_ID, name: "engineering", role: "READ_WRITE" as const }]
      : [],
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

function defaultBuilder(
  users: ReturnType<typeof makeUser>[],
): (body: FetchBody) => Response {
  return (body) => {
    const q = body.query ?? "";
    if (q.includes("query ListGroups")) {
      return jsonResponse({ data: { groups: [makeGroup()] } });
    }
    if (q.includes("query ListUsers")) {
      return jsonResponse({ data: { users } });
    }
    if (q.includes("mutation UpdateGroup")) {
      return jsonResponse({
        data: {
          updateGroup: {
            id: GROUP_ID,
            name: "engineering",
            role: "READ_WRITE",
          },
        },
      });
    }
    return jsonResponse({ data: {} });
  };
}

function makeTestRouter() {
  const rootRoute = createRootRoute();
  const groupsRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/groups",
    component: () => <div>groups list</div>,
  });
  const groupDetailRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/groups/$id",
    component: () => <GroupDetailPage />,
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
    history: createMemoryHistory({ initialEntries: [`/groups/${GROUP_ID}`] }),
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

async function renderGroupDetail(): Promise<void> {
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

describe("GroupDetailPage — inactive member safety", () => {
  beforeEach(() => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows both the active member (in picker) and the inactive member (read-only section)", async () => {
    const users = [
      makeUser({
        id: "u-active",
        username: "alice",
        active: true,
        inGroup: true,
      }),
      makeUser({
        id: "u-inactive",
        username: "bob",
        active: false,
        inGroup: true,
      }),
      makeUser({
        id: "u-other",
        username: "carol",
        active: true,
        inGroup: false,
      }),
    ];
    installFetch(defaultBuilder(users));

    await renderGroupDetail();

    await waitFor(() => {
      expect(screen.getByTestId("group-edit-form")).toBeInTheDocument();
    });

    // Active member picker contains alice and carol, with alice pre-checked.
    const picker = screen.getByTestId("group-members-multiselect");
    expect(picker.querySelector('[data-user-id="u-active"]')).not.toBeNull();
    expect(picker.querySelector('[data-user-id="u-other"]')).not.toBeNull();
    expect(picker.querySelector('[data-user-id="u-inactive"]')).toBeNull();

    // Inactive section contains bob, who is listed read-only with a remove
    // toggle. We rely on the save round-trip test below to verify the
    // pre-checked state ends up in memberIds.
    const inactive = screen.getByTestId("group-inactive-members-list");
    expect(
      inactive.querySelector('[data-user-id="u-inactive"]'),
    ).not.toBeNull();
    expect(inactive.textContent).toContain("bob");
    expect(inactive.textContent).toContain("inactive");
  });

  it("toggling a new active member into the group preserves the inactive member in memberIds", async () => {
    const users = [
      makeUser({
        id: "u-active",
        username: "alice",
        active: true,
        inGroup: true,
      }),
      makeUser({
        id: "u-inactive",
        username: "bob",
        active: false,
        inGroup: true,
      }),
      makeUser({
        id: "u-other",
        username: "carol",
        active: true,
        inGroup: false,
      }),
    ];
    const { calls } = installFetch(defaultBuilder(users));

    await renderGroupDetail();

    await waitFor(() => {
      expect(screen.getByTestId("group-edit-form")).toBeInTheDocument();
    });

    // Wait for the inactive member to be present (proves seeding completed).
    await waitFor(() => {
      expect(
        screen.getByTestId("group-inactive-members-list"),
      ).toBeInTheDocument();
    });

    // Add carol (a new active member) — this makes membersChanged true so we
    // can inspect the memberIds payload. The inactive bob must survive.
    const user = userEvent.setup();
    const carolToggle = screen
      .getByTestId("group-members-multiselect")
      .querySelector('[data-user-id="u-other"] [role="checkbox"]')!;
    await user.click(carolToggle);

    await user.click(screen.getByTestId("group-edit-save"));

    await waitFor(() => {
      const updateCalls = calls.filter((c) =>
        (c.query ?? "").includes("mutation UpdateGroup"),
      );
      expect(updateCalls.length).toBeGreaterThan(0);
    });

    const updateCall = calls
      .filter((c) => (c.query ?? "").includes("mutation UpdateGroup"))
      .pop()!;
    const input = (
      updateCall.variables as { input: { memberIds: string[] | null } }
    ).input;
    expect(input.memberIds).not.toBeNull();
    expect(input.memberIds).toEqual(
      expect.arrayContaining(["u-active", "u-inactive", "u-other"]),
    );
  });

  it("unchecking the inactive member removes only that one from the saved memberIds", async () => {
    const users = [
      makeUser({
        id: "u-active",
        username: "alice",
        active: true,
        inGroup: true,
      }),
      makeUser({
        id: "u-inactive",
        username: "bob",
        active: false,
        inGroup: true,
      }),
    ];
    const { calls } = installFetch(defaultBuilder(users));

    await renderGroupDetail();

    await waitFor(() => {
      expect(
        screen.getByTestId("group-inactive-members-list"),
      ).toBeInTheDocument();
    });

    const user = userEvent.setup();
    const bobToggle = screen
      .getByTestId("group-inactive-members-list")
      .querySelector('[data-user-id="u-inactive"] [role="checkbox"]')!;
    await user.click(bobToggle); // uncheck bob

    await user.click(screen.getByTestId("group-edit-save"));

    await waitFor(() => {
      const updateCalls = calls.filter((c) =>
        (c.query ?? "").includes("mutation UpdateGroup"),
      );
      expect(updateCalls.length).toBeGreaterThan(0);
    });

    const updateCall = calls
      .filter((c) => (c.query ?? "").includes("mutation UpdateGroup"))
      .pop()!;
    const input = (
      updateCall.variables as { input: { memberIds: string[] | null } }
    ).input;
    expect(input.memberIds).not.toBeNull();
    expect(input.memberIds).toContain("u-active");
    expect(input.memberIds).not.toContain("u-inactive");
  });

  it("renders an inline error with retry when the users query fails", async () => {
    let usersCalls = 0;
    installFetch((body) => {
      const q = body.query ?? "";
      if (q.includes("query ListGroups")) {
        return jsonResponse({ data: { groups: [makeGroup()] } });
      }
      if (q.includes("query ListUsers")) {
        usersCalls += 1;
        if (usersCalls === 1) {
          return jsonResponse({ errors: [{ message: "boom" }] }, 500);
        }
        return jsonResponse({
          data: {
            users: [
              makeUser({
                id: "u-active",
                username: "alice",
                active: true,
                inGroup: true,
              }),
            ],
          },
        });
      }
      return jsonResponse({ data: {} });
    });

    await renderGroupDetail();

    // The page itself still renders (groups query succeeded); the members
    // section shows the inline error.
    await waitFor(() => {
      expect(screen.getByTestId("group-members-error")).toBeInTheDocument();
    });

    // Retry triggers a refetch — after which the picker appears.
    const user = userEvent.setup();
    const retryBtn = screen
      .getByTestId("group-members-error")
      .querySelector("button");
    expect(retryBtn).not.toBeNull();
    await user.click(retryBtn!);

    await waitFor(() => {
      expect(
        screen.getByTestId("group-members-multiselect"),
      ).toBeInTheDocument();
    });
  });
});
