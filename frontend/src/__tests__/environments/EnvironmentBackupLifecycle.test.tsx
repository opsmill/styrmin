/**
 * Snapshot visibility and lifecycle on the environment Backups tab
 * (001-env-backup-restore, US3).
 *
 * Two behaviours are under test:
 *
 * - **Per-constituent visibility** — what makes a `PARTIAL` snapshot
 *   trustworthy. Every captured deployment must appear exactly once, as a live
 *   backup, an attributable creation error, or a *gap* left by a constituent
 *   whose backup was deleted since the snapshot was taken. A silently omitted
 *   row is indistinguishable from an application that was never in the
 *   snapshot, so gaps are asserted explicitly.
 * - **Cascade deletion behind a confirmation** (FR-010), including the escape
 *   hatch: deleting an `IN_PROGRESS` snapshot must be offered, because that is
 *   the only way to clear a snapshot pinned in progress by a constituent whose
 *   work was never picked up.
 *
 * The `data-*` attributes asserted here are the contract the Playwright
 * scenario driver reads, so they are tested as behaviour rather than left to
 * the E2E to discover.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { render, screen, userEvent, waitFor, within } from "@/test/utils";
import type { AuthContextValue } from "@/auth/AuthProvider";
import {
  EnvironmentBackupRow,
  classifyConstituent,
  summarizeConstituents,
  type EnvironmentBackupConstituentItem,
  type EnvironmentBackupItem,
} from "@/components/environment/EnvironmentBackupRow";

const useListEnvironmentRestoresQuery = vi.fn();
const useRestoreEnvironmentBackupMutation = vi.fn();
const deleteMutateAsync = vi.fn();
const useDeleteEnvironmentBackupMutation = vi.fn();

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
    useDeleteEnvironmentBackupMutation: (...args: unknown[]) =>
      useDeleteEnvironmentBackupMutation(...args),
  };
});

const BACKUP_ID = "envbackup-1";

/** A constituent whose backup exists, with the given per-instance status. */
function withBackup(
  deploymentName: string,
  status: string,
  errorMessage: string | null = null,
): EnvironmentBackupConstituentItem {
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
      errorMessage,
    },
  };
}

/** A constituent that never got a backup row, with the recorded reason. */
function withError(
  deploymentName: string,
  error: string,
): EnvironmentBackupConstituentItem {
  return {
    deploymentId: `dep-${deploymentName}`,
    deploymentName,
    error,
    backup: null,
  };
}

/** A gap: captured in the snapshot, but the constituent row is gone. */
function asGap(deploymentName: string): EnvironmentBackupConstituentItem {
  return {
    deploymentId: `dep-${deploymentName}`,
    deploymentName,
    error: null,
    backup: null,
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
    constituents: [withBackup("api", "completed")],
    ...overrides,
  };
}

function queryResult(environmentRestores: unknown[] = []) {
  return {
    data: { environmentRestores },
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  };
}

function auth(role: "READ_ONLY" | "READ_WRITE" | "ADMIN"): AuthContextValue {
  return {
    currentUser: {
      id: `u-${role}`,
      username: role.toLowerCase(),
      displayName: role,
      role,
      effectiveRole: role,
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
    <EnvironmentBackupRow
      environmentBackup={snapshot(overrides)}
      index={0}
      autoRefreshEnabled
    />,
    options,
  );
}

async function expand() {
  const user = userEvent.setup();
  await user.click(screen.getByTestId("environment-backup-expand-button"));
  return user;
}

beforeEach(() => {
  useListEnvironmentRestoresQuery.mockReset();
  useListEnvironmentRestoresQuery.mockReturnValue(queryResult());
  useRestoreEnvironmentBackupMutation.mockReset();
  useRestoreEnvironmentBackupMutation.mockReturnValue({
    mutateAsync: vi.fn(),
    isPending: false,
  });
  deleteMutateAsync.mockReset();
  deleteMutateAsync.mockResolvedValue({ deleteEnvironmentBackup: true });
  useDeleteEnvironmentBackupMutation.mockReset();
  // The stub honours the `onSuccess` the component passes in. Returning a bare
  // `{ mutateAsync }` would silently swallow it, which is exactly how the
  // guideline-mandated invalidation went untested (and under-specified) before:
  // a dropped query key could not fail any test.
  useDeleteEnvironmentBackupMutation.mockImplementation(
    (options?: { onSuccess?: (data: unknown) => void }) => ({
      mutateAsync: async (variables: unknown) => {
        const data = await deleteMutateAsync(variables);
        options?.onSuccess?.(data);
        return data;
      },
      isPending: false,
    }),
  );
});

describe("classifyConstituent", () => {
  it.each([
    ["a live completed backup", withBackup("api", "completed"), "completed"],
    ["a failed backup", withBackup("api", "failed"), "failed"],
    ["a pending backup", withBackup("api", "pending"), "in-flight"],
    ["an in-progress backup", withBackup("api", "in_progress"), "in-flight"],
    ["a creation error", withError("api", "already in progress"), "error"],
    ["a deleted constituent", asGap("api"), "missing"],
  ] as const)("classifies %s", (_label, constituent, expected) => {
    expect(classifyConstituent(constituent)).toBe(expected);
  });

  it("is case-insensitive about the backup status", () => {
    // The parent's status enum is uppercase while a constituent Backup's is
    // lowercase; a backend that ever uppercased the child must not silently
    // reclassify every constituent as in-flight.
    expect(classifyConstituent(withBackup("api", "COMPLETED"))).toBe(
      "completed",
    );
  });

  it("folds creation errors into the summary's failed count", () => {
    // The collapsed row has one "failed" bucket, but the expanded list keeps
    // `error` and `failed` distinct — the two views must agree on the totals.
    const summary = summarizeConstituents([
      withBackup("api", "completed"),
      withBackup("worker", "failed"),
      withError("busy", "backup already in progress"),
      asGap("gone"),
    ]);
    expect(summary).toEqual({
      total: 4,
      completed: 1,
      failed: 2,
      missing: 1,
      inFlight: 0,
    });
  });
});

describe("EnvironmentBackupRow — per-constituent outcomes", () => {
  it("lists every captured deployment exactly once with its outcome", async () => {
    await renderRow({
      status: "PARTIAL",
      constituents: [
        withBackup("api", "completed"),
        withBackup("worker", "failed", "velero exploded"),
        withBackup("queue", "in_progress"),
        withError("busy", "Backup already in progress: 1234"),
        asGap("gone"),
      ],
    });

    await expand();

    const rows = screen.getAllByTestId("environment-backup-constituent");
    expect(
      rows.map((row) => [
        row.getAttribute("data-deployment-name"),
        row.getAttribute("data-constituent-outcome"),
      ]),
    ).toEqual([
      ["api", "completed"],
      ["worker", "failed"],
      ["queue", "in-flight"],
      ["busy", "error"],
      ["gone", "missing"],
    ]);
  });

  it("publishes the constituent backup id and raw status for the driver", async () => {
    await renderRow({ constituents: [withBackup("api", "completed")] });

    await expand();

    const row = screen.getByTestId("environment-backup-constituent");
    expect(row).toHaveAttribute("data-backup-id", "backup-api");
    expect(row).toHaveAttribute("data-backup-status", "completed");
    expect(row).toHaveAttribute("data-deployment-id", "dep-api");
  });

  it("shows the recorded reason verbatim for a constituent that never ran", async () => {
    // FR-005: the error is free text from the backend, so it is rendered as-is
    // rather than mapped through a table that would drop unknown values.
    await renderRow({
      status: "PARTIAL",
      constituents: [
        withBackup("api", "completed"),
        withError("busy", "Backup already in progress: 1234"),
      ],
    });

    await expand();

    const row = screen
      .getAllByTestId("environment-backup-constituent")
      .find((el) => el.getAttribute("data-deployment-name") === "busy");
    expect(row).toHaveTextContent("Backup already in progress: 1234");
    expect(row).toHaveAttribute("data-backup-id", "");
  });

  it("makes a gap from a deleted constituent visible", async () => {
    // US3: the parent survives an individually deleted child and the gap must
    // be legible — an omitted row would look like an application that was
    // never in the snapshot at all.
    await renderRow({
      constituents: [withBackup("api", "completed"), asGap("cache")],
    });

    await expand();

    const row = screen
      .getAllByTestId("environment-backup-constituent")
      .find((el) => el.getAttribute("data-deployment-name") === "cache");
    expect(row).toHaveAttribute("data-constituent-outcome", "missing");
    expect(row).toHaveTextContent(/constituent backup was deleted/i);
    // Deliberately NOT attributed to retention expiry: expiry garbage-collects
    // the Velero data but never removes the `Backup` row (see
    // `_classify_constituents` — an expired constituent still reads
    // `completed`), so naming expiry here would send the operator hunting a
    // retention problem that cannot produce this state.
    expect(row).not.toHaveTextContent(/expired/i);
    // The collapsed summary counts it separately from a failure.
    expect(screen.getByTestId("environment-backup-row")).toHaveAttribute(
      "data-constituent-missing",
      "1",
    );
  });

  it("surfaces a failed constituent's own error message", async () => {
    await renderRow({
      status: "PARTIAL",
      constituents: [withBackup("worker", "failed", "velero exploded")],
    });

    await expand();

    expect(
      screen.getByTestId("environment-backup-constituent"),
    ).toHaveTextContent("velero exploded");
  });

  it("says so explicitly for a config-only snapshot", async () => {
    await renderRow({ constituents: [] });

    await expand();

    expect(
      screen.getByTestId("environment-backup-constituents-empty"),
    ).toHaveTextContent(/config-only/i);
    expect(
      screen.queryByTestId("environment-backup-constituent"),
    ).not.toBeInTheDocument();
  });

  it("does not render the outcome list until the row is expanded", async () => {
    await renderRow();

    expect(
      screen.queryByTestId("environment-backup-detail"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("environment-backup-constituent"),
    ).not.toBeInTheDocument();
  });
});

describe("EnvironmentBackupRow — delete", () => {
  it("asks for confirmation and only deletes on confirm", async () => {
    await renderRow();

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-backup-delete-button"));

    expect(
      screen.getByTestId("environment-backup-delete-dialog"),
    ).toBeInTheDocument();
    expect(deleteMutateAsync).not.toHaveBeenCalled();

    await user.click(
      screen.getByTestId("environment-backup-delete-dialog-confirm"),
    );

    await waitFor(() =>
      expect(deleteMutateAsync).toHaveBeenCalledWith({
        environmentBackupId: BACKUP_ID,
      }),
    );
  });

  it("cancelling the confirmation deletes nothing", async () => {
    await renderRow();

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-backup-delete-button"));
    await user.click(
      screen.getByTestId("environment-backup-delete-dialog-cancel"),
    );

    expect(deleteMutateAsync).not.toHaveBeenCalled();
    expect(
      screen.queryByTestId("environment-backup-delete-dialog"),
    ).not.toBeInTheDocument();
  });

  it("warns that the cascade takes the constituent backups with it", async () => {
    await renderRow({
      constituents: [
        withBackup("api", "completed"),
        withBackup("worker", "completed"),
      ],
    });

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-backup-delete-button"));

    const body = screen.getByTestId("environment-backup-delete-dialog-body");
    expect(body).toHaveTextContent("env-backup-2026-08-06");
    expect(body).toHaveTextContent(/2 application backup/i);
    expect(body).toHaveTextContent(/cannot be undone/i);
  });

  it.each(["PENDING", "IN_PROGRESS"] as const)(
    "offers delete for a %s snapshot (FR-010 escape hatch)",
    async (status) => {
      // A snapshot pinned non-terminal by a constituent that never got picked
      // up blocks every new environment-level operation; deletion is the only
      // way out, so unlike Restore it must NOT be gated on status.
      await renderRow({ status });

      const button = screen.getByTestId("environment-backup-delete-button");
      expect(button).toBeEnabled();
      // The sibling Restore button is disabled for the same snapshot.
      expect(
        screen.getByTestId("environment-backup-restore-button"),
      ).toBeDisabled();
    },
  );

  it("surfaces a rejected delete instead of failing silently", async () => {
    deleteMutateAsync.mockRejectedValue(new Error("snapshot vanished"));
    vi.spyOn(console, "error").mockImplementation(() => {});

    await renderRow();

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-backup-delete-button"));
    await user.click(
      screen.getByTestId("environment-backup-delete-dialog-confirm"),
    );

    expect(
      await screen.findByTestId("environment-backup-delete-error"),
    ).toHaveTextContent(/snapshot vanished/i);
  });

  it("offers delete to a READ_WRITE operator who cannot restore", async () => {
    // Deleting a snapshot removes backups; it does not revert the environment
    // config, so it does not inherit Restore's ADMIN gate (research.md D7).
    await renderRow({}, { auth: auth("READ_WRITE") });

    expect(
      screen.getByTestId("environment-backup-delete-button"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("environment-backup-restore-button"),
    ).not.toBeInTheDocument();
  });

  it("invalidates every list the cascade makes stale", async () => {
    // The cascade removes the parent, every constituent `Backup` and every
    // `Restore` taken from it. `ListBackups` and `ListRestores` back the
    // deployment detail page's Backups tab, so invalidating only
    // `ListEnvironmentBackups` leaves that page showing rows the server has
    // already deleted — clicking one 404s.
    const invalidate = vi.spyOn(QueryClient.prototype, "invalidateQueries");
    await renderRow();

    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-backup-delete-button"));
    await user.click(
      screen.getByTestId("environment-backup-delete-dialog-confirm"),
    );

    await waitFor(() => expect(deleteMutateAsync).toHaveBeenCalled());
    const keys = invalidate.mock.calls.map((call) => call[0]?.queryKey);
    for (const key of [
      ["ListEnvironmentBackups"],
      ["ListBackups"],
      ["ListRestores"],
    ]) {
      expect(keys).toContainEqual(key);
    }
    invalidate.mockRestore();
  });

  it("hides delete from a READ_ONLY viewer", async () => {
    await renderRow({}, { auth: auth("READ_ONLY") });

    expect(
      screen.queryByTestId("environment-backup-delete-button"),
    ).not.toBeInTheDocument();
    // The snapshot itself stays inspectable.
    const user = userEvent.setup();
    await user.click(screen.getByTestId("environment-backup-expand-button"));
    expect(
      within(screen.getByTestId("environment-backup-detail")).getByTestId(
        "environment-backup-constituent",
      ),
    ).toBeInTheDocument();
  });
});
