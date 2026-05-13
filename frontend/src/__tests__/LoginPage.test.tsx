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

// Mock the router module BEFORE importing anything that touches it.
const {
  navigateMock,
  updateMock,
  routerOptions,
  useNavigateMock,
  searchValue,
} = vi.hoisted(() => ({
  navigateMock: vi.fn(() => Promise.resolve()),
  updateMock: vi.fn(),
  routerOptions: { context: {} as Record<string, unknown> },
  useNavigateMock: vi.fn(() => Promise.resolve()),
  // Mutable container so individual tests can prime `?next=` before render.
  searchValue: { current: {} as Record<string, unknown> },
}));

vi.mock("@/router", () => ({
  router: {
    navigate: navigateMock,
    update: updateMock,
    options: routerOptions,
  },
}));

// useNavigate() / useSearch() inside LoginPage would otherwise require a
// real <RouterProvider>; stub them so we can assert navigation and inject
// `next` into the search.
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => useNavigateMock,
  useSearch: () => searchValue.current,
}));

// Provide a no-op router context for the route hooks that LoginPage's button
// component does NOT use; we don't render the menu here so no extra mocks
// are needed.

import { AuthProvider } from "@/auth/AuthProvider";
import LoginPage from "@/pages/login/LoginPage";

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

function renderLogin(queryClient: QueryClient) {
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <LoginPage />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

const AUTH_USER = {
  id: "u1",
  username: "alice",
  displayName: "Alice",
  role: "ADMIN" as const,
  effectiveRole: "ADMIN" as const,
  active: true,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * Wires the global `fetch` to respond differently depending on which GraphQL
 * operation is being executed (parsed out of the request body). This lets a
 * single mock service the `CurrentUser` query (from <AuthProvider>) AND the
 * `Login` mutation.
 */
function installFetchRouter(routes: Record<string, () => Response>): Mock {
  const fetchMock = vi.fn(async (_url, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(init.body as string) : {};
    const query: string = body.query ?? "";
    for (const [opName, builder] of Object.entries(routes)) {
      if (query.includes(opName)) {
        return builder();
      }
    }
    return jsonResponse({ errors: [{ message: `no mock for ${query}` }] }, 500);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("LoginPage", () => {
  beforeEach(() => {
    navigateMock.mockClear();
    updateMock.mockClear();
    useNavigateMock.mockClear();
    routerOptions.context = {};
    searchValue.current = {};
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("happy path: submitting the form triggers the login mutation and refetches currentUser", async () => {
    // First call to CurrentUser (from <AuthProvider> mount) returns null.
    // After Login succeeds, LoginPage refetches CurrentUser; the second call
    // returns the authenticated user.
    let currentUserCalls = 0;
    const fetchMock = installFetchRouter({
      Login: () =>
        jsonResponse({
          data: {
            login: {
              token: "tok-1",
              user: AUTH_USER,
            },
          },
        }),
      CurrentUser: () => {
        currentUserCalls += 1;
        return jsonResponse({
          data: {
            currentUser: currentUserCalls === 1 ? null : AUTH_USER,
          },
        });
      },
    });

    const qc = makeQueryClient();
    renderLogin(qc);

    // Wait for AuthProvider's loading state to clear.
    await waitFor(() => {
      expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Username"), "alice");
    await user.type(screen.getByLabelText("Password"), "secret");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      const loginCalls = fetchMock.mock.calls.filter(([, init]) => {
        const parsed = init?.body
          ? JSON.parse((init as RequestInit).body as string)
          : {};
        return (parsed.query ?? "").includes("Login");
      });
      expect(loginCalls.length).toBeGreaterThan(0);
    });

    // CurrentUser was refetched (>= 2 calls now).
    await waitFor(() => {
      expect(currentUserCalls).toBeGreaterThanOrEqual(2);
    });

    // User is navigated to '/' after refresh — the /login beforeLoad guard
    // only fires on navigation, so refresh() alone would leave the user
    // stuck on the form.
    await waitFor(() => {
      expect(useNavigateMock).toHaveBeenCalledWith({ to: "/" });
    });

    // No error message rendered.
    expect(screen.queryByTestId("login-error")).not.toBeInTheDocument();
  });

  it("error path: failed login renders the literal generic message", async () => {
    installFetchRouter({
      Login: () =>
        jsonResponse({
          errors: [
            {
              message: "wrong creds",
              extensions: { code: "UNAUTHENTICATED" },
            },
          ],
        }),
      CurrentUser: () => jsonResponse({ data: { currentUser: null } }),
    });

    const qc = makeQueryClient();
    renderLogin(qc);

    await waitFor(() => {
      expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Username"), "alice");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(
        screen.getByText("Invalid username or password."),
      ).toBeInTheDocument();
    });
  });

  it("redirects to a safe ?next path after successful login", async () => {
    searchValue.current = { next: "/users/abc-123" };
    let currentUserCalls = 0;
    installFetchRouter({
      Login: () =>
        jsonResponse({
          data: { login: { token: "tok-1", user: AUTH_USER } },
        }),
      CurrentUser: () => {
        currentUserCalls += 1;
        return jsonResponse({
          data: {
            currentUser: currentUserCalls === 1 ? null : AUTH_USER,
          },
        });
      },
    });

    const qc = makeQueryClient();
    renderLogin(qc);

    await waitFor(() => {
      expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Username"), "alice");
    await user.type(screen.getByLabelText("Password"), "secret");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(useNavigateMock).toHaveBeenCalledWith({ to: "/users/abc-123" });
    });
  });

  it("falls back to '/' when ?next is an open-redirect attempt", async () => {
    searchValue.current = { next: "//evil.com/phish" };
    let currentUserCalls = 0;
    installFetchRouter({
      Login: () =>
        jsonResponse({
          data: { login: { token: "tok-1", user: AUTH_USER } },
        }),
      CurrentUser: () => {
        currentUserCalls += 1;
        return jsonResponse({
          data: {
            currentUser: currentUserCalls === 1 ? null : AUTH_USER,
          },
        });
      },
    });

    const qc = makeQueryClient();
    renderLogin(qc);

    await waitFor(() => {
      expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Username"), "alice");
    await user.type(screen.getByLabelText("Password"), "secret");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(useNavigateMock).toHaveBeenCalledWith({ to: "/" });
    });
  });

  it("disables the submit button while the request is in flight", async () => {
    // Hold the Login response so we can observe the in-flight UI state.
    let resolveLogin!: (response: Response) => void;
    const loginPromise = new Promise<Response>((resolve) => {
      resolveLogin = resolve;
    });

    const fetchMock = vi.fn(async (_url, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(init.body as string) : {};
      if ((body.query ?? "").includes("Login")) {
        return loginPromise;
      }
      return jsonResponse({ data: { currentUser: null } });
    });
    vi.stubGlobal("fetch", fetchMock);

    const qc = makeQueryClient();
    renderLogin(qc);

    await waitFor(() => {
      expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Username"), "alice");
    await user.type(screen.getByLabelText("Password"), "secret");
    const submit = screen.getByRole("button", { name: /sign in/i });
    await user.click(submit);

    await waitFor(() => {
      expect(submit).toBeDisabled();
    });

    // Release the request so the test exits cleanly.
    await act(async () => {
      resolveLogin(
        jsonResponse({
          data: {
            login: { token: "tok", user: AUTH_USER },
          },
        }),
      );
    });
  });
});
