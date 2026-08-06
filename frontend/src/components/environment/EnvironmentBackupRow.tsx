import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, RotateCcw } from "lucide-react";

import { StatusBadge, getStatusColor } from "@/components/StatusBadge";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { IfRole } from "@/auth/IfRole";
import {
  useListEnvironmentRestoresQuery,
  useRestoreEnvironmentBackupMutation,
  type EnvironmentBackupStatus,
  type ListEnvironmentBackupsQuery,
  type ListEnvironmentRestoresQuery,
} from "@/generated/graphql";

/** One environment backup as returned by `ListEnvironmentBackups`. */
export type EnvironmentBackupItem =
  ListEnvironmentBackupsQuery["environmentBackups"][number];

/** One eligible deployment's outcome inside an environment backup. */
export type EnvironmentBackupConstituentItem =
  EnvironmentBackupItem["constituents"][number];

/** One coordinated restore performed from an environment backup. */
export type EnvironmentRestoreItem =
  ListEnvironmentRestoresQuery["environmentRestores"][number];

/**
 * Poll interval for a snapshot's restore history. An environment restore's
 * status is derived from its constituent restores on every read, so the panel
 * only converges from `IN_PROGRESS` by refetching. Matches the tab's own
 * interval.
 */
const RESTORE_REFRESH_INTERVAL_MS = 10_000;

/**
 * Derived statuses a snapshot can be restored from. Anything else is refused
 * server-side with `OPERATION_DENIED`, so the button is disabled rather than
 * offering an action that cannot succeed.
 */
const RESTORABLE_STATUSES: readonly EnvironmentBackupStatus[] = [
  "COMPLETED",
  "PARTIAL",
];

export interface ConstituentSummary {
  /** One entry per eligible deployment at backup time. */
  total: number;
  /** Constituent backups that reached `completed`. */
  completed: number;
  /** Constituents that failed — at creation (`error`) or during the backup. */
  failed: number;
  /**
   * Constituents whose backup row is gone: neither a backup nor a creation
   * error. That means the child was deleted individually after the snapshot
   * was taken. The parent survives and the gap is deliberately visible
   * (spec FR-010), so it gets its own bucket rather than being folded into
   * `failed`.
   */
  missing: number;
  /** Constituents still `pending`/`in_progress`. */
  inFlight: number;
}

/**
 * Fold the per-constituent outcomes into the counts the snapshot row shows.
 *
 * Constituent backups are ordinary per-instance backups, so their `status` is
 * the lowercase string the Backup type carries (`"completed"`, `"failed"`,
 * `"pending"`, …) — not the uppercase `EnvironmentBackupStatus` enum of the
 * parent. Comparison is case-insensitive so a backend that ever uppercases
 * them does not silently zero the counts.
 */
export function summarizeConstituents(
  constituents: readonly EnvironmentBackupConstituentItem[],
): ConstituentSummary {
  const summary: ConstituentSummary = {
    total: constituents.length,
    completed: 0,
    failed: 0,
    missing: 0,
    inFlight: 0,
  };

  for (const constituent of constituents) {
    if (constituent.error != null) {
      summary.failed += 1;
      continue;
    }
    if (constituent.backup == null) {
      summary.missing += 1;
      continue;
    }
    switch (constituent.backup.status.toLowerCase()) {
      case "completed":
        summary.completed += 1;
        break;
      case "failed":
        summary.failed += 1;
        break;
      default:
        summary.inFlight += 1;
    }
  }

  return summary;
}

/**
 * Human-readable one-liner for the Applications column, e.g. `2/3 complete`
 * with the non-complete buckets spelled out so a `PARTIAL` snapshot says why.
 */
export function formatConstituentSummary(summary: ConstituentSummary): string {
  if (summary.total === 0) return "Config only";

  const detail: string[] = [];
  if (summary.failed > 0) detail.push(`${summary.failed} failed`);
  if (summary.missing > 0) detail.push(`${summary.missing} deleted`);
  if (summary.inFlight > 0) detail.push(`${summary.inFlight} in progress`);

  const base = `${summary.completed}/${summary.total} complete`;
  return detail.length > 0 ? `${base} · ${detail.join(", ")}` : base;
}

interface EnvironmentRestoreRowProps {
  environmentRestore: EnvironmentRestoreItem;
}

/**
 * One coordinated restore inside a snapshot's restore history.
 *
 * Publishes its derived status and its constituent counts as `data-*`
 * attributes, and lists every skipped constituent with the backend's free-text
 * `reason` verbatim. The reason vocabulary is open-ended (spec FR-007 lists the
 * common values but the service also emits `restore could not be created: …`),
 * so it is rendered as text rather than switched on.
 */
function EnvironmentRestoreRow({
  environmentRestore,
}: EnvironmentRestoreRowProps) {
  const status = environmentRestore.status;
  const restores = environmentRestore.restores;
  const skipped = environmentRestore.skippedConstituents;

  return (
    <div
      className="flex flex-col gap-2 rounded-md border border-border px-3 py-2"
      data-testid="environment-restore-row"
      data-environment-restore-id={environmentRestore.id}
      data-environment-restore-status={status}
      data-restore-total={restores.length}
      data-skipped-total={skipped.length}
    >
      <div className="flex items-center gap-3">
        <span data-testid="environment-restore-status">
          <StatusBadge status={status.toLowerCase()} />
        </span>
        <span
          className="text-[13px] text-muted-foreground"
          data-testid="environment-restore-created"
        >
          {new Date(environmentRestore.createdOn).toLocaleString()}
        </span>
        <span className="text-[13px] text-muted-foreground">
          {restores.length} restored · {skipped.length} skipped
        </span>
      </div>

      {restores.length > 0 && (
        <ul
          className="flex flex-col gap-1 pl-1"
          data-testid="environment-restore-constituents"
        >
          {restores.map((restore) => (
            <li
              key={restore.id}
              className="text-xs text-muted-foreground"
              data-testid="environment-restore-constituent"
              data-restore-id={restore.id}
              data-restore-name={restore.name}
              data-restore-status={restore.status}
            >
              {restore.name}: {restore.status}
              {restore.errorMessage ? ` — ${restore.errorMessage}` : ""}
            </li>
          ))}
        </ul>
      )}

      {skipped.length > 0 && (
        <ul
          className="flex flex-col gap-1 pl-1"
          data-testid="environment-restore-skipped"
        >
          {skipped.map((constituent) => (
            <li
              key={constituent.deploymentId}
              className="text-xs text-muted-foreground"
              data-testid="environment-restore-skipped-constituent"
              data-deployment-id={constituent.deploymentId}
              data-deployment-name={constituent.deploymentName}
              data-skip-reason={constituent.reason}
            >
              Skipped {constituent.deploymentName}: {constituent.reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface EnvironmentBackupRowProps {
  environmentBackup: EnvironmentBackupItem;
  /** Row position, used only for zebra striping. */
  index: number;
}

/**
 * One environment backup in the snapshot list, with its restore history.
 *
 * The row publishes its identity and derived status as `data-*` attributes so
 * the Playwright scenario driver can read a snapshot without scraping visible
 * text. `data-environment-backup-status` carries the raw
 * `EnvironmentBackupStatus` enum value (`COMPLETED`, `PARTIAL`, …) so the UI
 * driver and the API driver report identical strings; the badge lowercases it
 * purely for display.
 *
 * Restoring is ADMIN-only (it reverts the environment's config, so it carries
 * the same privilege as editing it) and always goes through a confirmation
 * dialog — the operation overwrites live application data in place.
 */
export function EnvironmentBackupRow({
  environmentBackup,
  index,
}: EnvironmentBackupRowProps) {
  const [expanded, setExpanded] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const summary = summarizeConstituents(environmentBackup.constituents);
  const status = environmentBackup.status;
  const colors = getStatusColor(status.toLowerCase());
  const restorable = RESTORABLE_STATUSES.includes(status);

  const restoresQuery = useListEnvironmentRestoresQuery(
    { environmentBackupId: environmentBackup.id },
    { enabled: expanded, refetchInterval: RESTORE_REFRESH_INTERVAL_MS },
  );
  const restoreMutation = useRestoreEnvironmentBackupMutation();

  const environmentRestores = restoresQuery.data?.environmentRestores ?? [];

  async function handleRestore() {
    setRestoreError(null);
    setConfirmOpen(false);
    try {
      await restoreMutation.mutateAsync({
        environmentBackupId: environmentBackup.id,
      });
      // Reveal the history immediately: the new restore is the operator's
      // only view of which constituents were skipped and why.
      setExpanded(true);
      await queryClient.invalidateQueries({
        queryKey: ["ListEnvironmentRestores"],
      });
    } catch (err) {
      // Surfaced inline rather than swallowed: OPERATION_DENIED (not
      // restorable) and ALREADY_IN_PROGRESS are the operator's answer to why
      // nothing happened.
      console.error("[restore-environment-backup] mutation failed", err);
      setRestoreError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  return (
    <div
      data-testid="environment-backup-row"
      data-environment-backup-id={environmentBackup.id}
      data-environment-backup-name={environmentBackup.name}
      data-environment-backup-status={status}
      data-constituent-total={summary.total}
      data-constituent-completed={summary.completed}
      data-constituent-failed={summary.failed}
      data-constituent-missing={summary.missing}
    >
      <div
        className={`flex items-center gap-4 rounded-lg border-l-[3px] px-4 py-3 ${colors.border} ${
          index % 2 === 0 ? "bg-surface" : ""
        }`}
      >
        <div className="flex w-[240px] items-center gap-2">
          <button
            type="button"
            className="flex-shrink-0 text-muted-foreground hover:text-foreground"
            data-testid="environment-backup-expand-button"
            aria-expanded={expanded}
            aria-label={
              expanded
                ? `Hide restores of ${environmentBackup.name}`
                : `Show restores of ${environmentBackup.name}`
            }
            onClick={() => setExpanded((open) => !open)}
          >
            {expanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </button>
          <div className={`h-2 w-2 flex-shrink-0 rounded-full ${colors.dot}`} />
          <span className="truncate text-[13px] font-medium text-foreground">
            {environmentBackup.name}
          </span>
        </div>
        <div className="w-[110px]" data-testid="environment-backup-status">
          <StatusBadge status={status.toLowerCase()} />
        </div>
        <span
          className="w-[220px] text-[13px] text-muted-foreground"
          data-testid="environment-backup-constituents"
        >
          {formatConstituentSummary(summary)}
        </span>
        <span
          className="flex-1 text-[13px] text-muted-foreground"
          data-testid="environment-backup-created"
        >
          {new Date(environmentBackup.createdOn).toLocaleString()}
        </span>
        <IfRole minimum="ADMIN">
          <Button
            size="sm"
            variant="outline"
            data-testid="environment-backup-restore-button"
            data-restorable={restorable}
            disabled={!restorable || restoreMutation.isPending}
            title={
              restorable
                ? undefined
                : "Only a completed or partial snapshot can be restored"
            }
            onClick={() => setConfirmOpen(true)}
          >
            <RotateCcw className="h-4 w-4" />
            {restoreMutation.isPending ? "Restoring..." : "Restore"}
          </Button>
        </IfRole>
      </div>

      {restoreError && (
        <Alert
          variant="destructive"
          data-testid="environment-backup-restore-error"
        >
          <AlertDescription>{restoreError}</AlertDescription>
        </Alert>
      )}

      {expanded && (
        <div
          className="flex flex-col gap-2 px-4 py-2"
          data-testid="environment-backup-restores"
        >
          {restoresQuery.isError ? (
            <p
              className="text-sm text-destructive"
              data-testid="environment-restores-error"
            >
              {(restoresQuery.error as Error).message}
            </p>
          ) : restoresQuery.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading restores...</p>
          ) : environmentRestores.length === 0 ? (
            <p
              className="text-sm text-muted-foreground"
              data-testid="environment-restores-empty"
            >
              No restores from this snapshot yet
            </p>
          ) : (
            environmentRestores.map((environmentRestore) => (
              <EnvironmentRestoreRow
                key={environmentRestore.id}
                environmentRestore={environmentRestore}
              />
            ))
          )}
        </div>
      )}

      <ConfirmDialog
        open={confirmOpen}
        data-testid="environment-restore-dialog"
        title="Restore this environment snapshot?"
        description={`This reverts the environment configuration to the values captured in "${environmentBackup.name}" and restores each usable application backup in place, overwriting current application data. Constituents that cannot be restored are reported with a reason.`}
        confirmLabel="Restore"
        busy={restoreMutation.isPending}
        onConfirm={() => {
          void handleRestore();
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}
