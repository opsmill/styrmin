import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, RotateCcw, Trash2 } from "lucide-react";

import { StatusBadge, getStatusColor } from "@/components/StatusBadge";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { IfRole } from "@/auth/IfRole";
import {
  useDeleteEnvironmentBackupMutation,
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
 * The outcome of one constituent, as a closed vocabulary.
 *
 * `error` and `failed` are deliberately distinct even though the row summary
 * folds both into its `failed` count: `error` means the constituent backup was
 * never created (the environment backup recorded an attributable reason —
 * usually a per-instance conflict), while `failed` means the backup ran and
 * failed. `missing` is the gap left by a constituent that was deleted
 * individually, or whose row is otherwise gone, after the snapshot was taken.
 */
export type ConstituentOutcome =
  | "completed"
  | "failed"
  | "error"
  | "in-flight"
  | "missing";

/**
 * Classify one constituent's outcome.
 *
 * Constituent backups are ordinary per-instance backups, so their `status` is
 * the lowercase string the Backup type carries (`"completed"`, `"failed"`,
 * `"pending"`, …) — not the uppercase `EnvironmentBackupStatus` enum of the
 * parent. Comparison is case-insensitive so a backend that ever uppercases
 * them does not silently misclassify.
 */
export function classifyConstituent(
  constituent: EnvironmentBackupConstituentItem,
): ConstituentOutcome {
  if (constituent.error != null) return "error";
  if (constituent.backup == null) return "missing";
  switch (constituent.backup.status.toLowerCase()) {
    case "completed":
      return "completed";
    case "failed":
      return "failed";
    default:
      return "in-flight";
  }
}

/**
 * Fold the per-constituent outcomes into the counts the snapshot row shows.
 *
 * Built on `classifyConstituent` so the collapsed counts and the expanded
 * per-constituent rows can never disagree about a constituent.
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
    switch (classifyConstituent(constituent)) {
      case "completed":
        summary.completed += 1;
        break;
      // A constituent that never got a backup row and one whose backup failed
      // are both "not covered by this snapshot" for the collapsed count.
      case "error":
      case "failed":
        summary.failed += 1;
        break;
      case "missing":
        summary.missing += 1;
        break;
      default:
        summary.inFlight += 1;
    }
  }

  return summary;
}

/** Human-readable detail for one constituent in the expanded outcome list. */
export function describeConstituent(
  constituent: EnvironmentBackupConstituentItem,
): string {
  const { backup, error } = constituent;
  // The backend's messages are free text, so they are shown verbatim rather
  // than mapped through a table that would drop unknown values.
  if (error != null) return `not backed up — ${error}`;
  // A snapshot entry with no backup row is a gap: the constituent was deleted
  // individually, or expired, after the snapshot was taken (spec US3).
  if (backup == null) return "backup no longer exists (deleted or expired)";
  return backup.errorMessage
    ? `${backup.status} — ${backup.errorMessage}`
    : backup.status;
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

interface ConstituentOutcomesProps {
  constituents: readonly EnvironmentBackupConstituentItem[];
}

/**
 * The per-constituent outcome list inside an expanded snapshot (spec US3).
 *
 * This is what makes a `PARTIAL` snapshot trustworthy: before deciding to
 * restore, the operator needs to see exactly which applications are covered.
 * Every captured deployment appears exactly once — as a live constituent
 * backup, as an attributable creation error, or as a *gap* left by a
 * constituent that was deleted individually or has expired. Gaps are rendered
 * explicitly rather than omitted, because a silently missing row is
 * indistinguishable from an application that was never in the snapshot.
 */
function ConstituentOutcomes({ constituents }: ConstituentOutcomesProps) {
  if (constituents.length === 0) {
    return (
      <p
        className="text-sm text-muted-foreground"
        data-testid="environment-backup-constituents-empty"
      >
        Config-only snapshot — no application backups
      </p>
    );
  }

  return (
    <ul
      className="flex flex-col gap-1"
      data-testid="environment-backup-constituent-outcomes"
    >
      {constituents.map((constituent) => {
        const outcome = classifyConstituent(constituent);
        return (
          <li
            key={constituent.deploymentId}
            className="flex items-center gap-2 text-xs text-muted-foreground"
            data-testid="environment-backup-constituent"
            data-deployment-id={constituent.deploymentId}
            data-deployment-name={constituent.deploymentName}
            data-constituent-outcome={outcome}
            data-backup-id={constituent.backup?.id ?? ""}
            data-backup-status={constituent.backup?.status ?? ""}
          >
            <span className="font-medium text-foreground">
              {constituent.deploymentName}
            </span>
            <span>{describeConstituent(constituent)}</span>
          </li>
        );
      })}
    </ul>
  );
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
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
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
  const deleteMutation = useDeleteEnvironmentBackupMutation();

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

  async function handleDelete() {
    setDeleteError(null);
    setDeleteConfirmOpen(false);
    try {
      await deleteMutation.mutateAsync({
        environmentBackupId: environmentBackup.id,
      });
      await queryClient.invalidateQueries({
        queryKey: ["ListEnvironmentBackups"],
      });
    } catch (err) {
      // Surfaced inline rather than swallowed: the row is still on screen, so
      // without this the operator cannot tell a failed delete from a stale list.
      console.error("[delete-environment-backup] mutation failed", err);
      setDeleteError(err instanceof Error ? err.message : "Unknown error");
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
        <IfRole minimum="READ_WRITE">
          <Button
            size="sm"
            variant="outline"
            data-testid="environment-backup-delete-button"
            aria-label={`Delete ${environmentBackup.name}`}
            disabled={deleteMutation.isPending}
            onClick={() => setDeleteConfirmOpen(true)}
          >
            <Trash2 className="h-4 w-4" />
            {deleteMutation.isPending ? "Deleting..." : "Delete"}
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

      {deleteError && (
        <Alert
          variant="destructive"
          data-testid="environment-backup-delete-error"
        >
          <AlertDescription>{deleteError}</AlertDescription>
        </Alert>
      )}

      {expanded && (
        <div
          className="flex flex-col gap-3 px-4 py-2"
          data-testid="environment-backup-detail"
        >
          <div className="flex flex-col gap-2">
            <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Applications in this snapshot
            </span>
            <ConstituentOutcomes
              constituents={environmentBackup.constituents}
            />
          </div>
          <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Restores
          </span>
        </div>
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

      <ConfirmDialog
        open={deleteConfirmOpen}
        data-testid="environment-backup-delete-dialog"
        title="Delete this environment snapshot?"
        description={`This deletes "${environmentBackup.name}" together with its ${summary.total} application backup(s) and every restore performed from it. This cannot be undone. Deletion works even while the snapshot is still in progress — that is how a stuck snapshot is cleared.`}
        confirmLabel="Delete"
        busy={deleteMutation.isPending}
        onConfirm={() => {
          void handleDelete();
        }}
        onCancel={() => setDeleteConfirmOpen(false)}
      />
    </div>
  );
}
