/**
 * Backups tab on the environment detail page (001-env-backup-restore, US1).
 *
 * The tab is the frontend surface of FR-012: one click backs the whole
 * environment up, and the snapshot list shows each parent's *derived* status
 * plus how many constituents are behind it. The `data-*` attributes asserted
 * here are the contract the Playwright scenario driver reads, so they are
 * tested as behaviour rather than left to the E2E to discover.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, userEvent, waitFor, within } from "@/test/utils";
import type { AuthContextValue } from "@/auth/AuthProvider";
import { EnvironmentBackupsTab } from "@/components/environment/EnvironmentBackupsTab";

const useListEnvironmentBackupsQuery = vi.fn();
const createEnvironmentBackupMutateAsync = vi.fn();
const useCreateEnvironmentBackupMutation = vi.fn();

vi.mock("@/generated/graphql", async () => {
  const actual = await vi.importActual<typeof import("@/generated/graphql")>(
    "@/generated/graphql",
  );
  return {
    ...actual,
    useListEnvironmentBackupsQuery: (...args: unknown[]) =>
      useListEnvironmentBackupsQuery(...args),
    useCreateEnvironmentBackupMutation: (...args: unknown[]) =>
      useCreateEnvironmentBackupMutation(...args),
  };
});

const ENVIRONMENT_ID = "env-1";

function queryResult(
  environmentBackups: unknown[],
  overrides: Record<string, unknown> = {},
) {
  return {
    data: { environmentBackups },
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
    dataUpdatedAt: Date.now(),
    ...overrides,
  };
}

/** A constituent backed by a real per-instance backup row. */
function constituent(
  deploymentName: string,
  status: string,
  overrides: Record<string, unknown> = {},
) {
  return {
    deploymentId: `dep-${deploymentName}`,
    deploymentName,
    error: null,
    backup: {
      id: `backup-${deploymentName}`,
      name: `${deploymentName}-backup`,
      status,
      completedAt: null,
      sizeBytes: null,
      errorMessage: null,
    },
    ...overrides,
  };
}

function snapshot(overrides: Record<string, unknown> = {}) {
  return {
    id: "envbackup-1",
    name: "env-backup-2026-08-06",
    status: "COMPLETED",
    createdOn: "2026-08-06T10:00:00Z",
    constituents: [constituent("api", "completed")],
    ...overrides,
  };
}

const readOnlyAuth: AuthContextValue = {
  currentUser: {
    id: "u-ro",
    username: "viewer",
    displayName: "Viewer",
    role: "READ_ONLY",
    effectiveRole: "READ_ONLY",
    active: true,
  },
  loading: false,
  refresh: () => Promise.resolve(),
  logout: () => Promise.resolve(),
};

describe("EnvironmentBackupsTab", () => {
  beforeEach(() => {
    useListEnvironmentBackupsQuery.mockReset();
    createEnvironmentBackupMutateAsync.mockReset();
    createEnvironmentBackupMutateAsync.mockResolvedValue({
      createEnvironmentBackup: {
        id: "envbackup-new",
        name: "new",
        status: "PENDING",
        createdOn: "2026-08-06T11:00:00Z",
      },
    });
    useCreateEnvironmentBackupMutation.mockReset();
    useCreateEnvironmentBackupMutation.mockReturnValue({
      mutateAsync: createEnvironmentBackupMutateAsync,
      isPending: false,
    });
  });

  it("polls the snapshot list every 10 seconds", async () => {
    // Parent status is derived on every read, so the list only converges by
    // refetching — a missing interval would freeze a snapshot on IN_PROGRESS.
    useListEnvironmentBackupsQuery.mockReturnValue(queryResult([]));

    await render(<EnvironmentBackupsTab environmentId={ENVIRONMENT_ID} />);

    expect(useListEnvironmentBackupsQuery).toHaveBeenCalledWith(
      { environmentId: ENVIRONMENT_ID },
      expect.objectContaining({ refetchInterval: 10_000 }),
    );
  });

  it("renders the empty state when the environment has no snapshots", async () => {
    useListEnvironmentBackupsQuery.mockReturnValue(queryResult([]));

    await render(<EnvironmentBackupsTab environmentId={ENVIRONMENT_ID} />);

    expect(screen.getByTestId("environment-backups-empty")).toHaveTextContent(
      /no environment backups yet/i,
    );
    expect(
      screen.queryByTestId("environment-backup-row"),
    ).not.toBeInTheDocument();
    // The tab still offers the action — an empty environment yields a valid
    // config-only snapshot (FR-011).
    expect(
      screen.getByTestId("create-environment-backup-button"),
    ).toBeInTheDocument();
  });

  it("renders one row per snapshot carrying its id, name and derived status", async () => {
    useListEnvironmentBackupsQuery.mockReturnValue(
      queryResult([
        snapshot(),
        snapshot({
          id: "envbackup-2",
          name: "nightly",
          status: "PARTIAL",
          constituents: [
            constituent("api", "completed"),
            constituent("worker", "failed"),
          ],
        }),
      ]),
    );

    await render(<EnvironmentBackupsTab environmentId={ENVIRONMENT_ID} />);

    const rows = screen.getAllByTestId("environment-backup-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute(
      "data-environment-backup-id",
      "envbackup-1",
    );
    expect(rows[0]).toHaveAttribute(
      "data-environment-backup-name",
      "env-backup-2026-08-06",
    );
    // Raw enum value, not the humanised badge label: the UI scenario driver
    // must report the same string the API driver reads off GraphQL.
    expect(rows[0]).toHaveAttribute(
      "data-environment-backup-status",
      "COMPLETED",
    );
    expect(rows[1]).toHaveAttribute(
      "data-environment-backup-status",
      "PARTIAL",
    );
  });

  it("shows a humanised badge for each derived status", async () => {
    useListEnvironmentBackupsQuery.mockReturnValue(
      queryResult([
        snapshot({ id: "b1", status: "COMPLETED" }),
        snapshot({ id: "b2", status: "PARTIAL" }),
        snapshot({ id: "b3", status: "IN_PROGRESS" }),
        snapshot({ id: "b4", status: "FAILED" }),
        snapshot({ id: "b5", status: "PENDING" }),
      ]),
    );

    await render(<EnvironmentBackupsTab environmentId={ENVIRONMENT_ID} />);

    const badges = screen
      .getAllByTestId("environment-backup-status")
      .map((cell) => cell.textContent);
    expect(badges).toEqual([
      "Complete",
      "Partial",
      "In Progress",
      "Failed",
      "Pending",
    ]);
  });

  it("summarises constituent outcomes, keeping failures and gaps distinct", async () => {
    // A constituent with an `error` never got a backup row; a constituent with
    // neither backup nor error was deleted individually afterwards. FR-010
    // wants that gap visible rather than folded into the failure count.
    useListEnvironmentBackupsQuery.mockReturnValue(
      queryResult([
        snapshot({
          status: "PARTIAL",
          constituents: [
            constituent("api", "completed"),
            constituent("worker", "failed"),
            {
              deploymentId: "dep-cache",
              deploymentName: "cache",
              error: "backup already in progress",
              backup: null,
            },
            {
              deploymentId: "dep-db",
              deploymentName: "db",
              error: null,
              backup: null,
            },
            constituent("queue", "in_progress"),
          ],
        }),
      ]),
    );

    await render(<EnvironmentBackupsTab environmentId={ENVIRONMENT_ID} />);

    const row = screen.getByTestId("environment-backup-row");
    expect(row).toHaveAttribute("data-constituent-total", "5");
    expect(row).toHaveAttribute("data-constituent-completed", "1");
    expect(row).toHaveAttribute("data-constituent-failed", "2");
    expect(row).toHaveAttribute("data-constituent-missing", "1");
    expect(
      within(row).getByTestId("environment-backup-constituents"),
    ).toHaveTextContent("1/5 complete · 2 failed, 1 deleted, 1 in progress");
  });

  it("labels a zero-constituent snapshot as config only", async () => {
    // FR-011: an environment with no eligible deployments still yields a
    // valid, immediately COMPLETED snapshot.
    useListEnvironmentBackupsQuery.mockReturnValue(
      queryResult([snapshot({ constituents: [] })]),
    );

    await render(<EnvironmentBackupsTab environmentId={ENVIRONMENT_ID} />);

    const row = screen.getByTestId("environment-backup-row");
    expect(row).toHaveAttribute("data-constituent-total", "0");
    expect(
      within(row).getByTestId("environment-backup-constituents"),
    ).toHaveTextContent("Config only");
  });

  it("creates a snapshot for the environment when Create Backup is clicked", async () => {
    useListEnvironmentBackupsQuery.mockReturnValue(queryResult([]));

    await render(<EnvironmentBackupsTab environmentId={ENVIRONMENT_ID} />);

    const user = userEvent.setup();
    await user.click(screen.getByTestId("create-environment-backup-button"));

    await waitFor(() =>
      expect(createEnvironmentBackupMutateAsync).toHaveBeenCalledWith({
        environmentId: ENVIRONMENT_ID,
      }),
    );
    expect(screen.queryByTestId("environment-backups-error")).toBeNull();
  });

  it("surfaces a rejected create instead of failing silently", async () => {
    // ALREADY_IN_PROGRESS (FR-009) is the operator's answer to "why did no new
    // snapshot appear?" — it must reach the page.
    useListEnvironmentBackupsQuery.mockReturnValue(queryResult([]));
    createEnvironmentBackupMutateAsync.mockRejectedValue(
      new Error("an environment backup is already in progress"),
    );
    vi.spyOn(console, "error").mockImplementation(() => {});

    await render(<EnvironmentBackupsTab environmentId={ENVIRONMENT_ID} />);

    const user = userEvent.setup();
    await user.click(screen.getByTestId("create-environment-backup-button"));

    expect(
      await screen.findByTestId("environment-backups-error"),
    ).toHaveTextContent(/already in progress/i);
  });

  it("disables the button while the create mutation is in flight", async () => {
    useListEnvironmentBackupsQuery.mockReturnValue(queryResult([]));
    useCreateEnvironmentBackupMutation.mockReturnValue({
      mutateAsync: createEnvironmentBackupMutateAsync,
      isPending: true,
    });

    await render(<EnvironmentBackupsTab environmentId={ENVIRONMENT_ID} />);

    const button = screen.getByTestId("create-environment-backup-button");
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent("Creating...");
  });

  it("hides Create Backup from a READ_ONLY operator but still lists snapshots", async () => {
    useListEnvironmentBackupsQuery.mockReturnValue(queryResult([snapshot()]));

    await render(<EnvironmentBackupsTab environmentId={ENVIRONMENT_ID} />, {
      auth: readOnlyAuth,
    });

    expect(
      screen.queryByTestId("create-environment-backup-button"),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("environment-backup-row")).toBeInTheDocument();
  });

  it("shows a retryable error state when the list query fails", async () => {
    const refetch = vi.fn();
    useListEnvironmentBackupsQuery.mockReturnValue(
      queryResult([], {
        data: undefined,
        isError: true,
        error: new Error("network down"),
        refetch,
      }),
    );

    await render(<EnvironmentBackupsTab environmentId={ENVIRONMENT_ID} />);

    expect(screen.getByText(/network down/i)).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(refetch).toHaveBeenCalled();
  });
});
