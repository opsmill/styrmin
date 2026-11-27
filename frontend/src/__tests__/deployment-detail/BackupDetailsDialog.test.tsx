/**
 * Rename a backup and change its description (spec 034, US1 / FR-012).
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
import { GraphQLOperationError } from "@/lib/graphql-fetcher";
import DeploymentDetailPage from "@/pages/deployments/DeploymentDetailPage";
import { BackupDetailsDialog } from "@/pages/deployments/BackupDetailsDialog";
import type { GetDeploymentQuery, ListBackupsQuery } from "@/generated/graphql";

const updateBackupMock = vi.fn();
const createBackupMock = vi.fn();
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

let deploymentStatus = "active";

const DEPLOYMENT = {
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
  applicationInstance: { id: "inst-1" },
  components: [],
  componentImageOverrides: [],
  componentContainerOverrides: [],
  componentReplicas: [],
  deployedServices: [],
} as unknown as NonNullable<GetDeploymentQuery["deployment"]>;

const BACKUP = {
  id: "backup-1",
  name: "before-upgrade",
  description: "Taken before the 2.6 upgrade",
  status: "completed",
  createdOn: "2026-08-03T12:04:06+00:00",
  completedAt: "2026-08-03T12:05:06+00:00",
  sizeBytes: 1024,
  errorMessage: null,
  ttl: null,
  expiresAt: null,
  instance: { id: "inst-1", applicationVersion: "2.5.0" },
  steps: [],
} as ListBackupsQuery["backups"][number];

vi.mock("@/generated/graphql", async () => {
  const actual = await vi.importActual<typeof import("@/generated/graphql")>(
    "@/generated/graphql",
  );
  return {
    ...actual,
    useGetDeploymentQuery: () => ({
      ...noopQueryResult,
      data: { deployment: { ...DEPLOYMENT, status: deploymentStatus } },
    }),
    useGetDeploymentTimelineQuery: () => ({
      ...noopQueryResult,
      data: { deploymentTimeline: [] },
    }),
    useListBackupsQuery: () => ({
      ...noopQueryResult,
      data: { backups: [BACKUP] },
      dataUpdatedAt: Date.now(),
    }),
    useListRestoresQuery: () => ({
      ...noopQueryResult,
      data: { restores: [] },
    }),
    useUpdateBackupMutation: () => ({
      ...noopMutationResult,
      mutateAsync: updateBackupMock,
    }),
    useCreateBackupMutation: () => ({
      ...noopMutationResult,
      mutateAsync: createBackupMock,
    }),
    useDeleteBackupMutation: () => noopMutationResult,
    useCreateRestoreMutation: () => noopMutationResult,
    useDeleteDeploymentMutation: () => noopMutationResult,
    useUpdateDeploymentVersionMutation: () => noopMutationResult,
  };
});

vi.mock("@/pages/deployments/PodsTab", () => ({
  PodsTab: () => <div>pods tab stub</div>,
}));

const AUTH: AuthContextValue = {
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

async function renderBackupsTab() {
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
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  await act(async () => {
    render(
      <ThemeProvider>
        <QueryClientProvider client={qc}>
          <AuthContext.Provider value={AUTH}>
            <RouterProvider router={router} />
          </AuthContext.Provider>
        </QueryClientProvider>
      </ThemeProvider>,
    );
  });
  await userEvent.click(screen.getByRole("button", { name: "Backups" }));
}

function renderDialog(
  props: Partial<Parameters<typeof BackupDetailsDialog>[0]> = {},
) {
  const onSubmit = props.onSubmit ?? vi.fn().mockResolvedValue(undefined);
  render(
    <BackupDetailsDialog
      open
      onOpenChange={() => {}}
      mode="edit"
      initialName="before-upgrade"
      initialDescription="old note"
      {...props}
      onSubmit={onSubmit}
    />,
  );
  return onSubmit;
}

describe("BackupDetailsDialog", () => {
  beforeEach(() => {
    deploymentStatus = "active";
    updateBackupMock.mockReset();
    updateBackupMock.mockResolvedValue({});
    createBackupMock.mockReset();
    createBackupMock.mockResolvedValue({});
  });

  it("opens the dialog from Create Backup and sends only the filled fields", async () => {
    await renderBackupsTab();

    await userEvent.click(
      screen.getByRole("button", { name: /Create Backup/ }),
    );
    expect(screen.getByTestId("backup-details-dialog")).toBeInTheDocument();
    expect(createBackupMock).not.toHaveBeenCalled();

    await userEvent.type(
      screen.getByTestId("backup-details-description"),
      "Before the 2.6 upgrade",
    );
    await userEvent.click(screen.getByTestId("backup-details-submit"));

    expect(createBackupMock).toHaveBeenCalledWith({
      instanceId: "inst-1",
      description: "Before the 2.6 upgrade",
    });
    await vi.waitFor(() =>
      expect(
        screen.queryByTestId("backup-details-dialog"),
      ).not.toBeInTheDocument(),
    );
  });

  it("shows a create error in the Create Backup dialog", async () => {
    createBackupMock.mockRejectedValue(
      new GraphQLOperationError(
        "ALREADY_EXISTS",
        "A backup with that name already exists for this instance",
      ),
    );
    await renderBackupsTab();

    await userEvent.click(
      screen.getByRole("button", { name: /Create Backup/ }),
    );
    await userEvent.type(screen.getByTestId("backup-details-name"), "taken");
    await userEvent.click(screen.getByTestId("backup-details-submit"));

    expect(createBackupMock).toHaveBeenCalledWith({
      instanceId: "inst-1",
      name: "taken",
    });
    expect(screen.getByTestId("backup-details-error")).toHaveTextContent(
      "A backup with that name already exists for this instance",
    );
  });

  it("shows the description in the backup row as plain text", async () => {
    await renderBackupsTab();

    const row = screen.getByTestId("backup-row");
    expect(row.getAttribute("data-backup-description")).toBe(
      BACKUP.description,
    );
    const description = within(row).getByTestId("backup-description");
    expect(description.textContent).toBe(BACKUP.description);
    expect(description.getAttribute("title")).toBe(BACKUP.description);
    expect(description.className).toContain("line-clamp-2");
  });

  it("keeps Edit enabled while the deployment is being deleted", async () => {
    deploymentStatus = "deleting";
    await renderBackupsTab();

    const row = screen.getByTestId("backup-row");
    expect(within(row).getByTestId("backup-edit")).toBeEnabled();
    expect(within(row).getByRole("button", { name: "Delete" })).toBeDisabled();
  });

  it("pre-fills edit mode and sends only the changed fields", async () => {
    await renderBackupsTab();

    await userEvent.click(screen.getByTestId("backup-edit"));
    const name = screen.getByTestId("backup-details-name");
    const description = screen.getByTestId("backup-details-description");
    expect(name).toHaveValue(BACKUP.name);
    expect(description).toHaveValue(BACKUP.description);

    await userEvent.clear(description);
    await userEvent.type(description, "Kept for the audit");
    await userEvent.click(screen.getByTestId("backup-details-submit"));

    expect(updateBackupMock).toHaveBeenCalledWith({
      backupId: BACKUP.id,
      description: "Kept for the audit",
    });
  });

  it("sends an empty description to clear it", async () => {
    const onSubmit = renderDialog();

    await userEvent.clear(screen.getByTestId("backup-details-description"));
    await userEvent.click(screen.getByTestId("backup-details-submit"));

    expect(onSubmit).toHaveBeenCalledWith({ description: "" });
  });

  it("rejects a whitespace-only name", async () => {
    const onSubmit = renderDialog();

    const name = screen.getByTestId("backup-details-name");
    await userEvent.clear(name);
    await userEvent.type(name, "   ");
    await userEvent.click(screen.getByTestId("backup-details-submit"));

    expect(screen.getByText("The name cannot be empty")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("shows a server ALREADY_EXISTS error", async () => {
    const onSubmit = vi
      .fn()
      .mockRejectedValue(
        new GraphQLOperationError(
          "ALREADY_EXISTS",
          "A backup with that name already exists for this instance",
        ),
      );
    renderDialog({ onSubmit });

    const name = screen.getByTestId("backup-details-name");
    await userEvent.clear(name);
    await userEvent.type(name, "taken");
    await userEvent.click(screen.getByTestId("backup-details-submit"));

    expect(onSubmit).toHaveBeenCalledWith({ name: "taken" });
    expect(screen.getByTestId("backup-details-error")).toHaveTextContent(
      "A backup with that name already exists for this instance",
    );
  });

  it("focuses the submit button in create mode so Enter submits the empty form", async () => {
    const onSubmit = renderDialog({
      mode: "create",
      initialName: undefined,
      initialDescription: undefined,
    });

    await vi.waitFor(() =>
      expect(screen.getByTestId("backup-details-submit")).toHaveFocus(),
    );
    await userEvent.keyboard("{Enter}");

    expect(onSubmit).toHaveBeenCalledWith({});
  });
});
