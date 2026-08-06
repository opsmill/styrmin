/**
 * Restore surface on the environment Backups tab (001-env-backup-restore, US2).
 *
 * Covers FR-006 (one-action in-place restore behind an ADMIN-gated
 * confirmation) and FR-007 / SC-004 (every non-restored constituent shown with
 * its deployment name and reason — zero silent skips). The `data-*` attributes
 * asserted here are the contract the Playwright scenario driver reads, so they
 * are tested as behaviour rather than left to the E2E to discover.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, userEvent, waitFor, within } from "@/test/utils";
import type { AuthContextValue } from "@/auth/AuthProvider";
import {
  EnvironmentBackupRow,
  type EnvironmentBackupItem,
} from "@/components/environment/EnvironmentBackupRow";

const useListEnvironmentRestoresQuery = vi.fn();
const restoreMutateAsync = vi.fn();
const useRestoreEnvironmentBackupMutation = vi.fn();

vi.mock("@/generated/graphql", async () => {
  const actual = await vi.importActual<typeof import("@/generated/graphql")>(
    "@/generated/graphql",
  );
  return {
    ...actual,
    useListEnvironmentRestoresQuery: (...args: unknown[]) =>
      useListEnvironmentRestoresQuery(...args),
    useRestoreEnvironmentBackupMutation: (...args: unknown[]) =>
      useRestoreEnvironmentBackupMutation(...args),
  };
});

const BACKUP_ID = "envbackup-1";

function queryResult(
  environmentRestores: unknown[],
  overrides: Record<string, unknown> = {},
) {
  return {
    data: { environmentRestores },
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  };
}

function snapshot(
  overrides: Partial<EnvironmentBackupItem> = {},
): EnvironmentBackupItem {
  return {
    id: BACKUP_ID,
    name: "env-backup-2026-08-06",
    status: "COMPLETED",
    createdOn: "2026-08-06T10:00:00Z",
    constituents: [
      {
        deploymentId: "dep-api",
        deploymentName: "api",
        error: null,
        backup: {
          id: "backup-api",
          name: "api-backup",
          status: "completed",
          completedAt: null,
          sizeBytes: null,
          errorMessage: null,
        },
      },
    ],
    ...overrides,
  };
}

function constituentRestore(
  name: string,
  status: string,
  errorMessage: string | null = null,
) {
  return {
    id: `restore-${name}`,
    name,
    status,
    targetInstanceId: `instance-${name}`,
    errorMessage,
  };
}

function skipped(deploymentName: string, reason: string) {
  return { deploymentId: `dep-${deploymentName}`, deploymentName, reason };
}

function environmentRestore(overrides: Record<string, unknown> = {}) {
  return {
    id: "envrestore-1",
    status: "COMPLETED",
    createdOn: "2026-08-06T12:00:00Z",
    environmentBackupId: BACKUP_ID,
    restores: [constituentRestore("api-restore", "completed")],
    skippedConstituents: [],
    ...overrides,
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

async function renderRow(
  overrides: Partial<EnvironmentBackupItem> = {},
  options = {},
) {
  return render(
    <EnvironmentBackupRow environmentBackup={snapshot(overrides)} index={0} />,
    options,
  );
}

describe("EnvironmentBackupRow — restore", () => {
  beforeEach(() => {
    useListEnvironmentRestoresQuery.mockReset();
    useListEnvironmentRestoresQuery.mockReturnValue(queryResult([]));
    restoreMutateAsync.mockReset();
    restoreMutateAsync.mockResolvedValue({
      restoreEnvironmentBackup: {
        id: "envrestore-new",
        status: "PENDING",
        createdOn: "2026-08-06T12:30:00Z",
      },
    });
    useRestoreEnvironmentBackupMutation.mockReset();
    useRestoreEnvironmentBackupMutation.mockReturnValue({
      mutateAsync: restoreMutateAsync,
      isPending: false,
    });
  });

  it("does not fetch the restore history until the row is expanded", async () => {
    await renderRow();

    expect(useListEnvironmentRestoresQuery).toHaveBeenCalledWith(
      { environmentBackupId: BACKUP_ID },
      expect.objectContaining({ enabled: false, refetchInterval: 10_000 }),
    );
    expect(
      screen.queryByTestId("environment-backup-restores"),
    ).not.toBeInTheDocument();
  });

  it("expands to show the restore history and polls it", async () => {
    await renderRow();

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-backup-expand-button"));

    expect(
      screen.getByTestId("environment-backup-restores"),
    ).toBeInTheDocument();
    expect(useListEnvironmentRestoresQuery).toHaveBeenLastCalledWith(
      { environmentBackupId: BACKUP_ID },
      expect.objectContaining({ enabled: true, refetchInterval: 10_000 }),
    );
  });

  it("shows an empty state when the snapshot has never been restored", async () => {
    await renderRow();

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-backup-expand-button"));

    expect(screen.getByTestId("environment-restores-empty")).toHaveTextContent(
      /no restores from this snapshot yet/i,
    );
  });

  it("asks for confirmation before restoring and only fires on confirm", async () => {
    await renderRow();

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-backup-restore-button"));

    expect(
      screen.getByTestId("environment-restore-dialog"),
    ).toBeInTheDocument();
    expect(restoreMutateAsync).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("environment-restore-dialog-confirm"));

    await waitFor(() =>
      expect(restoreMutateAsync).toHaveBeenCalledWith({
        environmentBackupId: BACKUP_ID,
      }),
    );
  });

  it("cancelling the confirmation restores nothing", async () => {
    await renderRow();

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-backup-restore-button"));
    await user.click(screen.getByTestId("environment-restore-dialog-cancel"));

    expect(restoreMutateAsync).not.toHaveBeenCalled();
  });

  it("reveals the restore history after a successful restore", async () => {
    await renderRow();

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-backup-restore-button"));
    await user.click(screen.getByTestId("environment-restore-dialog-confirm"));

    expect(
      await screen.findByTestId("environment-backup-restores"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("environment-backup-restore-error"),
    ).not.toBeInTheDocument();
  });

  it("surfaces a rejected restore instead of failing silently", async () => {
    // OPERATION_DENIED / ALREADY_IN_PROGRESS is the operator's answer to
    // "why did nothing happen?" — it must reach the page.
    restoreMutateAsync.mockRejectedValue(
      new Error("an environment restore is already in progress"),
    );
    vi.spyOn(console, "error").mockImplementation(() => {});

    await renderRow();

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-backup-restore-button"));
    await user.click(screen.getByTestId("environment-restore-dialog-confirm"));

    expect(
      await screen.findByTestId("environment-backup-restore-error"),
    ).toHaveTextContent(/already in progress/i);
  });

  it.each(["PENDING", "IN_PROGRESS", "FAILED"] as const)(
    "disables Restore for a %s snapshot",
    async (status) => {
      await renderRow({ status });

      const button = screen.getByTestId("environment-backup-restore-button");
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("data-restorable", "false");
    },
  );

  it.each(["COMPLETED", "PARTIAL"] as const)(
    "enables Restore for a %s snapshot",
    async (status) => {
      await renderRow({ status });

      const button = screen.getByTestId("environment-backup-restore-button");
      expect(button).toBeEnabled();
      expect(button).toHaveAttribute("data-restorable", "true");
    },
  );

  it("hides Restore from a READ_WRITE operator", async () => {
    // Restoring reverts the environment config, so it is ADMIN-only — parity
    // with updateEnvironment (research.md D7).
    await renderRow({}, { auth: readWriteAuth() });

    expect(
      screen.queryByTestId("environment-backup-restore-button"),
    ).not.toBeInTheDocument();
    // The snapshot itself is still visible and expandable.
    expect(screen.getByTestId("environment-backup-row")).toBeInTheDocument();
  });

  it("renders each restore with its derived status and constituent counts", async () => {
    useListEnvironmentRestoresQuery.mockReturnValue(
      queryResult([
        environmentRestore({
          id: "envrestore-2",
          status: "PARTIAL",
          restores: [
            constituentRestore("api-restore", "completed"),
            constituentRestore("worker-restore", "failed", "velero exploded"),
          ],
          skippedConstituents: [skipped("cache", "backup expired")],
        }),
      ]),
    );

    await renderRow();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-backup-expand-button"));

    const row = screen.getByTestId("environment-restore-row");
    expect(row).toHaveAttribute("data-environment-restore-id", "envrestore-2");
    // Raw enum value, not the humanised badge label: the UI scenario driver
    // must report the same string the API driver reads off GraphQL.
    expect(row).toHaveAttribute("data-environment-restore-status", "PARTIAL");
    expect(row).toHaveAttribute("data-restore-total", "2");
    expect(row).toHaveAttribute("data-skipped-total", "1");
    expect(
      within(row).getByTestId("environment-restore-status"),
    ).toHaveTextContent("Partial");

    const constituents = within(row).getAllByTestId(
      "environment-restore-constituent",
    );
    expect(constituents).toHaveLength(2);
    expect(constituents[1]).toHaveAttribute("data-restore-status", "failed");
    expect(constituents[1]).toHaveTextContent("velero exploded");
  });

  it("attributes every skipped constituent with its deployment name and reason", async () => {
    // FR-007 / SC-004: zero silent skips. `reason` is free text from the
    // backend, so it is rendered verbatim rather than mapped through a table
    // that would drop unknown values.
    useListEnvironmentRestoresQuery.mockReturnValue(
      queryResult([
        environmentRestore({
          status: "PARTIAL",
          restores: [constituentRestore("api-restore", "completed")],
          skippedConstituents: [
            skipped("cache", "backup expired"),
            skipped("gone", "deployment no longer exists"),
            skipped("busy", "deployment busy with another restore"),
            skipped("odd", "restore could not be created: boom"),
          ],
        }),
      ]),
    );

    await renderRow();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-backup-expand-button"));

    const entries = screen.getAllByTestId(
      "environment-restore-skipped-constituent",
    );
    expect(
      entries.map((entry) => [
        entry.getAttribute("data-deployment-name"),
        entry.getAttribute("data-skip-reason"),
      ]),
    ).toEqual([
      ["cache", "backup expired"],
      ["gone", "deployment no longer exists"],
      ["busy", "deployment busy with another restore"],
      ["odd", "restore could not be created: boom"],
    ]);
    expect(entries[0]).toHaveTextContent("Skipped cache: backup expired");
  });

  it("omits the skipped list entirely when nothing was skipped", async () => {
    useListEnvironmentRestoresQuery.mockReturnValue(
      queryResult([environmentRestore()]),
    );

    await renderRow();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-backup-expand-button"));

    const row = screen.getByTestId("environment-restore-row");
    expect(row).toHaveAttribute("data-skipped-total", "0");
    expect(
      within(row).queryByTestId("environment-restore-skipped"),
    ).not.toBeInTheDocument();
  });

  it("shows an error when the restore history fails to load", async () => {
    useListEnvironmentRestoresQuery.mockReturnValue(
      queryResult([], {
        data: undefined,
        isError: true,
        error: new Error("network down"),
      }),
    );

    await renderRow();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-backup-expand-button"));

    expect(screen.getByTestId("environment-restores-error")).toHaveTextContent(
      /network down/i,
    );
  });
});
