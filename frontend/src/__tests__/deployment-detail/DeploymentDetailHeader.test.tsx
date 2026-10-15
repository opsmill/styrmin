/**
 * DeploymentDetailPage header tests (feature 013 follow-up).
 *
 * Asserts the deployment-detail header "Driver" line renders the driver
 * name followed by `v<version>@<short>` in font-mono, for both local
 * and git-source deployments, and degrades cleanly when the embedded
 * driver-version reference is null.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, act, within } from "@testing-library/react";
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

describe("DeploymentDetailPage header driver label", () => {
  beforeEach(() => {
    useGetDeploymentQueryMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders `Driver <driverName>` then v<version>@<short> (font-mono) for a local-source deployment", async () => {
    const deployment = makeDeployment({
      applicationDriverVersion: {
        id: "adv-1",
        version: "1.2.3",
        contentHash: "a".repeat(64),
        sourceCommitSha: null,
        applicationDriver: { id: "drv-1", name: "nginx" },
        parameters: [],
      } as AdvShape,
    });
    useGetDeploymentQueryMock.mockReturnValue(makeQueryResult(deployment));

    await renderPage();

    const header = await screen.findByTestId("deployment-detail");
    expect(header.getAttribute("data-driver-name")).toBe("nginx");

    // The label "Driver" is followed by the driver name and then the
    // formatted v<version>@<short> in font-mono.
    expect(within(header).getByText("nginx")).toBeInTheDocument();
    const label = within(header).getByText("v1.2.3@aaaaaaa");
    expect(label).toBeInTheDocument();
    expect(label.className).toMatch(/font-mono/);
  });

  it("renders the same shape with v<version>@<short-sourceCommitSha> for a git-source deployment", async () => {
    const deployment = makeDeployment({
      applicationDriverVersion: {
        id: "adv-2",
        version: "2.0.0",
        contentHash: null,
        sourceCommitSha: "b".repeat(40),
        applicationDriver: { id: "drv-2", name: "redis" },
        parameters: [],
      } as AdvShape,
    });
    useGetDeploymentQueryMock.mockReturnValue(makeQueryResult(deployment));

    await renderPage();

    const header = await screen.findByTestId("deployment-detail");
    expect(within(header).getByText("redis")).toBeInTheDocument();
    const label = within(header).getByText("v2.0.0@bbbbbbb");
    expect(label).toBeInTheDocument();
    expect(label.className).toMatch(/font-mono/);
  });

  it("omits the v<...> suffix when applicationDriverVersion is null (defensive)", async () => {
    // Production code currently always has applicationDriverVersion, but
    // the rendering branch guards against null — assert the guard works.
    const deployment = makeDeployment({
      applicationDriverVersion: null as unknown as AdvShape,
    });
    useGetDeploymentQueryMock.mockReturnValue(makeQueryResult(deployment));

    await renderPage();

    const header = await screen.findByTestId("deployment-detail");
    // No formatted driver-version label rendered.
    expect(
      within(header).queryByText(/^v\d+\.\d+\.\d+/),
    ).not.toBeInTheDocument();
    // Falls back to applicationDriverVersionId for the driver text.
    expect(within(header).getByText("adv-1")).toBeInTheDocument();
  });

  it("ensures the trigger uses formatDriverVersionLabel — same version + different fingerprint render visually distinct", async () => {
    const deployment = makeDeployment({
      applicationDriverVersion: {
        id: "adv-1",
        version: "1.2.3",
        contentHash: "deadbee" + "f".repeat(57),
        sourceCommitSha: null,
        applicationDriver: { id: "drv-1", name: "nginx" },
        parameters: [],
      } as AdvShape,
    });
    useGetDeploymentQueryMock.mockReturnValue(makeQueryResult(deployment));

    await renderPage();

    await waitFor(() => {
      expect(screen.getByText("v1.2.3@deadbee")).toBeInTheDocument();
    });
  });
});

describe("DeploymentDetailPage header actions", () => {
  beforeEach(() => {
    useGetDeploymentQueryMock.mockReset();
  });

  it("offers Upgrade and Delete, and no Redeploy (#428)", async () => {
    useGetDeploymentQueryMock.mockReturnValue(
      makeQueryResult(makeDeployment()),
    );

    await renderPage();

    const header = await screen.findByTestId("deployment-detail");
    expect(
      within(header).getByRole("button", { name: "Upgrade" }),
    ).toBeInTheDocument();
    expect(
      within(header).getByTestId("delete-deployment-button"),
    ).toBeInTheDocument();
    expect(
      within(header).queryByRole("button", { name: "Redeploy" }),
    ).not.toBeInTheDocument();
  });
});
