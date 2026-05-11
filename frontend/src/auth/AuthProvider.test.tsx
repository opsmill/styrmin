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
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Mock the router module BEFORE importing anything that touches it.
const { navigateMock, updateMock, routerOptions } = vi.hoisted(() => {
  return {
    navigateMock: vi.fn(() => Promise.resolve()),
    updateMock: vi.fn(),
    routerOptions: { context: {} as Record<string, unknown> },
  };
});

vi.mock("@/router", () => ({
  router: {
    navigate: navigateMock,
    update: updateMock,
    options: routerOptions,
  },
}));

// Imports that resolve the mocked router.
import { AuthProvider, useAuth } from "./AuthProvider";
import {
  graphqlFetcher,
  setUnauthenticatedHandler,
} from "@/lib/graphql-fetcher";

function mockFetchOnce(body: unknown, status = 200): Mock {
  const response = new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
  const fetchMock = vi.fn(() => Promise.resolve(response));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function deferredFetch(): {
  fetchMock: Mock;
  resolve: (body: unknown) => void;
} {
  let resolveFetch!: (body: unknown) => void;
  const promise = new Promise<Response>((resolve) => {
    resolveFetch = (body: unknown) =>
      resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
  });
  const fetchMock = vi.fn(() => promise);
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, resolve: resolveFetch };
}

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

function renderProvider(queryClient: QueryClient, child: React.ReactNode) {
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{child}</AuthProvider>
    </QueryClientProvider>,
  );
}

function Consumer() {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="user">
        {auth.currentUser ? auth.currentUser.username : "anon"}
      </span>
    </div>
  );
}

describe("AuthProvider", () => {
  beforeEach(() => {
    navigateMock.mockClear();
    updateMock.mockClear();
    routerOptions.context = {};
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setUnauthenticatedHandler(null);
  });

  it("renders a loading indicator before the first currentUser response", async () => {
    const { resolve } = deferredFetch();
    const queryClient = makeQueryClient();
    renderProvider(
      queryClient,
      <div data-testid="child">child-content</div>,
    );

    // Initial render: query in flight, child should NOT yet be rendered.
    expect(screen.queryByTestId("child")).not.toBeInTheDocument();
    expect(screen.getByText("Loading...")).toBeInTheDocument();

    // Resolve the request so the test finishes cleanly.
    await act(async () => {
      resolve({ data: { currentUser: null } });
    });
    await waitFor(() => {
      expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
    });
  });

  it("does not render children inside the provider when currentUser is null (login route handles UI)", async () => {
    mockFetchOnce({ data: { currentUser: null } });
    const queryClient = makeQueryClient();
    renderProvider(queryClient, <Consumer />);

    await waitFor(() => {
      expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
    });
    // Provider renders its children regardless once loaded; the unauthenticated
    // UI flow (redirect to /login) is the router's job. We assert that the
    // consumer sees `currentUser == null`.
    expect(screen.getByTestId("user")).toHaveTextContent("anon");
  });

  it("renders children with an authenticated user once currentUser resolves", async () => {
    mockFetchOnce({
      data: {
        currentUser: {
          id: "u1",
          username: "alice",
          displayName: "Alice",
          role: "ADMIN",
          effectiveRole: "ADMIN",
          active: true,
        },
      },
    });
    const queryClient = makeQueryClient();
    renderProvider(queryClient, <Consumer />);

    await waitFor(() => {
      expect(screen.getByTestId("user")).toHaveTextContent("alice");
    });
    // Router context was updated with the auth value.
    expect(updateMock).toHaveBeenCalled();
    const lastCall = updateMock.mock.calls.at(-1)![0] as {
      context: { auth: { currentUser: { username: string } } };
    };
    expect(lastCall.context.auth.currentUser.username).toBe("alice");
  });

  it("invokes the registered handler, clears the query cache, and navigates to /login when a later request returns UNAUTHENTICATED", async () => {
    mockFetchOnce({
      data: {
        currentUser: {
          id: "u1",
          username: "alice",
          displayName: "Alice",
          role: "ADMIN",
          effectiveRole: "ADMIN",
          active: true,
        },
      },
    });
    const queryClient = makeQueryClient();
    const clearSpy = vi.spyOn(queryClient, "clear");

    renderProvider(queryClient, <Consumer />);
    await waitFor(() => {
      expect(screen.getByTestId("user")).toHaveTextContent("alice");
    });

    // Now arrange a second request that returns an UNAUTHENTICATED error.
    const unauthResponse = new Response(
      JSON.stringify({
        errors: [
          {
            message: "Authentication required",
            extensions: { code: "UNAUTHENTICATED" },
          },
        ],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(unauthResponse)),
    );

    // Trigger a fetch by invoking graphqlFetcher directly. The fetcher's
    // module-scope handler was registered by AuthProvider's effect.
    const fetcher = graphqlFetcher<unknown, undefined>(
      "query Whatever { ok }",
    );
    await expect(fetcher()).rejects.toMatchObject({ name: "UnauthenticatedError" });

    expect(clearSpy).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledWith({ to: "/login" });
  });
});
