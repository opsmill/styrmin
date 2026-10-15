/**
 * Upgrade dialog: pinned image overrides are listed before Confirm
 * (018-component-image-overrides, User Story 2 scenario 3, FR-008).
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
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

import { AuthContext, type AuthContextValue } from "@/auth/AuthProvider";
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
    useGetDriverQuery: () => ({
      ...noopQueryResult,
      data: { applicationDriver: { versions: [] } },
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

type DeploymentShape = NonNullable<GetDeploymentQuery["deployment"]>;
type ImageOverride = DeploymentShape["componentImageOverrides"][number];

const PINNED_REF = "registry.example/acme/app-patched:1.0.0";

function makeDeployment(
  componentImageOverrides: ImageOverride[],
): DeploymentShape {
  return {
    id: "dep-1",
    name: "web",
    status: "active",
    deletedAt: null,
    config: {},
    parameters: {},
    applicationVersion: "1.0.0",
    applicationDriverVersionId: "adv-1",
    environmentId: "env-1",
    applicationDriverVersion: {
      id: "adv-1",
      version: "1.0.0",
      contentHash: "a".repeat(64),
      sourceCommitSha: null,
      applicationDriver: { id: "drv-1", name: "simple-app" },
      parameters: [],
      componentConfigs: [],
    },
    environment: {
      id: "env-1",
      name: "dev",
      config: {},
      cluster: { id: "c-1", name: "kind", config: {} },
    },
    applicationInstance: { id: "inst-1", status: "running" },
    components: [],
    componentImageOverrides,
    componentContainerOverrides: [],
    componentReplicas: [],
    deployedServices: [],
  } as unknown as DeploymentShape;
}

const authValue: AuthContextValue = {
  currentUser: {
    id: "user-rw",
    username: "rw-user",
    displayName: "RW User",
    role: "READ_WRITE",
    effectiveRole: "READ_WRITE",
    active: true,
  },
  loading: false,
  refresh: () => Promise.resolve(),
  logout: () => Promise.resolve(),
};

async function openUpgradeDialog(overrides: ImageOverride[]) {
  useGetDeploymentQueryMock.mockReturnValue({
    data: { deployment: makeDeployment(overrides) } as GetDeploymentQuery,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    dataUpdatedAt: Date.now(),
  });
  const rootRoute = createRootRoute();
  const depRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/environments/$environmentId/deployments/$deploymentId",
    component: () => <DeploymentDetailPage />,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([depRoute]),
    history: createMemoryHistory({
      initialEntries: ["/environments/env-1/deployments/dep-1"],
    }),
  });
  await router.load();
  await act(async () => {
    render(
      <ThemeProvider>
        <QueryClientProvider client={new QueryClient()}>
          <AuthContext.Provider value={authValue}>
            <RouterProvider router={router} />
          </AuthContext.Provider>
        </QueryClientProvider>
      </ThemeProvider>,
    );
  });
  await userEvent.click(await screen.findByRole("button", { name: "Upgrade" }));
  return screen.findByRole("dialog");
}

describe("DeploymentDetailPage upgrade dialog: pinned image overrides", () => {
  beforeEach(() => {
    useGetDeploymentQueryMock.mockReset();
  });

  it("lists the pinned override above the Upgrade button", async () => {
    const dialog = await openUpgradeDialog([
      {
        component: "server",
        reference: PINNED_REF,
        resolvedReference: PINNED_REF,
        isOrphaned: false,
        isApplicable: true,
      },
    ]);

    const notice = within(dialog).getByTestId("pinned-image-overrides-notice");
    expect(
      within(notice).getByTestId("pinned-image-override"),
    ).toHaveTextContent(`server (${PINNED_REF})`);
    const confirm = within(dialog).getByRole("button", { name: "Upgrade" });
    expect(
      notice.compareDocumentPosition(confirm) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("shows no notice when the override follows the application version", async () => {
    const dialog = await openUpgradeDialog([
      {
        component: "server",
        reference: "registry.example/acme/app-patched:{{ app.version }}",
        resolvedReference: PINNED_REF,
        isOrphaned: false,
        isApplicable: true,
      },
    ]);

    expect(
      within(dialog).queryByTestId("pinned-image-overrides-notice"),
    ).not.toBeInTheDocument();
  });
});
