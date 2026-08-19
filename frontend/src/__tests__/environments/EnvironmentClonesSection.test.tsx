/**
 * EnvironmentClonesSection tests (010-environment-clone, US4).
 *
 * The section is the operator's only honest view of an asynchronous, partially
 * failable operation, so the tests centre on the three things that make it
 * trustworthy:
 *
 * - **Every derived status renders**, including `PARTIAL` and a `FAILED` that
 *   came from the *supported discard path* — deleting the environment the clone
 *   created. A discard dressed up as an unexpected error would teach operators
 *   to distrust the list.
 * - **100% attribution** (SC-003): every source deployment appears once, with
 *   its open-vocabulary reason rendered verbatim.
 * - **Polling stops when there is nothing left to converge to**, and never runs
 *   while the tab is inactive or page refresh is paused.
 *
 * The `data-*` attributes asserted here are the contract the Playwright
 * scenario driver reads, so they are tested as behaviour rather than left to
 * the E2E to discover.
 */
import type { ReactElement } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render as rtlRender, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  createRouter,
  createRootRoute,
  createRoute,
  createMemoryHistory,
  RouterProvider,
} from "@tanstack/react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ThemeProvider } from "@/hooks/use-theme";
import { AuthContext, type AuthContextValue } from "@/auth/AuthProvider";
import {
  EnvironmentClonesSection,
  cloneListRefetchInterval,
  formatCloneResultSummary,
  isCloneDiscarded,
  isCloneTerminal,
  relativeAge,
  summariseCloneResults,
} from "@/components/environment/EnvironmentClonesSection";

const useListEnvironmentClonesQuery = vi.fn();
const useGetEnvironmentCloneQuery = vi.fn();
const useCloneEnvironmentMutation = vi.fn();

vi.mock("@/generated/graphql", async () => {
  const actual = await vi.importActual<typeof import("@/generated/graphql")>(
    "@/generated/graphql",
  );
  return {
    ...actual,
    useListEnvironmentClonesQuery: (...args: unknown[]) =>
      useListEnvironmentClonesQuery(...args),
    useGetEnvironmentCloneQuery: (...args: unknown[]) =>
      useGetEnvironmentCloneQuery(...args),
    useCloneEnvironmentMutation: (...args: unknown[]) =>
      useCloneEnvironmentMutation(...args),
  };
});

const ENVIRONMENT_ID = "env-1";

function adminAuth(): AuthContextValue {
  return {
    currentUser: {
      id: "u-admin",
      username: "admin",
      displayName: "Admin",
      role: "ADMIN",
      effectiveRole: "ADMIN",
      active: true,
    },
    loading: false,
    refresh: () => Promise.resolve(),
    logout: () => Promise.resolve(),
  };
}

function readWriteAuth(): AuthContextValue {
  return {
    currentUser: {
      id: "u-rw",
      username: "operator",
      displayName: "Operator",
      role: "READ_WRITE",
      effectiveRole: "READ_WRITE",
      active: true,
    },
    loading: false,
    refresh: () => Promise.resolve(),
    logout: () => Promise.resolve(),
  };
}

/**
 * Render with a router that actually carries the environment and deployment
 * routes the section links to.
 *
 * The shared `@/test/utils` helper registers only `/`, and a `<Link>` to an
 * unregistered route cannot resolve — the created-environment and counterpart
 * links are part of what this section is for, so the routes are declared here
 * (same approach as `DeploymentRow.test.tsx`).
 */
async function renderSection(ui: ReactElement, auth = adminAuth()) {
  const rootRoute = createRootRoute();
  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/",
    component: () => ui,
  });
  const environmentRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/environments/$environmentId",
    component: () => <div>environment detail</div>,
  });
  const deploymentRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/environments/$environmentId/deployments/$deploymentId",
    component: () => <div>deployment detail</div>,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([
      indexRoute,
      environmentRoute,
      deploymentRoute,
    ]),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });

  return rtlRender(
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <AuthContext.Provider value={auth}>
          <RouterProvider router={router} />
        </AuthContext.Provider>
      </QueryClientProvider>
    </ThemeProvider>,
  );
}

function listResult(
  environmentClones: unknown[],
  overrides: Record<string, unknown> = {},
) {
  return {
    data: { environmentClones },
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  };
}

function result(
  deploymentName: string,
  outcome: string,
  overrides: Record<string, unknown> = {},
) {
  return {
    deploymentId: `dep-${deploymentName}`,
    deploymentName,
    outcome,
    reason: null,
    ...overrides,
  };
}

function clone(overrides: Record<string, unknown> = {}) {
  return {
    id: "clone-1",
    name: "prod-rehearsal",
    status: "COMPLETED",
    sourceEnvironmentName: "prod",
    createdOn: new Date(Date.now() - 5 * 60_000).toISOString(),
    updatedOn: null,
    cloneErrors: [],
    createdEnvironment: { id: "env-2", name: "prod-rehearsal" },
    environmentBackup: {
      id: "envbackup-1",
      name: "clone-capture",
      status: "COMPLETED",
    },
    deploymentResults: [result("api", "CLONED")],
    ...overrides,
  };
}

function detail(overrides: Record<string, unknown> = {}) {
  return {
    ...clone(),
    requestedDeploymentIds: null,
    configOverride: null,
    clearConfigFields: null,
    sourceEnvironment: { id: ENVIRONMENT_ID, name: "prod" },
    deploymentResults: [
      result("api", "CLONED", {
        counterpartDeploymentId: "dep-api-clone",
        restoreId: "restore-1",
      }),
    ],
    ...overrides,
  };
}

function renderClones(
  clones: unknown[],
  props: { isActive?: boolean; autoRefreshEnabled?: boolean } = {},
  auth = adminAuth(),
) {
  useListEnvironmentClonesQuery.mockReturnValue(listResult(clones));
  return renderSection(
    <EnvironmentClonesSection
      environmentId={ENVIRONMENT_ID}
      environmentName="prod"
      deployments={[]}
      config={null}
      isActive={props.isActive ?? true}
      autoRefreshEnabled={props.autoRefreshEnabled ?? true}
    />,
    auth,
  );
}

describe("summariseCloneResults / formatCloneResultSummary", () => {
  it("buckets every outcome, treating an unknown one as still pending", () => {
    // `PENDING` is the transient value between registration and the step
    // landing; anything the frontend does not recognise is not yet an outcome.
    const summary = summariseCloneResults([
      { outcome: "CLONED" },
      { outcome: "SKIPPED" },
      { outcome: "FAILED" },
      { outcome: "PENDING" },
      { outcome: "SOMETHING_NEW" },
    ]);
    expect(summary).toEqual({
      total: 5,
      cloned: 1,
      skipped: 1,
      failed: 1,
      pending: 2,
    });
  });

  it("spells out every non-cloned bucket so PARTIAL says why", () => {
    expect(
      formatCloneResultSummary({
        total: 4,
        cloned: 1,
        skipped: 1,
        failed: 1,
        pending: 1,
      }),
    ).toBe("1/4 cloned · 1 skipped, 1 failed, 1 pending");
  });

  it("reads a clean clone as a bare ratio", () => {
    expect(
      formatCloneResultSummary({
        total: 2,
        cloned: 2,
        skipped: 0,
        failed: 0,
        pending: 0,
      }),
    ).toBe("2/2 cloned");
  });

  it("labels a clone with no applications as config only", () => {
    expect(
      formatCloneResultSummary({
        total: 0,
        cloned: 0,
        skipped: 0,
        failed: 0,
        pending: 0,
      }),
    ).toBe("Config only");
  });
});

describe("isCloneTerminal", () => {
  it("treats COMPLETED, PARTIAL and FAILED as terminal", () => {
    expect(isCloneTerminal("COMPLETED")).toBe(true);
    expect(isCloneTerminal("PARTIAL")).toBe(true);
    expect(isCloneTerminal("FAILED")).toBe(true);
    expect(isCloneTerminal("PENDING")).toBe(false);
    // A clone can arrive already IN_PROGRESS — an upfront skip counts as
    // recorded progress — so this branch is reachable straight after creation.
    expect(isCloneTerminal("IN_PROGRESS")).toBe(false);
  });
});

describe("isCloneDiscarded", () => {
  it("recognises the created-environment deletion event", () => {
    expect(
      isCloneDiscarded([
        "created_environment_deleted: environment prod-rehearsal was deleted",
      ]),
    ).toBe(true);
  });

  it("does not mistake another event for a discard", () => {
    // A deleted *backup* is a different escape hatch and must not read as a
    // discarded clone.
    expect(
      isCloneDiscarded(["environment_backup_deleted: capture was deleted"]),
    ).toBe(false);
    expect(isCloneDiscarded([])).toBe(false);
  });
});

describe("cloneListRefetchInterval", () => {
  const nonTerminal = [{ status: "IN_PROGRESS" as const }];
  const terminal = [{ status: "COMPLETED" as const }];

  it("polls while a clone can still move", () => {
    expect(
      cloneListRefetchInterval({
        isActive: true,
        autoRefreshEnabled: true,
        clones: nonTerminal,
      }),
    ).toBe(10_000);
  });

  it("stops once every clone is terminal", () => {
    expect(
      cloneListRefetchInterval({
        isActive: true,
        autoRefreshEnabled: true,
        clones: terminal,
      }),
    ).toBe(false);
  });

  it("stops while the tab is inactive or refresh is paused", () => {
    expect(
      cloneListRefetchInterval({
        isActive: false,
        autoRefreshEnabled: true,
        clones: nonTerminal,
      }),
    ).toBe(false);
    expect(
      cloneListRefetchInterval({
        isActive: true,
        autoRefreshEnabled: false,
        clones: nonTerminal,
      }),
    ).toBe(false);
  });

  it("does not poll before any data has arrived", () => {
    // The first fetch is driven by `enabled`, not by the interval.
    expect(
      cloneListRefetchInterval({
        isActive: true,
        autoRefreshEnabled: true,
        clones: undefined,
      }),
    ).toBe(false);
  });
});

describe("relativeAge", () => {
  it("degrades through seconds, minutes, hours and days", () => {
    const now = Date.now();
    expect(relativeAge(new Date(now - 5_000).toISOString())).toBe("5s ago");
    expect(relativeAge(new Date(now - 5 * 60_000).toISOString())).toBe(
      "5m ago",
    );
    expect(relativeAge(new Date(now - 5 * 3_600_000).toISOString())).toBe(
      "5h ago",
    );
    expect(relativeAge(new Date(now - 3 * 86_400_000).toISOString())).toBe(
      "3d ago",
    );
  });

  it("returns nothing for an unparseable timestamp", () => {
    expect(relativeAge("not-a-date")).toBe("");
  });
});

describe("EnvironmentClonesSection", () => {
  beforeEach(() => {
    useListEnvironmentClonesQuery.mockReset();
    useGetEnvironmentCloneQuery.mockReset();
    useGetEnvironmentCloneQuery.mockReturnValue({
      data: { environmentClone: detail() },
      isLoading: false,
      isError: false,
      error: null,
    });
    useCloneEnvironmentMutation.mockReset();
    useCloneEnvironmentMutation.mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
    });
  });

  it("renders the empty state when nothing has been cloned yet", async () => {
    await renderClones([]);

    expect(screen.getByTestId("environment-clones-empty")).toHaveTextContent(
      /no clones of this environment yet/i,
    );
    expect(
      screen.queryByTestId("environment-clone-row"),
    ).not.toBeInTheDocument();
    // The action is still offered — an environment with nothing cloned yet is
    // exactly where the operator starts.
    expect(screen.getByTestId("clone-environment-button")).toBeInTheDocument();
  });

  it("gates the clone action behind the ADMIN role", async () => {
    // FR-010. A READ_WRITE operator still sees the history.
    await renderClones([clone()], {}, readWriteAuth());

    expect(
      screen.queryByTestId("clone-environment-button"),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("environment-clone-row")).toBeInTheDocument();
  });

  it("renders one row per clone with its identity and derived status", async () => {
    await renderClones([
      clone(),
      clone({
        id: "clone-2",
        name: "prod-partial",
        status: "PARTIAL",
        createdEnvironment: { id: "env-3", name: "prod-partial" },
        deploymentResults: [
          result("api", "CLONED"),
          result("worker", "FAILED", { reason: "driver_version_gone" }),
          result("cache", "SKIPPED", { reason: "not_selected" }),
        ],
      }),
    ]);

    const rows = screen.getAllByTestId("environment-clone-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute("data-environment-clone-id", "clone-1");
    expect(rows[0]).toHaveAttribute(
      "data-environment-clone-name",
      "prod-rehearsal",
    );
    // Raw enum value, not the humanised badge label: the UI scenario driver
    // must report the same string the API driver reads off GraphQL.
    expect(rows[0]).toHaveAttribute(
      "data-environment-clone-status",
      "COMPLETED",
    );
    expect(rows[0]).toHaveAttribute("data-created-environment-id", "env-2");
    expect(rows[0]).toHaveAttribute(
      "data-environment-backup-id",
      "envbackup-1",
    );

    expect(rows[1]).toHaveAttribute("data-environment-clone-status", "PARTIAL");
    expect(rows[1]).toHaveAttribute("data-result-total", "3");
    expect(rows[1]).toHaveAttribute("data-result-cloned", "1");
    expect(rows[1]).toHaveAttribute("data-result-failed", "1");
    expect(rows[1]).toHaveAttribute("data-result-skipped", "1");
    expect(
      within(rows[1]).getByTestId("environment-clone-applications"),
    ).toHaveTextContent("1/3 cloned · 1 skipped, 1 failed");
  });

  it("shows a humanised badge for every derived status", async () => {
    await renderClones([
      clone({ id: "c1", status: "PENDING" }),
      clone({ id: "c2", status: "IN_PROGRESS" }),
      clone({ id: "c3", status: "COMPLETED" }),
      clone({ id: "c4", status: "PARTIAL" }),
      clone({ id: "c5", status: "FAILED" }),
    ]);

    expect(
      screen
        .getAllByTestId("environment-clone-status")
        .map((cell) => cell.textContent),
    ).toEqual(["Pending", "In Progress", "Complete", "Partial", "Failed"]);
  });

  it("links to the environment a clone created", async () => {
    await renderClones([clone()]);

    const link = screen.getByTestId("environment-clone-environment-link");
    expect(link).toHaveTextContent("prod-rehearsal");
    expect(link).toHaveAttribute("href", "/environments/env-2");
  });

  it("distinguishes a not-yet-created environment from a discarded one", async () => {
    await renderClones([
      clone({
        id: "clone-pending",
        status: "IN_PROGRESS",
        createdEnvironment: null,
        deploymentResults: [],
      }),
    ]);

    expect(
      screen.getByTestId("environment-clone-environment-pending"),
    ).toHaveTextContent(/not created yet/i);
    expect(
      screen.queryByTestId("environment-clone-discarded"),
    ).not.toBeInTheDocument();
  });

  it("presents a discarded clone as discarded, not as an unexpected failure", async () => {
    // Deleting the created environment is the documented discard path (SC-005)
    // and it drives the clone FAILED. Rendering that as a bare failure would
    // make a deliberate operator action look like a malfunction.
    await renderClones([
      clone({
        status: "FAILED",
        createdEnvironment: null,
        cloneErrors: [
          "created_environment_deleted: environment prod-rehearsal was deleted",
        ],
      }),
    ]);

    const row = screen.getByTestId("environment-clone-row");
    expect(row).toHaveAttribute("data-environment-clone-discarded", "true");
    expect(
      within(row).getByTestId("environment-clone-discarded"),
    ).toHaveTextContent("Discarded");
    expect(
      within(row).getByTestId("environment-clone-discard-note"),
    ).toHaveTextContent(/supported way to discard a clone/i);
  });

  it("shows the createdOn-relative age", async () => {
    await renderClones([
      clone({ createdOn: new Date(Date.now() - 2 * 3_600_000).toISOString() }),
    ]);

    expect(screen.getByTestId("environment-clone-age")).toHaveTextContent(
      "2h ago",
    );
  });

  it("accounts for every source deployment when a row is expanded", async () => {
    // SC-003: the reason vocabulary is open-ended, so it is rendered verbatim
    // rather than mapped through a table that would drop unknown values.
    useGetEnvironmentCloneQuery.mockReturnValue({
      data: {
        environmentClone: detail({
          status: "PARTIAL",
          deploymentResults: [
            result("api", "CLONED", {
              counterpartDeploymentId: "dep-api-clone",
              restoreId: "restore-1",
            }),
            result("worker", "FAILED", {
              reason: "driver_version_gone",
              counterpartDeploymentId: null,
              restoreId: null,
            }),
            result("cache", "SKIPPED", {
              reason: "a reason the frontend has never seen",
              counterpartDeploymentId: null,
              restoreId: null,
            }),
          ],
        }),
      },
      isLoading: false,
      isError: false,
      error: null,
    });
    await renderClones([clone()]);

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-clone-expand-button"));

    const entries = screen.getAllByTestId("environment-clone-result");
    expect(entries).toHaveLength(3);
    expect(entries[0]).toHaveAttribute("data-outcome", "CLONED");
    expect(entries[0]).toHaveAttribute(
      "data-counterpart-deployment-id",
      "dep-api-clone",
    );
    expect(entries[0]).toHaveAttribute("data-restore-id", "restore-1");
    expect(entries[1]).toHaveAttribute("data-outcome", "FAILED");
    expect(entries[1]).toHaveAttribute("data-reason", "driver_version_gone");
    expect(entries[2]).toHaveAttribute("data-outcome", "SKIPPED");
    expect(entries[2]).toHaveTextContent(
      "a reason the frontend has never seen",
    );
  });

  it("links a cloned application to its counterpart deployment", async () => {
    await renderClones([clone()]);

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-clone-expand-button"));

    expect(
      screen.getByTestId("environment-clone-counterpart-link"),
    ).toHaveAttribute("href", "/environments/env-2/deployments/dep-api-clone");
  });

  it("shows a counterpart whose environment is gone as history, not a dead link", async () => {
    useGetEnvironmentCloneQuery.mockReturnValue({
      data: {
        environmentClone: detail({
          status: "FAILED",
          createdEnvironment: null,
          cloneErrors: ["created_environment_deleted: discarded"],
        }),
      },
      isLoading: false,
      isError: false,
      error: null,
    });
    await renderClones([
      clone({
        status: "FAILED",
        createdEnvironment: null,
        cloneErrors: ["created_environment_deleted: discarded"],
      }),
    ]);

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-clone-expand-button"));

    expect(
      screen.queryByTestId("environment-clone-counterpart-link"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("environment-clone-counterpart-gone"),
    ).toHaveTextContent("dep-api-clone");
  });

  it("renders provenance from the surviving name once the source is gone", async () => {
    useGetEnvironmentCloneQuery.mockReturnValue({
      data: {
        environmentClone: detail({
          sourceEnvironment: null,
          sourceEnvironmentName: "prod",
        }),
      },
      isLoading: false,
      isError: false,
      error: null,
    });
    await renderClones([clone()]);

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-clone-expand-button"));

    expect(screen.getByTestId("environment-clone-source")).toHaveTextContent(
      "prod (deleted)",
    );
  });

  it("shows the request that produced the clone", async () => {
    useGetEnvironmentCloneQuery.mockReturnValue({
      data: {
        environmentClone: detail({
          requestedDeploymentIds: ["dep-api"],
          configOverride: { envVars: [{ name: "SMTP_HOST", value: "sink" }] },
          clearConfigFields: ["ingress_class"],
        }),
      },
      isLoading: false,
      isError: false,
      error: null,
    });
    await renderClones([clone()]);

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-clone-expand-button"));

    expect(
      screen.getByTestId("environment-clone-requested-deployments"),
    ).toHaveTextContent("1 selected");
    expect(
      screen.getByTestId("environment-clone-config-override"),
    ).toHaveTextContent("SMTP_HOST");
    expect(
      screen.getByTestId("environment-clone-clear-fields"),
    ).toHaveTextContent("ingress_class");
  });

  it("distinguishes an omitted selection from an explicitly empty one", async () => {
    // `null` means every eligible deployment (FR-003); `[]` means the operator
    // asked for a configuration-only clone.
    useGetEnvironmentCloneQuery.mockReturnValue({
      data: { environmentClone: detail({ requestedDeploymentIds: [] }) },
      isLoading: false,
      isError: false,
      error: null,
    });
    await renderClones([clone()]);

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-clone-expand-button"));

    expect(
      screen.getByTestId("environment-clone-requested-deployments"),
    ).toHaveTextContent("none (configuration only)");
  });

  it("lists the operation-level events verbatim", async () => {
    useGetEnvironmentCloneQuery.mockReturnValue({
      data: {
        environmentClone: detail({
          status: "FAILED",
          cloneErrors: ["capture: environment backup failed"],
        }),
      },
      isLoading: false,
      isError: false,
      error: null,
    });
    await renderClones([clone({ status: "FAILED" })]);

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-clone-expand-button"));

    expect(
      screen.getByTestId("environment-clone-error-entry"),
    ).toHaveTextContent("capture: environment backup failed");
  });

  it("names the backing capture behind the expand toggle", async () => {
    await renderClones([clone()]);

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-clone-expand-button"));

    expect(screen.getByTestId("environment-clone-backup")).toHaveTextContent(
      "clone-capture",
    );
  });

  it("reports a capture that is no longer available", async () => {
    await renderClones([clone({ environmentBackup: null })]);

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-clone-expand-button"));

    expect(screen.getByTestId("environment-clone-backup")).toHaveTextContent(
      /no longer available/i,
    );
  });

  it("fetches an expanded clone's detail only while it is expanded", async () => {
    await renderClones([clone()]);

    expect(useGetEnvironmentCloneQuery).toHaveBeenLastCalledWith(
      { environmentCloneId: "clone-1" },
      expect.objectContaining({ enabled: false, refetchInterval: false }),
    );

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-clone-expand-button"));

    expect(useGetEnvironmentCloneQuery).toHaveBeenLastCalledWith(
      { environmentCloneId: "clone-1" },
      // Terminal clone: nothing left to converge to, so no interval.
      expect.objectContaining({ enabled: true, refetchInterval: false }),
    );
  });

  it("polls an expanded non-terminal clone's detail", async () => {
    await renderClones([clone({ status: "IN_PROGRESS" })]);

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-clone-expand-button"));

    expect(useGetEnvironmentCloneQuery).toHaveBeenLastCalledWith(
      { environmentCloneId: "clone-1" },
      expect.objectContaining({ enabled: true, refetchInterval: 10_000 }),
    );
  });

  it("stops the expanded detail poll when page refresh is paused", async () => {
    await renderClones([clone({ status: "IN_PROGRESS" })], {
      autoRefreshEnabled: false,
    });

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-clone-expand-button"));

    expect(useGetEnvironmentCloneQuery).toHaveBeenLastCalledWith(
      { environmentCloneId: "clone-1" },
      expect.objectContaining({ enabled: true, refetchInterval: false }),
    );
  });

  it("does not fetch the list at all while the tab is inactive", async () => {
    await renderClones([], { isActive: false });

    expect(useListEnvironmentClonesQuery).toHaveBeenCalledWith(
      { environmentId: ENVIRONMENT_ID },
      expect.objectContaining({ enabled: false }),
    );
  });

  it("shows a retryable error state when the list query fails", async () => {
    const refetch = vi.fn();
    useListEnvironmentClonesQuery.mockReturnValue(
      listResult([], {
        data: undefined,
        isError: true,
        error: new Error("network down"),
        refetch,
      }),
    );

    await renderSection(
      <EnvironmentClonesSection
        environmentId={ENVIRONMENT_ID}
        environmentName="prod"
        deployments={[]}
        config={null}
        isActive
        autoRefreshEnabled
      />,
    );

    expect(screen.getByText(/network down/i)).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(refetch).toHaveBeenCalled();
  });
});
