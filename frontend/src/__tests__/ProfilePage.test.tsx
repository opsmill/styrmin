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

// Mock the `@/router` module BEFORE importing anything that touches it so the
// real Router instance (with the full route tree) is not pulled into the test.
const { navigateMock, updateMock, routerOptions } = vi.hoisted(() => ({
  navigateMock: vi.fn(() => Promise.resolve()),
  updateMock: vi.fn(),
  routerOptions: { context: {} as Record<string, unknown> },
}));

vi.mock("@/router", () => ({
  router: {
    navigate: navigateMock,
    update: updateMock,
    options: routerOptions,
  },
}));

import { AuthProvider } from "@/auth/AuthProvider";
import ProfilePage from "@/pages/profile/ProfilePage";

const AUTH_USER = {
  id: "u-self",
  username: "alice",
  displayName: "Alice",
  role: "READ_WRITE" as const,
  effectiveRole: "READ_WRITE" as const,
  active: true,
};

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

interface FetchCall {
  op: string;
  body: FetchBody;
}

interface InstallFetchResult {
  fetchMock: Mock;
  calls: FetchCall[];
}

/**
 * Wires the global `fetch` to dispatch by parsed GraphQL operation name.
 * Mirrors the helper used in LoginPage / UsersListPage tests.
 */
function installFetch(
  routes: Partial<Record<string, (body: FetchBody) => Response>>,
): InstallFetchResult {
  const calls: FetchCall[] = [];
  const fetchMock = vi.fn(async (_url: unknown, init?: RequestInit) => {
    const body: FetchBody = init?.body
      ? (JSON.parse(init.body as string) as FetchBody)
      : {};
    const query = body.query ?? "";
    for (const opName of Object.keys(routes)) {
      if (query.includes(opName)) {
        calls.push({ op: opName, body });
        return routes[opName]!(body);
      }
    }
    return jsonResponse(
      { errors: [{ message: `no mock for ${query}` }] },
      500,
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

/**
 * ProfilePage uses `<PageLayout>`, which itself renders TanStack Router
 * `<Link>` elements for the breadcrumb trail. Those `<Link>` components
 * require an active Router instance — a bare `render()` of ProfilePage will
 * throw "Cannot read properties of null (reading 'isServer')" inside
 * `useLinkProps`. We construct a minimal memory router that mounts the
 * AuthProvider + ProfilePage at `/profile`.
 */
function makeTestRouter() {
  const rootRoute = createRootRoute({
    component: () => (
      <AuthProvider>
        <ProfilePage />
      </AuthProvider>
    ),
  });
  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/",
    component: () => null,
  });
  const profileRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/profile",
    component: () => null,
  });
  return createRouter({
    routeTree: rootRoute.addChildren([indexRoute, profileRoute]),
    history: createMemoryHistory({ initialEntries: ["/profile"] }),
  });
}

async function renderProfile(queryClient: QueryClient): Promise<void> {
  const router = makeTestRouter();
  await router.load();
  await act(async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
  });
}

async function waitForReady(): Promise<void> {
  // ProfilePage renders the display-name input once AuthProvider exits its
  // loading state and currentUser is populated.
  await waitFor(() => {
    expect(screen.getByTestId("profile-display-name")).toBeInTheDocument();
  });
}

describe("ProfilePage", () => {
  beforeEach(() => {
    navigateMock.mockClear();
    updateMock.mockClear();
    routerOptions.context = {};
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("(a) display-name save calls updateUser with the new value", async () => {
    let updatedDisplayName: string | null = null;
    const { calls } = installFetch({
      CurrentUser: () =>
        jsonResponse({ data: { currentUser: AUTH_USER } }),
      UpdateUser: (body) => {
        const variables = body.variables as {
          id: string;
          input: { displayName: string | null };
        };
        updatedDisplayName = variables.input.displayName;
        return jsonResponse({
          data: {
            updateUser: {
              ...AUTH_USER,
              displayName: variables.input.displayName ?? AUTH_USER.displayName,
              groups: [],
              createdOn: "2025-01-01T00:00:00Z",
              updatedOn: "2025-01-02T00:00:00Z",
            },
          },
        });
      },
    });

    const qc = makeQueryClient();
    await renderProfile(qc);
    await waitForReady();

    const user = userEvent.setup();
    const input = screen.getByTestId("profile-display-name");
    await user.clear(input);
    await user.type(input, "Alice Updated");

    await user.click(screen.getByTestId("profile-display-name-save"));

    await waitFor(() => {
      const updateCalls = calls.filter((c) => c.op === "UpdateUser");
      expect(updateCalls.length).toBeGreaterThan(0);
    });

    expect(updatedDisplayName).toBe("Alice Updated");

    // Latest call should target the current user's id with the new display name.
    const latest = calls.filter((c) => c.op === "UpdateUser").pop()!;
    expect(latest.body.variables).toMatchObject({
      id: AUTH_USER.id,
      input: { displayName: "Alice Updated" },
    });

    await waitFor(() => {
      expect(
        screen.getByTestId("profile-display-name-success"),
      ).toBeInTheDocument();
    });
  });

  it("(b) password change happy path clears the form and shows success", async () => {
    let receivedPasswords: { currentPassword: string; newPassword: string } | null =
      null;
    installFetch({
      CurrentUser: () =>
        jsonResponse({ data: { currentUser: AUTH_USER } }),
      ChangePassword: (body) => {
        receivedPasswords = body.variables as {
          currentPassword: string;
          newPassword: string;
        };
        return jsonResponse({ data: { changePassword: true } });
      },
    });

    const qc = makeQueryClient();
    await renderProfile(qc);
    await waitForReady();

    const user = userEvent.setup();
    await user.type(
      screen.getByTestId("profile-current-password"),
      "old-pass",
    );
    await user.type(screen.getByTestId("profile-new-password"), "new-pass-1");
    await user.type(
      screen.getByTestId("profile-new-password-confirm"),
      "new-pass-1",
    );
    await user.click(screen.getByTestId("profile-change-password-save"));

    await waitFor(() => {
      expect(receivedPasswords).toEqual({
        currentPassword: "old-pass",
        newPassword: "new-pass-1",
      });
    });

    await waitFor(() => {
      expect(
        screen.getByTestId("profile-change-password-success"),
      ).toBeInTheDocument();
    });

    // Form fields are cleared on success.
    expect(
      (screen.getByTestId("profile-current-password") as HTMLInputElement).value,
    ).toBe("");
    expect(
      (screen.getByTestId("profile-new-password") as HTMLInputElement).value,
    ).toBe("");
    expect(
      (screen.getByTestId(
        "profile-new-password-confirm",
      ) as HTMLInputElement).value,
    ).toBe("");
  });

  it("(c) wrong current password renders inline error on the current-password field", async () => {
    installFetch({
      CurrentUser: () =>
        jsonResponse({ data: { currentUser: AUTH_USER } }),
      ChangePassword: () =>
        jsonResponse({
          errors: [
            {
              message: "Invalid credentials.",
              extensions: { code: "INVALID_CREDENTIALS" },
            },
          ],
        }),
    });

    const qc = makeQueryClient();
    await renderProfile(qc);
    await waitForReady();

    const user = userEvent.setup();
    await user.type(
      screen.getByTestId("profile-current-password"),
      "wrong-pass",
    );
    await user.type(screen.getByTestId("profile-new-password"), "new-pass-1");
    await user.type(
      screen.getByTestId("profile-new-password-confirm"),
      "new-pass-1",
    );
    await user.click(screen.getByTestId("profile-change-password-save"));

    await waitFor(() => {
      expect(
        screen.getByTestId("profile-current-password-error"),
      ).toBeInTheDocument();
    });

    // The top-level password-change error alert is NOT rendered (the inline
    // field-level message replaces it for this specific code).
    expect(
      screen.queryByTestId("profile-change-password-error"),
    ).not.toBeInTheDocument();
    // And no success message.
    expect(
      screen.queryByTestId("profile-change-password-success"),
    ).not.toBeInTheDocument();
  });

  it("(d) password-mismatch on confirm shows inline error and does NOT submit", async () => {
    const { calls } = installFetch({
      CurrentUser: () =>
        jsonResponse({ data: { currentUser: AUTH_USER } }),
      ChangePassword: () => jsonResponse({ data: { changePassword: true } }),
    });

    const qc = makeQueryClient();
    await renderProfile(qc);
    await waitForReady();

    const user = userEvent.setup();
    await user.type(
      screen.getByTestId("profile-current-password"),
      "old-pass",
    );
    await user.type(screen.getByTestId("profile-new-password"), "new-pass-1");
    await user.type(
      screen.getByTestId("profile-new-password-confirm"),
      "different-pass",
    );
    await user.click(screen.getByTestId("profile-change-password-save"));

    await waitFor(() => {
      expect(
        screen.getByTestId("profile-new-password-confirm-error"),
      ).toBeInTheDocument();
    });

    // Crucially, the mismatch check must short-circuit before any network call.
    const changePasswordCalls = calls.filter((c) => c.op === "ChangePassword");
    expect(changePasswordCalls).toHaveLength(0);

    // And no success message was rendered.
    expect(
      screen.queryByTestId("profile-change-password-success"),
    ).not.toBeInTheDocument();
  });
});
