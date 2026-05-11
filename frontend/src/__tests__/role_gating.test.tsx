/**
 * Role-gating integration test (011 / US5).
 *
 * Verifies that the hide-not-disable IfRole wrappers applied across the
 * app suppress write-mutation buttons for users below the required role
 * tier. The test mounts the AppShell plus a representative write-heavy
 * page (BackupStorageLocationListPage) under three synthetic auth
 * contexts:
 *
 *   - READ_ONLY  → no write buttons; no admin nav.
 *   - READ_WRITE → write buttons visible; admin nav still hidden.
 *   - ADMIN      → write buttons visible; admin nav (Users, Groups)
 *                  visible.
 *
 * The test does NOT exhaustively check every wrapped button on every
 * page (the per-page tests cover that surface). It uses
 * BackupStorageLocationListPage as a representative read/write page,
 * trusting that the same <IfRole minimum="READ_WRITE"> wrapping pattern
 * applied across drivers / deployments / environments / settings
 * behaves identically.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createRouter,
  createRootRoute,
  createMemoryHistory,
  RouterProvider,
} from "@tanstack/react-router";

import {
  AuthContext,
  type AuthContextValue,
  type CurrentUser,
} from "@/auth/AuthProvider";
import { AppShell } from "@/components/AppShell";
import BackupStorageLocationListPage from "@/pages/backup-storage-locations/BackupStorageLocationListPage";
import { ThemeProvider } from "@/hooks/use-theme";

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

function makeAuthValue(currentUser: CurrentUser | null): AuthContextValue {
  return {
    currentUser,
    loading: false,
    refresh: () => Promise.resolve(),
    logout: () => Promise.resolve(),
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function installFetch(): void {
  // The BSL list page issues a `listBackupStorageLocations` query on
  // mount. Stub it to return an empty list so the page renders without
  // network errors and the create-button surface is rendered.
  const fetchMock = vi.fn(async () =>
    jsonResponse({ data: { backupStorageLocations: [] } }),
  );
  vi.stubGlobal("fetch", fetchMock);
}

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

function makeTestRouter() {
  const rootRoute = createRootRoute({
    component: () => (
      <>
        <AppShell />
        <BackupStorageLocationListPage />
      </>
    ),
  });
  return createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
}

async function renderWithRole(role: Role | null): Promise<void> {
  const auth = makeAuthValue(role === null ? null : makeUser(role));
  const router = makeTestRouter();
  await router.load();
  const qc = makeQueryClient();
  await act(async () => {
    render(
      <ThemeProvider>
        <QueryClientProvider client={qc}>
          <AuthContext.Provider value={auth}>
            <RouterProvider router={router} />
          </AuthContext.Provider>
        </QueryClientProvider>
      </ThemeProvider>,
    );
  });
}

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] ?? null),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value;
    }),
    removeItem: vi.fn((key: string) => {
      delete store[key];
    }),
    clear: vi.fn(() => {
      store = {};
    }),
    get length() {
      return Object.keys(store).length;
    },
    key: vi.fn(() => null),
  };
})();

describe("role gating (US5)", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", localStorageMock);
    localStorageMock.clear();
    installFetch();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("hides write buttons and admin nav for a READ_ONLY user", async () => {
    await renderWithRole("READ_ONLY");

    // Wait for the page to settle past the initial loading state.
    await waitFor(() => {
      expect(
        screen.queryByText(/Loading backup storage locations/i),
      ).not.toBeInTheDocument();
    });

    // "New Storage Location" is the create-mutation trigger on this page.
    // It must be absent for a READ_ONLY viewer.
    expect(screen.queryByText("New Storage Location")).not.toBeInTheDocument();

    // Admin-only nav entries must also be absent.
    expect(screen.queryByText("Users")).not.toBeInTheDocument();
    expect(screen.queryByText("Groups")).not.toBeInTheDocument();
  });

  it("shows write buttons but hides admin nav for a READ_WRITE user", async () => {
    await renderWithRole("READ_WRITE");

    await waitFor(() => {
      expect(
        screen.queryByText(/Loading backup storage locations/i),
      ).not.toBeInTheDocument();
    });

    // Write button visible for READ_WRITE.
    expect(screen.getByText("New Storage Location")).toBeInTheDocument();

    // Admin nav still hidden — it requires ADMIN.
    expect(screen.queryByText("Users")).not.toBeInTheDocument();
    expect(screen.queryByText("Groups")).not.toBeInTheDocument();
  });

  it("shows write buttons and admin nav for an ADMIN user", async () => {
    await renderWithRole("ADMIN");

    await waitFor(() => {
      expect(
        screen.queryByText(/Loading backup storage locations/i),
      ).not.toBeInTheDocument();
    });

    expect(screen.getByText("New Storage Location")).toBeInTheDocument();
    expect(screen.getByText("Users")).toBeInTheDocument();
    expect(screen.getByText("Groups")).toBeInTheDocument();
  });

  it("treats an unauthenticated context like below-minimum (hides everything)", async () => {
    await renderWithRole(null);

    await waitFor(() => {
      expect(
        screen.queryByText(/Loading backup storage locations/i),
      ).not.toBeInTheDocument();
    });

    expect(screen.queryByText("New Storage Location")).not.toBeInTheDocument();
    expect(screen.queryByText("Users")).not.toBeInTheDocument();
    expect(screen.queryByText("Groups")).not.toBeInTheDocument();
  });
});
