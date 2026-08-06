import { StatusBadge, getStatusColor } from "@/components/StatusBadge";
import type { ListEnvironmentBackupsQuery } from "@/generated/graphql";

/** One environment backup as returned by `ListEnvironmentBackups`. */
export type EnvironmentBackupItem =
  ListEnvironmentBackupsQuery["environmentBackups"][number];

/** One eligible deployment's outcome inside an environment backup. */
export type EnvironmentBackupConstituentItem =
  EnvironmentBackupItem["constituents"][number];

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

interface EnvironmentBackupRowProps {
  environmentBackup: EnvironmentBackupItem;
  /** Row position, used only for zebra striping. */
  index: number;
}

/**
 * One environment backup in the snapshot list.
 *
 * The row publishes its identity and derived status as `data-*` attributes so
 * the Playwright scenario driver can read a snapshot without scraping visible
 * text. `data-environment-backup-status` carries the raw
 * `EnvironmentBackupStatus` enum value (`COMPLETED`, `PARTIAL`, …) so the UI
 * driver and the API driver report identical strings; the badge lowercases it
 * purely for display.
 */
export function EnvironmentBackupRow({
  environmentBackup,
  index,
}: EnvironmentBackupRowProps) {
  const summary = summarizeConstituents(environmentBackup.constituents);
  const status = environmentBackup.status;
  const colors = getStatusColor(status.toLowerCase());

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
      </div>
    </div>
  );
}
