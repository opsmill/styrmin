/**
 * Task results and task links (spec 019-task-steps, US3): the timeline and
 * the Overview show the task result instead of `Task.status`, hook-started
 * tasks link to the task that started them, superseded steps link to the
 * later task, and hook steps list the tasks they started.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  render as rtlRender,
  act,
  screen as rtlScreen,
  within as rtlWithin,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { render, screen, userEvent, within } from "@/test/utils";
import { AuthContext, type AuthContextValue } from "@/auth/AuthProvider";
import { ThemeProvider } from "@/hooks/use-theme";
import {
  DeploymentTimeline,
  type TimelineEntry,
} from "@/components/deployment/DeploymentTimeline";
import { TaskResultBadge } from "@/components/deployment/TaskResultBadge";
import type { StepListItem } from "@/components/deployment/StepList";
import DeploymentDetailPage from "@/pages/deployments/DeploymentDetailPage";
import type { GetDeploymentQuery, TaskResult } from "@/generated/graphql";

const useGetDeploymentQueryMock = vi.fn();
const useGetDeploymentTimelineQueryMock = vi.fn();
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
    useGetDeploymentTimelineQuery: (...args: unknown[]) =>
      useGetDeploymentTimelineQueryMock(...args),
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

const UPGRADE_ID = "task-upgrade";
const HOOK_STEP_ID = "step-hook";

function makeStep(overrides: Partial<StepListItem> = {}): StepListItem {
  return {
    id: "step-1",
    key: "plan",
    name: "Plan the changes",
    kind: "PLAN",
    status: "SUCCEEDED",
    startedAt: "2026-10-06T10:00:00+00:00",
    endedAt: "2026-10-06T10:00:02+00:00",
    durationSeconds: 2,
    attemptCount: 1,
    hasOutput: false,
    ...overrides,
  };
}

function makeEntry(
  overrides: Partial<TimelineEntry["task"]> = {},
): TimelineEntry {
  return {
    task: {
      id: "task-1",
      type: "update_instance",
      status: "success",
      message: null,
      createdOn: "2026-10-06T10:00:00+00:00",
      updatedOn: "2026-10-06T10:00:30+00:00",
      result: "SUCCEEDED",
      startedByStepId: null,
      startedBy: null,
      startedTasks: [],
      steps: [makeStep()],
      ...overrides,
    },
    applicationVersion: "1.2.0",
    contextDiff: null,
  };
}

const STARTED_TASKS = [
  { id: "task-stop", type: "stop_components", result: "SUCCEEDED" as const },
  {
    id: "task-version",
    type: "upgrade_instance",
    result: "SUPERSEDED" as const,
  },
  { id: "task-start", type: "start_components", result: "FAILED" as const },
];

// An upgrade whose hook step started three tasks, newest entry first.
function upgradeFamily(): TimelineEntry[] {
  const startedEntries = STARTED_TASKS.map((started) =>
    makeEntry({
      id: started.id,
      type: started.type,
      result: started.result,
      startedByStepId: HOOK_STEP_ID,
      startedBy: { id: UPGRADE_ID, type: "upgrade_instance" },
      steps: [makeStep({ id: `${started.id}-step` })],
    }),
  ).reverse();
  return [
    ...startedEntries,
    makeEntry({
      id: UPGRADE_ID,
      type: "upgrade_instance",
      result: "FAILED",
      startedTasks: STARTED_TASKS,
      steps: [
        makeStep({
          id: HOOK_STEP_ID,
          key: "hook:pre-upgrade",
          name: "Run the pre-upgrade hook",
          kind: "HOOK",
          startedTasks: STARTED_TASKS,
        }),
      ],
    }),
  ];
}

function entryById(taskId: string): HTMLElement {
  const entry = screen
    .getAllByTestId("timeline-entry")
    .find((element) => element.getAttribute("data-task-id") === taskId);
  if (!entry) throw new Error(`no timeline entry for task ${taskId}`);
  return entry;
}

const scrollIntoView = vi.fn();

beforeEach(() => {
  // jsdom does not implement scrolling.
  scrollIntoView.mockReset();
  Element.prototype.scrollIntoView = scrollIntoView;
});

afterEach(() => {
  delete (Element.prototype as Partial<Element>).scrollIntoView;
});

describe("TaskResultBadge", () => {
  it.each<[TaskResult, string]>([
    ["RUNNING", "Running"],
    ["FAILED", "Failed"],
    ["SUCCEEDED", "Succeeded"],
    ["SUPERSEDED", "Superseded"],
  ])("shows %s as %s", async (result, label) => {
    await render(<TaskResultBadge result={result} />);

    const badge = screen.getByTestId("task-result-badge");
    expect(badge).toHaveTextContent(label);
    expect(badge).toHaveAttribute("data-task-result", result);
  });
});

describe("DeploymentTimeline task results", () => {
  it("shows the task result instead of the Prefect flow status", async () => {
    await render(
      <DeploymentTimeline
        entries={[makeEntry({ status: "success", result: "FAILED" })]}
      />,
    );

    const entry = entryById("task-1");
    expect(entry).toHaveAttribute("data-task-result", "FAILED");
    expect(entry).toHaveAttribute("data-task-status", "success");
    expect(within(entry).getByTestId("task-result-badge")).toHaveTextContent(
      "Failed",
    );
    expect(within(entry).queryByText("Success")).not.toBeInTheDocument();
  });

  it("links a started task back to the task that started it", async () => {
    const user = userEvent.setup();
    await render(<DeploymentTimeline entries={upgradeFamily()} />);

    const started = entryById("task-start");
    expect(started).toHaveAttribute("data-started-by-task-id", UPGRADE_ID);
    expect(started).toHaveAttribute(
      "data-started-by-task-type",
      "upgrade_instance",
    );
    // A FAILED entry starts expanded; collapse it so the link must expand it.
    const upgrade = entryById(UPGRADE_ID);
    expect(upgrade).toHaveAttribute("data-expanded", "true");
    await user.click(within(upgrade).getByTestId("timeline-entry-trigger"));
    expect(upgrade).toHaveAttribute("data-expanded", "false");

    await user.click(
      within(started).getByRole("link", { name: "Started by Upgrade" }),
    );

    expect(upgrade).toHaveAttribute("data-expanded", "true");
    expect(within(upgrade).getByTestId("step-list")).toBeVisible();
    expect(within(upgrade).getByTestId("timeline-entry-trigger")).toHaveFocus();
    expect(scrollIntoView).toHaveBeenCalledOnce();
    expect(scrollIntoView.mock.contexts[0]).toBe(upgrade);
  });

  it("shows a link whose task is not in the timeline as text", async () => {
    await render(
      <DeploymentTimeline
        entries={[
          makeEntry({
            id: "task-start",
            type: "start_components",
            startedByStepId: "step-elsewhere",
            startedBy: { id: "task-elsewhere", type: "upgrade_instance" },
          }),
        ]}
      />,
    );

    const startedBy = within(entryById("task-start")).getByTestId("started-by");
    expect(startedBy).toHaveTextContent("Started by Upgrade");
    expect(within(startedBy).queryByRole("link")).not.toBeInTheDocument();
    expect(within(startedBy).getByTestId("task-link")).toHaveAttribute(
      "data-link-target",
      "missing",
    );
  });

  it("lists the tasks a hook step started with their results and links", async () => {
    const user = userEvent.setup();
    await render(<DeploymentTimeline entries={upgradeFamily()} />);

    const upgrade = entryById(UPGRADE_ID);
    expect(upgrade).toHaveAttribute("data-task-result", "FAILED");
    const hookRow = within(upgrade).getByTestId("step-row");
    const items = within(hookRow).getAllByTestId("started-task");
    expect(
      items.map((item) => [
        item.getAttribute("data-task-id"),
        item.getAttribute("data-task-type"),
        item.getAttribute("data-task-result"),
      ]),
    ).toEqual(STARTED_TASKS.map((task) => [task.id, task.type, task.result]));
    expect(within(items[0]).getByTestId("task-result-badge")).toHaveTextContent(
      "Succeeded",
    );
    expect(within(items[1]).getByTestId("task-result-badge")).toHaveTextContent(
      "Superseded",
    );
    expect(within(items[2]).getByTestId("task-result-badge")).toHaveTextContent(
      "Failed",
    );

    // FAILED entries start expanded, so the hook step's links are visible.
    expect(upgrade).toHaveAttribute("data-expanded", "true");
    await user.click(
      within(items[2]).getByRole("link", { name: "Start Components" }),
    );

    expect(entryById("task-start")).toHaveAttribute("data-expanded", "true");
    expect(
      within(entryById("task-start")).getByTestId("timeline-entry-trigger"),
    ).toHaveFocus();
  });

  it("links a superseded step to the task that superseded it", async () => {
    const user = userEvent.setup();
    await render(
      <DeploymentTimeline
        entries={[
          makeEntry({ id: "task-second", type: "update_instance" }),
          makeEntry({
            id: "task-first",
            type: "upgrade_instance",
            result: "SUPERSEDED",
            steps: [
              makeStep({
                id: "step-phase",
                key: "phase:helmrelease",
                name: "Install or upgrade the HelmRelease",
                kind: "OPERATOR_PHASE",
                status: "SUPERSEDED",
                supersededBy: { id: "task-second", type: "update_instance" },
              }),
            ],
          }),
        ]}
      />,
    );

    const first = entryById("task-first");
    expect(first).toHaveAttribute("data-task-result", "SUPERSEDED");
    const row = within(first).getByTestId("step-row");
    expect(row).toHaveAttribute("data-superseded-by-task-id", "task-second");
    const second = entryById("task-second");
    expect(second).toHaveAttribute("data-expanded", "false");

    await user.click(within(first).getByTestId("timeline-entry-trigger"));
    await user.click(
      within(row).getByRole("link", { name: "Superseded by Update" }),
    );

    expect(second).toHaveAttribute("data-expanded", "true");
    expect(scrollIntoView.mock.contexts[0]).toBe(second);
  });

  it("shows no links on a step that was not superseded and started nothing", async () => {
    await render(<DeploymentTimeline entries={[makeEntry()]} />);

    const row = within(entryById("task-1")).getByTestId("step-row");
    expect(row).toHaveAttribute("data-superseded-by-task-id", "");
    expect(
      within(row).queryByTestId("step-superseded-by"),
    ).not.toBeInTheDocument();
    expect(within(row).queryByTestId("started-tasks")).not.toBeInTheDocument();
  });
});

describe("DeploymentDetailPage Overview", () => {
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
      podStatuses: [],
      deployedServices: [],
    } as NonNullable<GetDeploymentQuery["deployment"]>;
  }

  const auth: AuthContextValue = {
    currentUser: {
      id: "user-ro",
      username: "ro-user",
      displayName: "RO User",
      role: "READ_ONLY",
      effectiveRole: "READ_ONLY",
      active: true,
    },
    loading: false,
    refresh: () => Promise.resolve(),
    logout: () => Promise.resolve(),
  };

  async function renderPage() {
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
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: Infinity } },
    });
    await act(async () => {
      rtlRender(
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <AuthContext.Provider value={auth}>
              <RouterProvider router={router} />
            </AuthContext.Provider>
          </QueryClientProvider>
        </ThemeProvider>,
      );
    });
  }

  it("shows each recent task's result, as the timeline does", async () => {
    useGetDeploymentQueryMock.mockReturnValue({
      ...noopQueryResult,
      data: { deployment: makeDeployment() },
      dataUpdatedAt: Date.now(),
    });
    useGetDeploymentTimelineQueryMock.mockReturnValue({
      ...noopQueryResult,
      data: {
        deploymentTimeline: [
          makeEntry({ id: "task-new", status: "success", result: "FAILED" }),
          makeEntry({
            id: "task-old",
            status: "failed",
            result: "SUPERSEDED",
          }),
        ],
      },
    });

    await renderPage();

    const recent = await rtlScreen.findAllByTestId("recent-timeline-entry");
    expect(
      recent.map((item) => [
        item.getAttribute("data-task-id"),
        item.getAttribute("data-task-result"),
        rtlWithin(item).getByTestId("task-result-badge").textContent,
      ]),
    ).toEqual([
      ["task-new", "FAILED", "Failed"],
      ["task-old", "SUPERSEDED", "Superseded"],
    ]);
  });

  it("refreshes the timeline every 10 seconds (US4, FR-005)", async () => {
    useGetDeploymentQueryMock.mockReturnValue({
      ...noopQueryResult,
      data: { deployment: makeDeployment() },
      dataUpdatedAt: Date.now(),
    });
    useGetDeploymentTimelineQueryMock.mockReturnValue({
      ...noopQueryResult,
      data: { deploymentTimeline: [] },
    });

    await renderPage();

    expect(useGetDeploymentTimelineQueryMock).toHaveBeenLastCalledWith(
      { deploymentId: "dep-1" },
      { refetchInterval: 10_000 },
    );
  });
});
