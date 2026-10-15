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
import type { GetDeploymentQuery, ListBackupsQuery } from "@/generated/graphql";

type BackupItem = ListBackupsQuery["backups"][number];

const EXPIRES_AT = "2026-11-01T12:04:06+00:00";
// The list's fetch time, which the page judges expiry against.
const LISTED_AT = Date.parse("2026-10-09T12:00:00+00:00");

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

function makeDeployment(
  overrides: Partial<DeploymentShape> = {},
): DeploymentShape {
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
    componentContainerOverrides: [],
    deployedServices: [],
    ...overrides,
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
    instance: { id: "inst-1", applicationVersion: "2.5.0" },
    steps: [],
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
async function renderBackupsTab(
  backups: BackupItem[],
  deployment: DeploymentShape = makeDeployment(),
  listResult?: Record<string, unknown>,
) {
  useGetDeploymentQueryMock.mockReturnValue({
    data: { deployment } as GetDeploymentQuery,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    dataUpdatedAt: Date.now(),
  });
  // A disabled query returns no data, as TanStack Query does.
  useListBackupsQueryMock.mockImplementation(
    (_variables: unknown, options?: { enabled?: boolean }) =>
      options?.enabled === false
        ? noopQueryResult
        : (listResult ?? {
            ...noopQueryResult,
            data: { backups } as ListBackupsQuery,
            dataUpdatedAt: LISTED_AT,
          }),
  );

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
      makeBackup({
        id: "backup-2",
        name: "backup-2",
        ttl: null,
        expiresAt: null,
      }),
    ]);

    const cell = screen.getByTestId("backup-expires");
    expect(cell.textContent).toContain("—");
    expect(cell.getAttribute("title")).toBeNull();
  });

  it("renders an em-dash rather than 'Invalid Date' for an unparseable expiry", async () => {
    // `new Date("not-a-timestamp")` never throws — it yields an Invalid Date
    // whose toLocaleDateString() is the literal string "Invalid Date". A
    // corrupt stored value must read as "unknown", not leak the JS artefact.
    await renderBackupsTab([makeBackup({ expiresAt: "not-a-timestamp" })]);

    const cell = screen.getByTestId("backup-expires");
    expect(cell.textContent).not.toContain("Invalid Date");
    expect(cell.textContent).toContain("—");
  });

  it("keeps the TTL hint when a failed backup never got an expiry", async () => {
    // The real shape of a backup Velero accepted but never completed: the
    // requested `ttl` was recorded at creation, but no `expiresAt` was ever
    // computed because nothing was stored to expire. The em-dash case above
    // nulls *both* fields, so it cannot catch a regression that ties the
    // retention hint to the presence of an expiry date — an operator
    // diagnosing the failure would silently lose the one field that says
    // which policy was applied.
    await renderBackupsTab([
      makeBackup({
        id: "backup-failed",
        name: "backup-failed",
        status: "failed",
        completedAt: null,
        sizeBytes: null,
        errorMessage: "backup storage location unavailable",
        ttl: "2160h",
        expiresAt: null,
      }),
    ]);

    const cell = screen.getByTestId("backup-expires");
    // No expiry to render...
    expect(cell.textContent).toContain("—");
    expect(cell.textContent).not.toContain("Invalid Date");
    // ...but the applied retention survives in both the tooltip and the
    // accessibility tree.
    expect(cell.getAttribute("title")).toContain("2160h");
    expect(cell.textContent).toContain("2160h");
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

describe("DeploymentDetailPage backups tab backup history (#304)", () => {
  beforeEach(() => {
    useGetDeploymentQueryMock.mockReset();
    useListBackupsQueryMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("lists the backups by the deployment id from the route", async () => {
    await renderBackupsTab([makeBackup()]);

    expect(useListBackupsQueryMock).toHaveBeenCalledWith(
      { deploymentId: "dep-1" },
      expect.not.objectContaining({ enabled: false }),
    );
    for (const [variables] of useListBackupsQueryMock.mock.calls) {
      expect(variables).toEqual({ deploymentId: "dep-1" });
    }
  });

  it("lists the backup history when the deployment has no active instance", async () => {
    await renderBackupsTab(
      [
        makeBackup({
          id: "backup-old",
          name: "backup-old",
          instance: { id: "inst-0", applicationVersion: "2.4.0" },
        }),
      ],
      makeDeployment({ applicationInstance: null }),
    );

    for (const [, options] of useListBackupsQueryMock.mock.calls) {
      expect(options).not.toMatchObject({ enabled: false });
    }
    expect(screen.queryByText("No backups yet")).not.toBeInTheDocument();
    expect(screen.getByTestId("backup-row")).toHaveAttribute(
      "data-backup-id",
      "backup-old",
    );
    // Creating a backup still needs an active instance.
    expect(
      screen.getByRole("button", { name: /Create Backup/ }),
    ).toBeDisabled();
  });

  it("shows the application version of each backup after the Status column", async () => {
    await renderBackupsTab([
      makeBackup({
        id: "backup-new",
        name: "backup-new",
        instance: { id: "inst-1", applicationVersion: "2.5.0" },
      }),
      makeBackup({
        id: "backup-old",
        name: "backup-old",
        instance: { id: "inst-0", applicationVersion: "2.4.0" },
      }),
    ]);

    // The header comes first; each row also labels its version for screen readers.
    const [header] = screen.getAllByText("Application version");
    expect(header.previousElementSibling?.textContent).toBe("Status");

    const rows = screen.getAllByTestId("backup-row");
    expect(
      rows.map((row) => row.getAttribute("data-backup-application-version")),
    ).toEqual(["2.5.0", "2.4.0"]);
    expect(
      rows.map(
        (row) =>
          within(row).getByTestId("backup-application-version").textContent,
      ),
    ).toEqual(["2.5.0", "2.4.0"]);
  });

  it("lists a deleted deployment's backup history with restore and delete disabled", async () => {
    await renderBackupsTab(
      [
        makeBackup({
          id: "backup-new",
          name: "backup-new",
          instance: { id: "inst-1", applicationVersion: "2.5.0" },
        }),
        makeBackup({
          id: "backup-old",
          name: "backup-old",
          instance: { id: "inst-0", applicationVersion: "2.4.0" },
        }),
      ],
      makeDeployment({
        status: "deleted",
        deletedAt: "2026-09-01T08:00:00+00:00",
      }),
    );

    expect(screen.getByTestId("deleted-banner")).toBeInTheDocument();
    expect(screen.getByTestId("deployment-detail")).toHaveAttribute(
      "data-instance-id",
      "inst-1",
    );
    for (const [variables, options] of useListBackupsQueryMock.mock.calls) {
      expect(variables).toEqual({ deploymentId: "dep-1" });
      expect(options).not.toMatchObject({ enabled: false });
    }
    const rows = screen.getAllByTestId("backup-row");
    expect(rows.map((row) => row.getAttribute("data-backup-id"))).toEqual([
      "backup-new",
      "backup-old",
    ]);
    // Both backups are completed, so only the deleted state disables restore.
    for (const row of rows) {
      for (const name of ["Restore", "Delete"]) {
        const button = within(row).getByRole("button", { name });
        expect(button).toBeDisabled();
        expect(button).toHaveAttribute("title", "This deployment is deleted");
      }
    }
  });
});

describe("DeploymentDetailPage backups tab review follow-ups (#304)", () => {
  beforeEach(() => {
    useGetDeploymentQueryMock.mockReset();
    useListBackupsQueryMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const olderBackup = () =>
    makeBackup({
      id: "backup-old",
      name: "backup-old",
      instance: { id: "inst-0", applicationVersion: "2.4.0" },
    });

  it("marks the backups of the current instance", async () => {
    await renderBackupsTab([makeBackup(), olderBackup()]);

    const [current, older] = screen.getAllByTestId("backup-row");
    expect(
      within(current).getByTestId("backup-current-instance"),
    ).toHaveTextContent("current instance");
    expect(
      within(older).queryByTestId("backup-current-instance"),
    ).not.toBeInTheDocument();
  });

  it("labels the application version for screen readers and shows it in full", async () => {
    const version = "2024.10.1-rc.1+build.5";
    await renderBackupsTab([
      makeBackup({ instance: { id: "inst-1", applicationVersion: version } }),
    ]);

    const row = screen.getByTestId("backup-row");
    const cell = within(row).getByTestId("backup-application-version");
    expect(cell).toHaveTextContent(version);
    expect(cell).not.toHaveAttribute("title");
    expect(cell.className).not.toContain("truncate");
    expect(cell.parentElement?.textContent).toContain(
      `Application version ${version}`,
    );
  });

  it("shows the time a backup was created, not only the date", async () => {
    await renderBackupsTab([makeBackup()]);

    expect(screen.getByTestId("backup-created")).toHaveTextContent(
      new Date("2026-08-03T12:04:06+00:00").toLocaleString(undefined, {
        dateStyle: "short",
        timeStyle: "short",
      }),
    );
  });

  it("marks an expired backup and disables its restore", async () => {
    await renderBackupsTab([
      makeBackup({ expiresAt: "2026-10-01T00:00:00+00:00" }),
    ]);

    const row = screen.getByTestId("backup-row");
    expect(within(row).getByTestId("backup-expired")).toHaveTextContent(
      "Expired",
    );
    const restore = within(row).getByRole("button", { name: "Restore" });
    expect(restore).toBeDisabled();
    expect(restore.getAttribute("title")).toContain("expiry date");
    expect(within(row).getByRole("button", { name: "Delete" })).toBeEnabled();
  });

  it("keeps restore enabled for a backup that has not expired", async () => {
    await renderBackupsTab([makeBackup()]);

    const row = screen.getByTestId("backup-row");
    expect(within(row).queryByTestId("backup-expired")).not.toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Restore" })).toBeEnabled();
  });

  it("shows an error with a retry action when the history fails to load", async () => {
    const refetch = vi.fn();
    await renderBackupsTab([], makeDeployment(), {
      ...noopQueryResult,
      error: new Error("network down"),
      refetch,
    });

    expect(
      screen.getByText("Could not load the backup history"),
    ).toBeInTheDocument();
    expect(screen.getByText("network down")).toBeInTheDocument();
    expect(screen.queryByText("No backups yet")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("explains that a deleted deployment with the same name keeps its own backups", async () => {
    await renderBackupsTab([]);

    const empty = screen.getByTestId("backups-empty");
    expect(empty).toHaveTextContent("No backups yet");
    expect(empty).toHaveTextContent("Show deleted");
  });

  it("explains the empty history of a deleted deployment", async () => {
    await renderBackupsTab(
      [],
      makeDeployment({
        status: "deleted",
        deletedAt: "2026-09-01T08:00:00+00:00",
      }),
    );

    expect(screen.getByTestId("backups-empty")).toHaveTextContent(
      "No backup was taken of this deployment before it was deleted.",
    );
  });

  it("shows both versions and warns before restoring a backup of an earlier instance", async () => {
    await renderBackupsTab([makeBackup(), olderBackup()]);

    const older = screen.getAllByTestId("backup-row")[1];
    await userEvent.click(
      within(older).getByRole("button", { name: "Restore" }),
    );

    expect(screen.getByTestId("restore-backup-version")).toHaveTextContent(
      "2.4.0",
    );
    expect(screen.getByTestId("restore-current-version")).toHaveTextContent(
      "2.5.0",
    );
    const warning = screen.getByTestId("restore-earlier-instance-warning");
    expect(warning).toHaveTextContent("earlier instance");
    expect(warning).toHaveTextContent("HelmRelease");
  });

  it("shows both versions without a warning for a backup of the current instance", async () => {
    await renderBackupsTab([makeBackup()]);

    const row = screen.getByTestId("backup-row");
    await userEvent.click(within(row).getByRole("button", { name: "Restore" }));

    expect(screen.getByTestId("restore-backup-version")).toHaveTextContent(
      "2.5.0",
    );
    expect(screen.getByTestId("restore-current-version")).toHaveTextContent(
      "2.5.0",
    );
    expect(
      screen.queryByTestId("restore-earlier-instance-warning"),
    ).not.toBeInTheDocument();
  });
});
