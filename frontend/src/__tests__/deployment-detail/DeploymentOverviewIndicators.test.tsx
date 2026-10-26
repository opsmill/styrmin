/**
 * DeploymentDetailPage Overview tab indicators (#567).
 *
 * The endpoint dot and the component dot are green only when the deployment
 * runs and every pod of the component is ready.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
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
import type { GetDeploymentQuery } from "@/generated/graphql";

// Mock generated hooks so the page renders deterministically.
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
    useListBackupsQuery: () => ({
      ...noopQueryResult,
      data: { backups: [] },
    }),
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

// Mock the PodsTab — it pulls its own hooks; we don't exercise it here.
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
type AdvShape = DeploymentShape["applicationDriverVersion"];

function makeDeployment(
  overrides: Partial<DeploymentShape> & {
    applicationDriverVersion?: AdvShape | null;
  } = {},
): DeploymentShape {
  const baseAdv: AdvShape = {
    id: "adv-1",
    version: "1.2.3",
    contentHash: "a".repeat(64),
    sourceCommitSha: null,
    applicationDriver: { id: "drv-1", name: "nginx" },
    parameters: [],
    componentConfigs: [],
  } as AdvShape;

  const base: DeploymentShape = {
    id: "dep-1",
    name: "web",
    status: "active",
    deletedAt: null,
    config: {},
    parameters: {},
    applicationVersion: "2.5.0",
    applicationDriverVersionId: "adv-1",
    environmentId: "env-1",
    applicationDriverVersion: baseAdv,
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
    podStatuses: [],
    deployedServices: [],
  } as DeploymentShape;

  return { ...base, ...overrides } as DeploymentShape;
}

function makeQueryResult(deployment: DeploymentShape | null) {
  return {
    data: { deployment } as GetDeploymentQuery,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    dataUpdatedAt: Date.now(),
  };
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

async function renderPage() {
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
}

type Pod = DeploymentShape["podStatuses"][number];
type Service = DeploymentShape["deployedServices"][number];

function pod(overrides: Partial<Pod> = {}): Pod {
  return {
    id: "pod-1",
    componentName: "app",
    phase: "RUNNING",
    ready: true,
    ...overrides,
  } as Pod;
}

const service = {
  id: "svc-1",
  driverServiceName: "http",
  resolvedName: "http",
  kind: "http",
  component: "app",
  port: 8080,
  primaryFqdn: null,
  humanReadableFqdn: null,
  primaryUrl: null,
  humanReadableUrl: null,
} as Service;

function deploymentWith(status: string, podStatuses: Pod[]): DeploymentShape {
  return makeDeployment({
    status,
    components: [
      { id: "cmp-1", name: "app", enabled: true, container: null },
    ] as DeploymentShape["components"],
    deployedServices: [service],
    podStatuses,
  });
}

/** The dot rendered just before a label, in the old and the new markup alike. */
function dotBefore(label: string): Element {
  const dot = screen.getByText(label).previousElementSibling;
  if (!dot) throw new Error(`no indicator before ${label}`);
  return dot;
}

describe("DeploymentDetailPage Overview indicators", () => {
  beforeEach(() => {
    useGetDeploymentQueryMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it.each([
    ["the deployment is deploying with no pod", "deploying", []],
    [
      "the pod runs but is not ready (CrashLoopBackOff)",
      "running",
      [pod({ ready: false })],
    ],
    ["the deployment failed", "failed", [pod({ ready: false })]],
    ["the running deployment has no pod reported", "running", []],
  ] as [string, string, Pod[]][])(
    "does not show the endpoint and component dots green when %s",
    async (_case, status, pods) => {
      useGetDeploymentQueryMock.mockReturnValue(
        makeQueryResult(deploymentWith(status, pods)),
      );

      await renderPage();

      expect(dotBefore("http").className).not.toMatch(/bg-success/);
      expect(dotBefore("app").className).not.toMatch(/bg-success/);
    },
  );

  it("shows the endpoint and component dots green when every pod is ready", async () => {
    useGetDeploymentQueryMock.mockReturnValue(
      makeQueryResult(deploymentWith("running", [pod(), pod({ id: "pod-2" })])),
    );

    await renderPage();

    expect(dotBefore("http").className).toMatch(/bg-success/);
    expect(dotBefore("app").className).toMatch(/bg-success/);
    expect(dotBefore("app").getAttribute("title")).toBe("2 of 2 pods ready");
  });
});
