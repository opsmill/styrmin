/**
 * Deployment-detail browser tab title (issue #332).
 *
 * The tab title must name the deployment once it has loaded, and fall back to
 * the generic page label while the query is still in flight — never the Vite
 * scaffold default.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, act, waitFor } from "@testing-library/react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
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
import type { GetDeploymentQuery } from "@/generated/graphql";

const useGetDeploymentQueryMock = vi.fn();
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
    useListBackupsQuery: () => ({ ...noopQueryResult, data: { backups: [] } }),
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

vi.mock("@/pages/deployments/PodsTab", () => ({
  PodsTab: () => <div>pods tab stub</div>,
}));

function makeAuthValue(): AuthContextValue {
  const user: CurrentUser = {
    id: "user-rw",
    username: "rw-user",
    displayName: "RW User",
    role: "READ_WRITE",
    effectiveRole: "READ_WRITE",
    active: true,
  };
  return {
    currentUser: user,
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
      componentConfigs: [],
    },
    environment: {
      id: "env-1",
      name: "dev",
      config: {},
      cluster: { id: "c-1", name: "kind", config: {} },
    },
    applicationInstance: null,
    components: [],
    componentImageOverrides: [],
    componentContainerOverrides: [],
    componentReplicas: [],
    deployedServices: [],
  } as DeploymentShape;
}

async function renderPage() {
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
  const router = createRouter({
    routeTree: rootRoute.addChildren([homeRoute, envRoute, depRoute]),
    history: createMemoryHistory({
      initialEntries: ["/environments/env-1/deployments/dep-1"],
    }),
  });
  await router.load();

  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });

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
}

describe("deployment detail document title", () => {
  beforeEach(() => {
    document.title = "";
    useGetDeploymentQueryMock.mockReset();
  });

  it("names the deployment once it has loaded", async () => {
    useGetDeploymentQueryMock.mockReturnValue({
      data: { deployment: makeDeployment() } as GetDeploymentQuery,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
      dataUpdatedAt: Date.now(),
    });

    await renderPage();

    await waitFor(() => expect(document.title).toBe("web · Styrmin"));
  });

  it("falls back to the page label while the deployment is loading", async () => {
    useGetDeploymentQueryMock.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
      refetch: vi.fn(),
      dataUpdatedAt: 0,
    });

    await renderPage();

    await waitFor(() => expect(document.title).toBe("Deployment · Styrmin"));
  });
  it("retitles from the fallback to the deployment name when data arrives", async () => {
    // The flow from issue #332: the tab must not sit on the fallback once the
    // deployment resolves. The two endpoint states asserted in isolation above
    // would both still pass on a page that never re-reads the name after mount,
    // so drive a real pending -> resolved query transition here.
    let resolveDeployment!: (value: GetDeploymentQuery) => void;
    const pending = new Promise<GetDeploymentQuery>((resolve) => {
      resolveDeployment = resolve;
    });
    useGetDeploymentQueryMock.mockImplementation(() =>
      useQuery({
        queryKey: ["GetDeployment", "dep-1"],
        queryFn: () => pending,
      }),
    );

    await renderPage();
    await waitFor(() => expect(document.title).toBe("Deployment · Styrmin"));

    await act(async () => {
      resolveDeployment({ deployment: makeDeployment() } as GetDeploymentQuery);
    });

    await waitFor(() => expect(document.title).toBe("web · Styrmin"));
  });
});
