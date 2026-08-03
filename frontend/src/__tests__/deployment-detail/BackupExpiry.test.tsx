/**
 * Backups-tab expiry column (spec 016-backup-retention-ttl, US4 / SC-005).
 *
 * The backup list must answer "when does this backup disappear?" without
 * cluster access: a localized expiry date per row, an em-dash when nothing was
 * recorded, and the applied retention TTL exposed *non-visually* — reachable by
 * screen readers without a hover interaction (critique P2).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, act, within } from "@testing-library/react";
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
import DeploymentDetailPage from "@/pages/deployments/DeploymentDetailPage";
import type {
  GetDeploymentQuery,
  ListBackupsQuery,
} from "@/generated/graphql";

type BackupItem = ListBackupsQuery["backups"][number];

const EXPIRES_AT = "2026-11-01T12:04:06+00:00";

// Mock generated hooks so the page renders deterministically.
const useGetDeploymentQueryMock = vi.fn();
const useListBackupsQueryMock = vi.fn();
const noopQueryResult = {
  data: undefined,
  isLoading: false,
  error: null,
  refetch: vi.fn(),
  dataUpdatedAt: 0,
};
const noopMutationResult = {
  mutateAsync: vi.fn().mockResolvedValue({}),
  mutate: vi.fn(),
  isPending: false,
  isError: false,
  error: null,
};
vi.mock("@/generated/graphql", async () => {
  const actual = await vi.importActual<typeof import("@/generated/graphql")>(
    "@/generated/graphql",
  );
  return {
    ...actual,
    useGetDeploymentQuery: (...args: unknown[]) =>
      useGetDeploymentQueryMock(...args),
    useGetDeploymentTimelineQuery: () => ({
      ...noopQueryResult,
      data: { deploymentTimeline: [] },
    }),
    useListBackupsQuery: (...args: unknown[]) =>
      useListBackupsQueryMock(...args),
    useListRestoresQuery: () => ({
      ...noopQueryResult,
      data: { restores: [] },
    }),
    useCreateBackupMutation: () => noopMutationResult,
    useDeleteBackupMutation: () => noopMutationResult,
    useCreateRestoreMutation: () => noopMutationResult,
    useDeleteDeploymentMutation: () => noopMutationResult,
    useUpdateDeploymentVersionMutation: () => noopMutationResult,
  };
});

// The Pods tab pulls its own hooks and is not exercised here.
vi.mock("@/pages/deployments/PodsTab", () => ({
  PodsTab: () => <div>pods tab stub</div>,
}));

function makeUser(): CurrentUser {
  return {
    id: "user-rw",
    username: "rw-user",
    displayName: "RW User",
    role: "READ_WRITE",
    effectiveRole: "READ_WRITE",
    active: true,
  };
}

function makeAuthValue(): AuthContextValue {
  return {
    currentUser: makeUser(),
    loading: false,
    refresh: () => Promise.resolve(),
    logout: () => Promise.resolve(),
  };
}

type DeploymentShape = NonNullable<GetDeploymentQuery["deployment"]>;

function makeDeployment(): DeploymentShape {
  return {
    id: "dep-1",
    name: "web",
    status: "active",
    deletedAt: null,
    config: {},
    parameters: {},
    applicationVersion: "2.5.0",
    applicationDriverVersionId: "adv-1",
    environmentId: "env-1",
    applicationDriverVersion: {
      id: "adv-1",
      version: "1.2.3",
      contentHash: "a".repeat(64),
      sourceCommitSha: null,
      applicationDriver: { id: "drv-1", name: "nginx" },
      parameters: [],
    },
    environment: {
      id: "env-1",
      name: "dev",
      config: {},
      cluster: { id: "c-1", name: "kind", config: {} },
    },
    applicationInstance: { id: "inst-1" },
    components: [],
    deployedServices: [],
  } as unknown as DeploymentShape;
}

function makeBackup(overrides: Partial<BackupItem> = {}): BackupItem {
  return {
    id: "backup-1",
    name: "backup-1",
    status: "completed",
    createdOn: "2026-08-03T12:04:06+00:00",
    completedAt: "2026-08-03T12:05:06+00:00",
    sizeBytes: 1024,
    errorMessage: null,
    ttl: "2160h",
    expiresAt: EXPIRES_AT,
    ...overrides,
  } as BackupItem;
}

function makeTestRouter() {
  const rootRoute = createRootRoute();
  const homeRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/",
    component: () => <div>home</div>,
  });
  const envRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/environments/$environmentId",
    component: () => <div>environment</div>,
  });
  const depRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/environments/$environmentId/deployments/$deploymentId",
    component: () => <DeploymentDetailPage />,
  });
  return createRouter({
    routeTree: rootRoute.addChildren([homeRoute, envRoute, depRoute]),
    history: createMemoryHistory({
      initialEntries: ["/environments/env-1/deployments/dep-1"],
    }),
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

/** Render the page and switch to the Backups tab. */
async function renderBackupsTab(backups: BackupItem[]) {
  useGetDeploymentQueryMock.mockReturnValue({
    data: { deployment: makeDeployment() } as GetDeploymentQuery,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    dataUpdatedAt: Date.now(),
  });
  useListBackupsQueryMock.mockReturnValue({
    ...noopQueryResult,
    data: { backups } as ListBackupsQuery,
  });

  const router = makeTestRouter();
  await router.load();
  const qc = makeQueryClient();
  await act(async () => {
    render(
      <ThemeProvider>
        <QueryClientProvider client={qc}>
          <AuthContext.Provider value={makeAuthValue()}>
            <RouterProvider router={router} />
          </AuthContext.Provider>
        </QueryClientProvider>
      </ThemeProvider>,
    );
  });

  await userEvent.click(screen.getByRole("button", { name: "Backups" }));
}

describe("DeploymentDetailPage backups tab expiry column", () => {
  beforeEach(() => {
    useGetDeploymentQueryMock.mockReset();
    useListBackupsQueryMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("labels the expiry column in the backups table header", async () => {
    await renderBackupsTab([makeBackup()]);

    expect(screen.getByText("Expires")).toBeInTheDocument();
  });

  it("renders the localized expiry date for a backup that has one", async () => {
    await renderBackupsTab([makeBackup()]);

    const cell = screen.getByTestId("backup-expires");
    expect(cell.textContent).toContain(
      new Date(EXPIRES_AT).toLocaleDateString(),
    );
  });

  it("exposes the applied TTL without requiring hover (title + assistive text)", async () => {
    await renderBackupsTab([makeBackup()]);

    const cell = screen.getByTestId("backup-expires");
    // Sighted mouse users get the native tooltip...
    expect(cell.getAttribute("title")).toContain("2160h");
    // ...and the same value is in the accessibility tree unconditionally, so
    // keyboard and screen-reader users are not locked out of it (critique P2).
    expect(cell.textContent).toContain("2160h");
  });

  it("renders an em-dash when no expiry was recorded", async () => {
    await renderBackupsTab([
      makeBackup({ id: "backup-2", name: "backup-2", ttl: null, expiresAt: null }),
    ]);

    const cell = screen.getByTestId("backup-expires");
    expect(cell.textContent).toContain("—");
    expect(cell.getAttribute("title")).toBeNull();
  });

  it("keeps the expiry date when only the TTL is missing", async () => {
    await renderBackupsTab([makeBackup({ ttl: null })]);

    const row = screen.getByTestId("backup-row");
    const cell = within(row).getByTestId("backup-expires");
    expect(cell.textContent).toContain(
      new Date(EXPIRES_AT).toLocaleDateString(),
    );
    expect(cell.getAttribute("title")).toBeNull();
  });
});
