import type { UpdateDeploymentInput } from "@/generated/graphql";
import { DEFAULT_BACKUP_TTL } from "@/lib/backup-ttl";
import { cn } from "@/lib/utils";
import { ConfigSummaryCard } from "../../ConfigSummaryCard";

interface Props {
  current: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
  /**
   * Cluster-scope projection. Only the backup-retention tile consults it,
   * because retention is the one field here whose fallback chain the operator
   * can actually observe: an unset deployment *and* environment still yields a
   * real TTL on every Velero backup, from the cluster or from the built-in
   * default. Claiming "720h (default)" while a cluster policy is in force
   * would be a false statement about live behaviour, so the tile needs this
   * layer to tell the two apart.
   *
   * The other two tiles keep their two-scope display unchanged.
   */
  cluster: UpdateDeploymentInput;
}

/**
 * Read-only summary for `dbSize`, `standardStorage.storageClass`, and
 * `backupTtl`. Rendered as a horizontal strip of
 * label/value pairs in small-caps mono labels (per Paper mock D2).
 */
export function StorageRuntimeSummary({
  current,
  environment,
  cluster,
}: Props) {
  const dbSize = resolve(current.dbSize, environment.dbSize, (v) => v ?? "—");
  const storageClass = resolve(
    current.standardStorage?.storageClass,
    environment.standardStorage?.storageClass,
    (v) => v ?? "—",
  );
  const backupTtl = resolveBackupTtl(
    current.backupTtl,
    environment.backupTtl,
    cluster.backupTtl,
  );

  return (
    <ConfigSummaryCard title="Storage & Runtime">
      {/* Three tiles: two-up on small screens rather than three-up, so the
          mono values are not crushed on a narrow viewport. */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Pair label="DB SIZE" {...dbSize} />
        <Pair label="STORAGE CLASS" {...storageClass} />
        <Pair label="BACKUP TTL" testId="storage-backup-ttl" {...backupTtl} />
      </div>
    </ConfigSummaryCard>
  );
}

function Pair({
  label,
  value,
  inherited,
  // Which scope the value came from, rendered as a parenthetical when the
  // deployment itself did not set it. Defaults to `env` so the pre-existing
  // tiles render exactly as before.
  origin = "env",
  testId,
}: {
  label: string;
  value: string;
  inherited: boolean;
  origin?: string;
  testId?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="font-mono text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <span
        data-testid={testId}
        data-inherited={inherited ? "true" : "false"}
        data-origin={origin}
        className={cn(
          "font-mono text-sm",
          inherited
            ? "italic text-muted-foreground"
            : "font-medium text-blue-700 dark:text-blue-300",
        )}
      >
        {value}
        {inherited ? <span className="ml-1 not-italic">({origin})</span> : null}
      </span>
    </div>
  );
}

function resolve<T>(
  deploymentValue: T | null | undefined,
  environmentValue: T | null | undefined,
  formatter: (v: T | null | undefined) => string,
): { value: string; inherited: boolean } {
  if (deploymentValue !== undefined && deploymentValue !== null) {
    return { value: formatter(deploymentValue), inherited: false };
  }
  if (environmentValue !== undefined && environmentValue !== null) {
    return { value: formatter(environmentValue), inherited: true };
  }
  return { value: "not set", inherited: true };
}

/**
 * Resolve the retention policy actually in force, deepest scope wins
 * (016-backup-retention-ttl, FR-003).
 *
 * Unlike {@link resolve}, this never reports "not set": there is no such
 * state for retention. Every Velero backup gets a `spec.ttl`, so when no
 * scope sets a policy the built-in {@link DEFAULT_BACKUP_TTL} applies and the
 * tile says so — a blank or "not set" here would suggest backups are kept
 * forever, which is the opposite of what happens.
 *
 * The `origin` distinguishes the three inherited cases so the operator knows
 * *where* to go to change it.
 */
function resolveBackupTtl(
  deploymentValue: string | null | undefined,
  environmentValue: string | null | undefined,
  clusterValue: string | null | undefined,
): { value: string; inherited: boolean; origin: string } {
  if (deploymentValue != null) {
    return { value: deploymentValue, inherited: false, origin: "deployment" };
  }
  if (environmentValue != null) {
    return { value: environmentValue, inherited: true, origin: "env" };
  }
  if (clusterValue != null) {
    return { value: clusterValue, inherited: true, origin: "cluster" };
  }
  return { value: DEFAULT_BACKUP_TTL, inherited: true, origin: "default" };
}
