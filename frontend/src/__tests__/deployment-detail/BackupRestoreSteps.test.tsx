/**
 * Steps of backups and restores on the Backups tab (spec 019-task-steps, US6,
 * SC-005): a backup lists one step per component with its start time, end
 * time and result; a restore lists its three steps in order with durations and
 * names the failed step with its error; older rows show a notice.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
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
  ListRestoresQuery,
} from "@/generated/graphql";

type BackupItem = ListBackupsQuery["backups"][number];
type RestoreItem = ListRestoresQuery["restores"][number];
type StepItem = BackupItem["steps"][number];

const useGetDeploymentQueryMock = vi.fn();
const useListBackupsQueryMock = vi.fn();
const useListRestoresQueryMock = vi.fn();
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
    useListRestoresQuery: (...args: unknown[]) =>
      useListRestoresQueryMock(...args),
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
    id: "user-ro",
    username: "ro-user",
    displayName: "RO User",
    role: "READ_ONLY",
    effectiveRole: "READ_ONLY",
    active: true,
  };
  return {
    currentUser: user,
    loading: false,
    refresh: () => Promise.resolve(),
    logout: () => Promise.resolve(),
  };
}

function makeDeployment(): NonNullable<GetDeploymentQuery["deployment"]> {
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
    componentImageOverrides: [],
    deployedServices: [],
  } as unknown as NonNullable<GetDeploymentQuery["deployment"]>;
}

function makeStep(overrides: Partial<StepItem>): StepItem {
  return {
    id: "step",
    key: "step",
    name: "Step",
    kind: "RESTORE",
    status: "SUCCEEDED",
    startedAt: null,
    endedAt: null,
    durationSeconds: null,
    attemptCount: 1,
    error: null,
    errors: [],
    ...overrides,
  };
}

const COMPONENT_STEPS: StepItem[] = [
  makeStep({
    id: "web",
    key: "backup:component:web",
    name: "Back up web",
    kind: "BACKUP_COMPONENT",
    status: "FAILED",
    startedAt: "2026-10-06T10:00:05+00:00",
    endedAt: "2026-10-06T10:01:05+00:00",
    durationSeconds: 60,
    error: "pod volume backup web-data failed: disk full",
    errors: [
      {
        attempt: 1,
        message: "pod volume backup web-data failed: disk full",
        occurredAt: "2026-10-06T10:01:05+00:00",
      },
    ],
  }),
  makeStep({
    id: "db",
    key: "backup:component:db",
    name: "Back up db",
    kind: "BACKUP_COMPONENT",
    startedAt: "2026-10-06T10:00:10+00:00",
    endedAt: "2026-10-06T10:00:40+00:00",
    durationSeconds: 30,
  }),
];

const VELERO_ERROR = "Velero restore FailedValidation: backup not found";

const RESTORE_STEPS: StepItem[] = [
  makeStep({
    id: "namespace",
    key: "restore:namespace",
    name: "Delete the namespace",
    startedAt: "2026-10-06T11:00:00+00:00",
    endedAt: "2026-10-06T11:00:12+00:00",
    durationSeconds: 12,
  }),
  makeStep({
    id: "velero",
    key: "restore:velero",
    name: "Run the Velero restore",
    status: "FAILED",
    startedAt: "2026-10-06T11:00:12+00:00",
    endedAt: "2026-10-06T11:00:20+00:00",
    durationSeconds: 8,
    error: VELERO_ERROR,
    errors: [
      {
        attempt: 1,
        message: VELERO_ERROR,
        occurredAt: "2026-10-06T11:00:20+00:00",
      },
    ],
  }),
  makeStep({
    id: "recovery",
    key: "restore:recovery",
    name: "Run the recovery",
    status: "PENDING",
    attemptCount: 0,
  }),
];

function makeBackup(overrides: Partial<BackupItem> = {}): BackupItem {
  return {
    id: "backup-1",
    name: "backup-1",
    status: "completed",
    createdOn: "2026-10-06T10:00:00+00:00",
    completedAt: "2026-10-06T10:01:05+00:00",
    sizeBytes: 1024,
    errorMessage: null,
    ttl: "2160h",
    expiresAt: null,
    steps: [],
    ...overrides,
  };
}

function makeRestore(overrides: Partial<RestoreItem> = {}): RestoreItem {
  return {
    id: "restore-1",
    name: "restore-1",
    status: "failed",
    createdOn: "2026-10-06T11:00:00+00:00",
    startedAt: "2026-10-06T11:00:00+00:00",
    completedAt: "2026-10-06T11:00:20+00:00",
    targetNamespace: "styrmin-dep-1",
    errorMessage: "Velero restore failed",
    componentStatuses: null,
    steps: [],
    ...overrides,
  };
}

async function renderBackupsTab(
  backups: BackupItem[],
  restoresByBackup: Record<string, RestoreItem[]> = {},
) {
  useGetDeploymentQueryMock.mockReturnValue({
    ...noopQueryResult,
    data: { deployment: makeDeployment() },
    dataUpdatedAt: Date.now(),
  });
  useListBackupsQueryMock.mockReturnValue({
    ...noopQueryResult,
    data: { backups },
  });
  useListRestoresQueryMock.mockImplementation(
    (variables: { backupId: string }) => ({
      ...noopQueryResult,
      data: { restores: restoresByBackup[variables.backupId] ?? [] },
    }),
  );

  const rootRoute = createRootRoute();
  const router = createRouter({
    routeTree: rootRoute.addChildren([
      createRoute({
        getParentRoute: () => rootRoute,
        path: "/environments/$environmentId/deployments/$deploymentId",
        component: () => <DeploymentDetailPage />,
      }),
    ]),
    history: createMemoryHistory({
      initialEntries: ["/environments/env-1/deployments/dep-1"],
    }),
  });
  await router.load();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  await act(async () => {
    render(
      <ThemeProvider>
        <QueryClientProvider client={queryClient}>
          <AuthContext.Provider value={makeAuthValue()}>
            <RouterProvider router={router} />
          </AuthContext.Provider>
        </QueryClientProvider>
      </ThemeProvider>,
    );
  });
  await userEvent.click(screen.getByRole("button", { name: "Backups" }));
}

function backupSteps(backupId: string): HTMLElement {
  const container = document.querySelector<HTMLElement>(
    `[data-testid=backup-steps][data-backup-id="${backupId}"]`,
  );
  expect(container).not.toBeNull();
  return container as HTMLElement;
}

function restoreSteps(restoreId: string): HTMLElement {
  const container = document.querySelector<HTMLElement>(
    `[data-testid=restore-steps][data-restore-id="${restoreId}"]`,
  );
  expect(container).not.toBeNull();
  return container as HTMLElement;
}

function stepRows(container: HTMLElement): HTMLElement[] {
  return within(container).queryAllByTestId("step-row");
}

describe("DeploymentDetailPage backup and restore steps", () => {
  beforeEach(() => {
    useGetDeploymentQueryMock.mockReset();
    useListBackupsQueryMock.mockReset();
    useListRestoresQueryMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows each component of a failed backup with its start time, end time and result", async () => {
    await renderBackupsTab([
      makeBackup({ status: "failed", steps: COMPONENT_STEPS }),
    ]);

    const container = backupSteps("backup-1");
    expect(container).toHaveAttribute("data-expanded", "true");
    const rows = stepRows(container);
    expect(rows.map((row) => row.getAttribute("data-step-key"))).toEqual([
      "backup:component:web",
      "backup:component:db",
    ]);
    const [web, db] = rows;
    expect(web).toBeVisible();
    expect(within(web).getByTestId("step-name")).toHaveTextContent(
      "Back up web",
    );
    expect(within(web).getByTestId("step-status")).toHaveTextContent("Failed");
    expect(within(web).getByTestId("step-times")).toHaveTextContent(
      `Started ${new Date("2026-10-06T10:00:05+00:00").toLocaleString()}, ` +
        `ended ${new Date("2026-10-06T10:01:05+00:00").toLocaleString()}`,
    );
    expect(within(web).getByTestId("step-error-message")).toHaveTextContent(
      "pod volume backup web-data failed: disk full",
    );
    expect(within(db).getByTestId("step-status")).toHaveTextContent(
      "Succeeded",
    );
    expect(within(db).getByTestId("step-duration")).toHaveTextContent("30s");
  });

  it("starts a completed backup's steps collapsed and expands them on click", async () => {
    await renderBackupsTab([makeBackup({ steps: COMPONENT_STEPS })]);

    const container = backupSteps("backup-1");
    expect(container).toHaveAttribute("data-expanded", "false");
    // Kept in the DOM while collapsed, but hidden.
    expect(stepRows(container)).toHaveLength(2);
    expect(within(container).getByTestId("step-list")).not.toBeVisible();

    await userEvent.click(
      within(container).getByRole("button", { name: "Steps (2)" }),
    );

    expect(container).toHaveAttribute("data-expanded", "true");
    expect(within(container).getByTestId("step-list")).toBeVisible();
  });

  it("names the failed restore step and its error, with each step's duration in order", async () => {
    await renderBackupsTab([makeBackup({ steps: COMPONENT_STEPS })], {
      "backup-1": [makeRestore({ steps: RESTORE_STEPS })],
    });

    const container = restoreSteps("restore-1");
    expect(container).toHaveAttribute("data-expanded", "true");
    const rows = stepRows(container);
    expect(rows.map((row) => row.getAttribute("data-step-key"))).toEqual([
      "restore:namespace",
      "restore:velero",
      "restore:recovery",
    ]);
    expect(
      rows.map((row) => within(row).getByTestId("step-name").textContent),
    ).toEqual([
      "Delete the namespace",
      "Run the Velero restore",
      "Run the recovery",
    ]);
    expect(
      rows.map(
        (row) => within(row).queryByTestId("step-duration")?.textContent,
      ),
    ).toEqual(["12s", "8s", undefined]);

    const failed = rows.filter(
      (row) => row.getAttribute("data-step-status") === "FAILED",
    );
    expect(failed).toHaveLength(1);
    expect(failed[0]).toBeVisible();
    expect(within(failed[0]).getByTestId("step-name")).toHaveTextContent(
      "Run the Velero restore",
    );
    expect(
      within(failed[0]).getByTestId("step-error-message"),
    ).toHaveTextContent(VELERO_ERROR);

    // The backup's own steps do not include the steps of its restores.
    expect(
      stepRows(backupSteps("backup-1")).map((row) =>
        row.getAttribute("data-step-key"),
      ),
    ).toEqual(["backup:component:web", "backup:component:db"]);
    expect(
      within(screen.getByTestId("restore-row")).getAllByTestId("step-row"),
    ).toHaveLength(3);
  });

  it("shows a notice for a backup and a restore that ran before steps were recorded", async () => {
    await renderBackupsTab([makeBackup()], {
      "backup-1": [makeRestore({ status: "completed" })],
    });

    for (const [container, notice] of [
      [backupSteps("backup-1"), "No steps recorded for this backup."],
      [restoreSteps("restore-1"), "No steps recorded for this restore."],
    ] as const) {
      expect(stepRows(container)).toHaveLength(0);
      await userEvent.click(
        within(container).getByRole("button", { name: "Steps (0)" }),
      );
      expect(within(container).getByTestId("steps-notice")).toHaveTextContent(
        notice,
      );
      expect(within(container).getByTestId("steps-notice")).toBeVisible();
    }
  });

  it("shows an in-progress backup without steps as waiting for its first step", async () => {
    await renderBackupsTab([makeBackup({ status: "in_progress" })]);

    const container = backupSteps("backup-1");
    expect(container).toHaveAttribute("data-expanded", "true");
    expect(within(container).getByTestId("steps-notice")).toHaveTextContent(
      "Waiting for the first step.",
    );
  });
});
