/**
 * Upgrade dialog: "Latest (auto)" ignores the driver directory, so the dialog
 * warns when the driver's versions come from more than one (#517 review).
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, act, waitFor, within } from "@testing-library/react";
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
const driverVersionsMock = vi.fn();
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
      data: { applicationDriver: { versions: driverVersionsMock() } },
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

function makeDeployment(
  componentImageOverrides: ImageOverride[] = [],
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

async function openUpgradeDialog(overrides: ImageOverride[] = []) {
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

function driverVersion(id: string, driverDirectory: string | null) {
  return {
    id,
    version: "1.0.0",
    createdOn: "2026-10-01T00:00:00Z",
    contentHash: null,
    sourceCommitSha: "abc1234567890abcdef1234567890abcdef12345",
    sourceType: "git",
    sourcePath: driverDirectory,
    driverDirectory,
  };
}

describe("DeploymentDetailPage upgrade dialog: driver directory", () => {
  beforeEach(() => {
    useGetDeploymentQueryMock.mockReset();
    driverVersionsMock.mockReset();
  });

  it("warns that Latest (auto) can move the deployment to another driver directory", async () => {
    driverVersionsMock.mockReturnValue([
      driverVersion("adv-1", "drivers/a"),
      driverVersion("adv-2", "drivers/b"),
    ]);

    const dialog = await openUpgradeDialog();

    const notice = within(dialog).getByTestId("driver-directory-change-notice");
    expect(notice).toHaveTextContent(
      "This deployment uses a driver version from drivers/a. Other versions " +
        "of this driver come from drivers/b.",
    );
    expect(notice).toHaveTextContent("To stay in drivers/a, pick a version.");
  });

  it("names the repository root when the deployment's version was loaded from it", async () => {
    driverVersionsMock.mockReturnValue([
      driverVersion("adv-1", null),
      driverVersion("adv-2", "drivers/b"),
    ]);

    const dialog = await openUpgradeDialog();

    expect(
      within(dialog).getByTestId("driver-directory-change-notice"),
    ).toHaveTextContent("uses a driver version from the repository root.");
  });

  it("shows the label of the selected driver version, not its raw value", async () => {
    driverVersionsMock.mockReturnValue([
      driverVersion("adv-1", "drivers/a"),
      driverVersion("adv-2", "drivers/b"),
    ]);

    const dialog = await openUpgradeDialog();

    const trigger = within(dialog).getByTestId("upgrade-driver-version-select");
    expect(trigger).toHaveTextContent("Latest (auto)");
    await userEvent.click(trigger);
    const option = await screen.findByRole("option", { name: /drivers\/b/ });
    const label = option.textContent ?? "";
    await userEvent.click(option);
    await waitFor(() => expect(trigger).toHaveTextContent(label));
    expect(trigger).not.toHaveTextContent("adv-2");
  });

  it("shows no warning when every version comes from one driver directory", async () => {
    driverVersionsMock.mockReturnValue([
      driverVersion("adv-1", "drivers/a"),
      driverVersion("adv-2", "drivers/a"),
    ]);

    const dialog = await openUpgradeDialog();

    expect(
      within(dialog).queryByTestId("driver-directory-change-notice"),
    ).not.toBeInTheDocument();
  });
});
